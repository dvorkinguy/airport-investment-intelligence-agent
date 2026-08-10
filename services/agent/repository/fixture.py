"""Fixture repository - the same contract, served from a JSON snapshot.

Exists so the agent, the tools, the tests and the evals can all run with no
database and no network. Filtering, ordering and error behaviour mirror
``PostgresRepo`` statement-for-statement; a tool cannot tell them apart.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.repository.base import (
    SUPPORTED_METRICS,
    RepoError,
    Row,
    UnknownAirportError,
    normalize_iata,
    normalize_region,
    normalize_states,
)

DEFAULT_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "dataset.json"


class FixtureRepo:
    """Implements ``AirportRepo`` against ``fixtures/dataset.json``."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else DEFAULT_FIXTURE
        if not self._path.exists():
            raise RepoError(f"fixture dataset not found: {self._path}")
        data = json.loads(self._path.read_text(encoding="utf-8"))
        self._meta: dict[str, Any] = data.get("_meta", {})
        self._airports: list[Row] = data["airports"]
        self._regions: list[Row] = data["regions"]
        self._metrics: list[Row] = data["v_airport_metrics"]
        self._congestion: list[Row] = data["v_congestion"]
        self._scores: list[Row] = data["v_opportunity_score"]
        self._unmet: list[Row] = data["v_unmet_demand_est"]

    async def open(self) -> None:  # symmetry with PostgresRepo
        return None

    async def close(self) -> None:
        return None

    # --- Contract ---------------------------------------------------------

    async def resolve_airport(self, query: str, limit: int = 5) -> list[Row]:
        q = (query or "").strip()
        if not q:
            raise RepoError("resolve_airport requires a non-empty query")
        exact, needle = q.upper(), q.lower()
        hits = [
            a for a in self._airports
            if a["iata"] == exact
            or a["icao"] == exact
            or needle in a["name"].lower()
            or needle in a["city"].lower()
        ]
        hits.sort(key=lambda a: (a["iata"] != exact, a["icao"] != exact, a["name"]))
        return [dict(a) for a in hits[: max(1, min(int(limit), 25))]]

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

        allowed: set[str] | None = None
        if region_n:
            allowed = {r["state"] for r in self._regions if r["region"] == region_n}
            if not allowed:
                raise RepoError(
                    f"region '{region_n}' is not defined in the dataset; "
                    "pass explicit states instead"
                )
        if states_n:
            allowed = set(states_n) if allowed is None else allowed & set(states_n)

        by_iata = {a["iata"]: a for a in self._airports}
        rows: list[Row] = []
        for s in self._scores:
            a = by_iata.get(s["iata"])
            if not a or (allowed is not None and a["state"] not in allowed):
                continue
            rows.append(
                {
                    "iata": s["iata"],
                    "name": a["name"],
                    "city": a["city"],
                    "state": a["state"],
                    "score_0_100": s["score_0_100"],
                    "c_pax_growth": s["c_pax_growth"],
                    "c_load_factor": s["c_load_factor"],
                    "c_congestion": s["c_congestion"],
                    "c_flight_growth": s["c_flight_growth"],
                    "c_infra": s["c_infra"],
                    "runways_count": a["runways_count"],
                    "max_runway_length_ft": a["max_runway_length_ft"],
                }
            )
        rows.sort(key=lambda r: (-(r["score_0_100"] or 0), r["iata"]))
        return rows[: max(1, min(int(limit), 50))]

    def _per_year(self, table: list[Row], iata: str, years: int, what: str) -> list[Row]:
        code = normalize_iata(iata)
        rows = sorted(
            (dict(r) for r in table if r["iata"] == code),
            key=lambda r: r["year"],
            reverse=True,
        )
        if not rows:
            raise UnknownAirportError(f"no {what} rows for airport '{code}' in the dataset")
        return rows[: max(1, min(int(years), 20))]

    async def airport_metrics(self, iata: str, years: int = 3) -> list[Row]:
        return self._per_year(self._metrics, iata, years, "traffic")

    async def congestion(self, iata: str, years: int = 3) -> list[Row]:
        return self._per_year(self._congestion, iata, years, "congestion")

    async def unmet_demand(self, iata: str, years: int = 3) -> list[Row]:
        return self._per_year(self._unmet, iata, years, "unmet-demand")

    async def data_vintage(self) -> dict[str, Any]:
        vintage = self._meta.get("vintage", {})
        years = [m["year"] for m in self._metrics]
        return {
            "source": vintage.get("source", "fixture"),
            "first_year": vintage.get("first_year", min(years) if years else None),
            "last_year": vintage.get("last_year", max(years) if years else None),
            "airports": len(self._airports),
            "backend": "fixture",
            "warning": self._meta.get("warning"),
        }

    async def ping(self) -> bool:
        return bool(self._airports)
