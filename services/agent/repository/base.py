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

SUPPORTED_METRICS = ("opportunity",)

#: Long-haul threshold, documented so every answer can cite it.
LONG_HAUL_THRESHOLD_MILES = 1500


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

    async def data_vintage(self) -> dict[str, Any]:
        """Year coverage of the dataset, cited in every answer."""
        ...

    async def ping(self) -> bool:
        """Cheap liveness probe used by /health."""
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
