"""Postgres (Neon) repository - read-only SQL against the scoring views.

Read-only is enforced three ways, not by convention:
  1. every statement runs inside ``SET TRANSACTION READ ONLY``;
  2. only literal SELECT statements exist in this module - nothing is built from
     user input, every value is a bound parameter;
  3. a per-statement ``statement_timeout`` caps a runaway query.

If a view is missing (data workstream not finished, wrong database) the error is
surfaced verbatim to the agent, which then says so instead of inventing numbers.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import psycopg

from agent.db import build_pool, pool_stats, with_stale_retry
from agent.logging_config import get_logger
from agent.repository.base import (
    SUPPORTED_METRICS,
    RepoError,
    Row,
    UnknownAirportError,
    normalize_iata,
    normalize_region,
    normalize_states,
)

log = get_logger(__name__)

# --- Statements (literal, parameterised, SELECT-only) --------------------

Q_RESOLVE = """
SELECT iata, icao, name, city, state, lat, lon,
       runways_count, max_runway_length_ft
FROM airports
WHERE iata = %(exact)s
   OR icao = %(exact)s
   OR name ILIKE %(like)s
   OR city ILIKE %(like)s
ORDER BY (iata = %(exact)s) DESC, (icao = %(exact)s) DESC, name ASC
LIMIT %(limit)s
"""

Q_RANK = """
SELECT s.iata, a.name, a.city, a.state,
       s.score_0_100, s.c_pax_growth, s.c_load_factor, s.c_congestion,
       s.c_flight_growth, s.c_infra,
       a.runways_count, a.max_runway_length_ft
FROM v_opportunity_score s
JOIN airports a ON a.iata = s.iata
WHERE (%(region)s::text IS NULL
       OR a.state IN (SELECT state FROM regions WHERE region = %(region)s))
  AND (%(states)s::text[] IS NULL OR a.state = ANY(%(states)s::text[]))
ORDER BY s.score_0_100 DESC NULLS LAST, s.iata ASC
LIMIT %(limit)s
"""

Q_METRICS = """
SELECT iata, year, passengers, seats, departures, load_factor, long_haul_pct,
       pax_growth_yoy, seat_growth_yoy, flight_growth_yoy
FROM v_airport_metrics
WHERE iata = %(iata)s
ORDER BY year DESC
LIMIT %(years)s
"""

Q_CONGESTION = """
SELECT iata, year, delay_rate, avg_delay_min
FROM v_congestion
WHERE iata = %(iata)s
ORDER BY year DESC
LIMIT %(years)s
"""

Q_UNMET = """
SELECT iata, year, est_unmet_pax, driver_load_factor, driver_growth_gap,
       driver_delay_rate
FROM v_unmet_demand_est
WHERE iata = %(iata)s
ORDER BY year DESC
LIMIT %(years)s
"""

Q_VINTAGE = """
SELECT MIN(year) AS first_year, MAX(year) AS last_year,
       COUNT(DISTINCT iata) AS airports
FROM v_airport_metrics
"""


def coerce_numeric(value: Any) -> Any:
    """Postgres NUMERIC arrives as ``Decimal``, which JSON-encodes as a string.

    A passenger count reaching the model as ``"3180000.00"`` is a number the model
    then has to reformat - and reformatting is where invented digits creep in.
    Integral values become ``int``, fractional ones ``float``, matching the
    fixture backend exactly.
    """
    if isinstance(value, Decimal):
        as_float = float(value)
        return int(as_float) if as_float.is_integer() else as_float
    return value


class PostgresRepo:
    """Implements ``AirportRepo`` against Neon."""

    def __init__(
        self,
        dsn: str,
        *,
        min_size: int = 0,
        max_size: int = 3,
        statement_timeout_ms: int = 15_000,
        max_idle_seconds: float = 30.0,
        max_lifetime_seconds: float = 300.0,
    ) -> None:
        self._statement_timeout_ms = int(statement_timeout_ms)
        self._pool = build_pool(
            dsn,
            autocommit=False,
            min_size=min_size,
            max_size=max_size,
            max_idle_seconds=max_idle_seconds,
            max_lifetime_seconds=max_lifetime_seconds,
        )

    async def open(self) -> None:
        await self._pool.open(wait=True, timeout=15)
        log.info("postgres pool opened")

    async def close(self) -> None:
        await self._pool.close()

    # --- Core execution ---------------------------------------------------

    async def _run_select(self, sql: str, params: dict[str, Any]) -> list[Row]:
        async with self._pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute("SET TRANSACTION READ ONLY")
                    await cur.execute(
                        f"SET LOCAL statement_timeout = {self._statement_timeout_ms}"
                    )
                    await cur.execute(sql, params)
                    return [
                        {k: coerce_numeric(v) for k, v in row.items()}
                        for row in await cur.fetchall()
                    ]

    async def _select(self, sql: str, params: dict[str, Any]) -> list[Row]:
        try:
            # Read-only and side-effect free, so a retry is always safe.
            return await with_stale_retry(
                lambda: self._run_select(sql, params), what="repo.select"
            )
        except psycopg.errors.UndefinedTable as exc:
            raise RepoError(
                f"required table/view is not present in the database: {exc}"
            ) from exc
        except psycopg.errors.QueryCanceled as exc:
            raise RepoError("query exceeded the statement timeout") from exc
        except psycopg.Error as exc:
            raise RepoError(f"database error: {exc}") from exc

    # --- Contract ---------------------------------------------------------

    async def resolve_airport(self, query: str, limit: int = 5) -> list[Row]:
        q = (query or "").strip()
        if not q:
            raise RepoError("resolve_airport requires a non-empty query")
        return await self._select(
            Q_RESOLVE,
            {"exact": q.upper(), "like": f"%{q}%", "limit": max(1, min(int(limit), 25))},
        )

    async def rank_airports(
        self,
        *,
        region: str | None = None,
        states: list[str] | None = None,
        metric: str = "opportunity",
        limit: int = 10,
    ) -> list[Row]:
        if metric not in SUPPORTED_METRICS:
            raise RepoError(
                f"metric '{metric}' is not available; supported: {', '.join(SUPPORTED_METRICS)}"
            )
        region_n, states_n = normalize_region(region), normalize_states(states)
        if not region_n and not states_n:
            raise RepoError("rank_airports requires either a region or a list of states")
        return await self._select(
            Q_RANK,
            {
                "region": region_n,
                "states": states_n,
                "limit": max(1, min(int(limit), 50)),
            },
        )

    async def _per_year(self, sql: str, iata: str, years: int, what: str) -> list[Row]:
        code = normalize_iata(iata)
        rows = await self._select(sql, {"iata": code, "years": max(1, min(int(years), 20))})
        if not rows:
            raise UnknownAirportError(f"no {what} rows for airport '{code}' in the dataset")
        return rows

    async def airport_metrics(self, iata: str, years: int = 3) -> list[Row]:
        return await self._per_year(Q_METRICS, iata, years, "traffic")

    async def congestion(self, iata: str, years: int = 3) -> list[Row]:
        return await self._per_year(Q_CONGESTION, iata, years, "congestion")

    async def unmet_demand(self, iata: str, years: int = 3) -> list[Row]:
        return await self._per_year(Q_UNMET, iata, years, "unmet-demand")

    async def data_vintage(self) -> dict[str, Any]:
        rows = await self._select(Q_VINTAGE, {})
        row = rows[0] if rows else {}
        return {
            "source": "BTS T-100 segments + BTS on-time performance (via Neon views)",
            "first_year": row.get("first_year"),
            "last_year": row.get("last_year"),
            "airports": row.get("airports"),
            "backend": "postgres",
        }

    async def ping(self) -> bool:
        await self._select("SELECT 1 AS ok", {})
        return True

    def stats(self) -> dict[str, Any]:
        return pool_stats(self._pool)
