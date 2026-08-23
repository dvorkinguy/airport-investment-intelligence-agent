"""Data contract shared by every repository backend.

The column lists below ARE the contract agreed with the data workstream. Both
``PostgresRepo`` (Neon views) and ``FixtureRepo`` (JSON) return dictionaries with
exactly these keys, so a tool cannot tell which backend answered it.

    airports(iata, icao, name, city, state, lat, lon,
             runways_count, max_runway_length_ft)
    regions(state, region)                          region 'new_england' = CT ME MA NH RI VT
    v_airport_metrics(iata, year, passengers, seats, departures, load_factor,
                      long_haul_pct, pax_growth_yoy, seat_growth_yoy,
                      flight_growth_yoy)
    v_congestion(iata, year, delay_rate, avg_delay_min)
    v_opportunity_score(iata, score_0_100, c_pax_growth, c_load_factor,
                        c_congestion, c_flight_growth, c_infra)
    v_unmet_demand_est(iata, year, est_unmet_pax, driver_load_factor,
                       driver_growth_gap, driver_delay_rate)

T2.5 additions (ADR-004). Optional by design: these views may not exist on a
database that only has the Tier 1 build, so their repository methods return an
empty list instead of raising, and the tool degrades one source at a time.

    v_carrier_concentration(iata, year, hhi, top_carrier, top_carrier_share)
    airport_financials(locid, fy, op_revenue, op_expenses, enplanements,
                       net_rev_per_enplanement)
    v_roi_proxy(iata, year, roi_proxy)

``airport_financials`` is the one table whose key columns are named differently
(``locid``/``fy``, FAA Form 127 vocabulary). The repository aliases them to
``iata``/``year`` so every row a tool sees is on the same grain.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

Row = dict[str, Any]

# --- Contract constants -------------------------------------------------

AIRPORT_COLUMNS = (
    "iata", "icao", "name", "city", "state", "lat", "lon",
    "runways_count", "max_runway_length_ft",
)
METRIC_COLUMNS = (
    "iata", "year", "passengers", "seats", "departures", "load_factor",
    "long_haul_pct", "pax_growth_yoy", "seat_growth_yoy", "flight_growth_yoy",
)
CONGESTION_COLUMNS = ("iata", "year", "delay_rate", "avg_delay_min")
SCORE_COLUMNS = (
    "iata", "score_0_100", "c_pax_growth", "c_load_factor",
    "c_congestion", "c_flight_growth", "c_infra",
)
UNMET_COLUMNS = (
    "iata", "year", "est_unmet_pax", "driver_load_factor",
    "driver_growth_gap", "driver_delay_rate",
)
CONCENTRATION_COLUMNS = ("iata", "year", "hhi", "top_carrier", "top_carrier_share")
FINANCIAL_COLUMNS = (
    "iata", "year", "op_revenue", "op_expenses", "enplanements",
    "net_rev_per_enplanement",
)
ROI_COLUMNS = ("iata", "year", "roi_proxy")

SUPPORTED_METRICS = ("opportunity",)

#: Long-haul threshold, documented so every answer can cite it.
LONG_HAUL_THRESHOLD_MILES = 1500

#: DOJ/FTC merger-guideline bands, used as a reading aid for the HHI - not a
#: regulatory claim about airports. See db/views_t25.sql and ADR-004.
HHI_UNCONCENTRATED = 1500
HHI_HIGHLY_CONCENTRATED = 2500


def hhi_band(hhi: float | int | None) -> str | None:
    """Name the concentration band so the model does not have to remember the cutoffs."""
    if hhi is None:
        return None
    if hhi < HHI_UNCONCENTRATED:
        return "unconcentrated"
    if hhi <= HHI_HIGHLY_CONCENTRATED:
        return "moderately concentrated"
    return "highly concentrated"


class RepoError(RuntimeError):
    """Any repository-level failure the tool layer should surface verbatim."""


class UnknownAirportError(RepoError):
    """The requested IATA code is not present in the dataset."""


@runtime_checkable
class AirportRepo(Protocol):
    """Read-only access to the airport dataset. No method ever writes."""

    async def resolve_airport(self, query: str, limit: int = 5) -> list[Row]:
        """Match an IATA/ICAO code, airport name, or city to airport rows."""
        ...

    async def rank_airports(
        self,
        *,
        region: str | None = None,
        states: list[str] | None = None,
        metric: str = "opportunity",
        limit: int = 10,
    ) -> list[Row]:
        """Rank airports by a scoring view, filtered by region or by states."""
        ...

    async def airport_metrics(self, iata: str, years: int = 3) -> list[Row]:
        """Per-year traffic metrics for one airport, newest year first."""
        ...

    async def congestion(self, iata: str, years: int = 3) -> list[Row]:
        """Per-year delay metrics for one airport, newest year first."""
        ...

    async def unmet_demand(self, iata: str, years: int = 3) -> list[Row]:
        """Per-year estimated unmet demand for one airport, newest year first."""
        ...

    # --- T2.5 (ADR-004). Empty list, never an exception, when absent. ---

    async def carrier_concentration(self, iata: str, years: int = 3) -> list[Row]:
        """Per-year HHI and top carrier for one airport, newest year first."""
        ...

    async def financials(self, iata: str, years: int = 3) -> list[Row]:
        """Per-fiscal-year FAA Form 127 financials, newest first, keyed as iata/year."""
        ...

    async def roi_proxy(self, iata: str, years: int = 3) -> list[Row]:
        """Per-year expansion-value ESTIMATE for one airport, newest year first."""
        ...

    async def data_vintage(self) -> dict[str, Any]:
        """Year coverage of the dataset, cited in every answer."""
        ...

    async def ping(self) -> bool:
        """Cheap liveness probe used by /health."""
        ...

    async def refresh_status(self) -> dict[str, Any]:
        """Scheduled-ingestion state (ADR-005), read from ``data_refresh_runs``.

        Returns ``{}`` when the table does not exist, is empty, or the query
        fails - all three are ordinary pre-launch states (this workstream can
        land before or after ADR-005 ships), never raised as an error. When
        non-empty, keys are:

            last_successful_at   datetime | None  ``finished_at`` of the
                                  newest run whose status is 'success' or
                                  'no_change'. A 'failed' run must never
                                  advance this - that is the whole honesty
                                  of the endpoint this feeds.
            latest_period         str | None       from that same run.
            sources                list[str] | None from that same run.
            last_run_status       str | None       status of the newest run
                                  of ANY status ('success' | 'no_change' |
                                  'failed' | 'running') - surfaced as-is, so
                                  a failed attempt is reported honestly
                                  rather than hidden behind an old good
                                  timestamp. A 'running' row older than the
                                  job's task timeout is stale and is treated
                                  as if it does not exist.
            last_run_started_at  datetime | None  ``started_at`` of that
                                  same newest-run row - used only to anchor
                                  a next-scheduled estimate, never to
                                  advance ``last_successful_at``.
        """
        ...


def normalize_iata(value: str) -> str:
    return (value or "").strip().upper()


def normalize_states(states: list[str] | None) -> list[str] | None:
    if not states:
        return None
    return [s.strip().upper() for s in states if s and s.strip()]


def normalize_region(region: str | None) -> str | None:
    if not region:
        return None
    return region.strip().lower().replace(" ", "_").replace("-", "_")
