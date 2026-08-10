"""The five agent tools.

Every tool is read-only, bound to an ``AirportRepo``, and returns
``(content, artifact)``:

* **content** - a compact JSON string the model reads. It carries the numbers,
  the assumptions that apply to them, and the data vintage, so the model never
  has to remember or infer any of the three.
* **artifact** - structured payload the graph keeps out of the prompt. The
  ``assumptions`` list is merged into typed graph state by the tools node, so the
  API can return the exact assumption set behind an answer.

A repository failure is returned as an ``error`` payload rather than raised: the
model must be able to say "the data is not available" instead of guessing.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool, tool

from agent.logging_config import get_logger
from agent.repository.base import (
    LONG_HAUL_THRESHOLD_MILES,
    AirportRepo,
    RepoError,
)

log = get_logger(__name__)

# --- Assumption text (single source of truth, cited verbatim in answers) ---

A_VINTAGE = "Figures cover {first_year}-{last_year} ({source}); nothing after {last_year} is in scope."
A_SCORE = (
    "The opportunity score is a deterministic 0-100 SQL composite of five published "
    "components (passenger growth, load factor, congestion, flight growth, "
    "infrastructure). Weights live in the database view, not in the model."
)
A_REGION = "Region 'new_england' is defined as CT, ME, MA, NH, RI and VT."
A_LONG_HAUL = (
    f"Long-haul means a segment distance of at least {LONG_HAUL_THRESHOLD_MILES} miles; "
    "long_haul_pct is the share of departing flights meeting that threshold."
)
A_CONGESTION = (
    "Congestion is measured from BTS on-time data as delay_rate (share of delayed "
    "departures) and avg_delay_min (average delay in minutes). It is a historical "
    "annual average, not live airport status."
)
A_UNMET = (
    "Unmet demand is an ESTIMATE, not an observed statistic. No public source reports "
    "it directly. est_unmet_pax = max(0, demand pressure - available capacity), derived "
    "from load factor, the passenger-vs-seat growth gap and persistent delay rates."
)
A_RANK_SCOPE = (
    "Ranking covers only airports present in the dataset; an airport with no BTS rows "
    "cannot appear and its absence is not evidence against it."
)


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def _error(tool_name: str, message: str) -> tuple[str, dict[str, Any]]:
    log.warning("tool failed", extra={"tool": tool_name, "error": message})
    return (
        _dump(
            {
                "error": message,
                "instruction": (
                    "Tell the user this figure is unavailable and why. "
                    "Do not substitute an estimate or a remembered number."
                ),
            }
        ),
        {"tool": tool_name, "ok": False, "assumptions": [], "error": message},
    )


def _ok(
    tool_name: str, payload: dict[str, Any], assumptions: list[str]
) -> tuple[str, dict[str, Any]]:
    content = {**payload, "assumptions": assumptions}
    return _dump(content), {"tool": tool_name, "ok": True, "assumptions": assumptions, **payload}


def build_tools(repo: AirportRepo) -> list[BaseTool]:
    """Bind the five read-only tools to a repository backend."""

    async def _vintage_line() -> tuple[str, dict[str, Any]]:
        v = await repo.data_vintage()
        return A_VINTAGE.format(
            first_year=v.get("first_year"),
            last_year=v.get("last_year"),
            source=v.get("source"),
        ), v

    async def _coerce_iata(value: str) -> str:
        """Accept a code or a place name; return a dataset IATA code."""
        candidate = (value or "").strip()
        if len(candidate) == 3 and candidate.isalpha():
            return candidate.upper()
        hits = await repo.resolve_airport(candidate, limit=1)
        if not hits:
            raise RepoError(f"could not resolve '{value}' to an airport in the dataset")
        return hits[0]["iata"]

    @tool(response_format="content_and_artifact")
    async def resolve_airport(query: str) -> tuple[str, dict[str, Any]]:
        """Resolve an airport name, city or code to its IATA code and reference facts.

        Use this first whenever the user names a place rather than a code (for example
        "Los Angeles", "Santa Ana", "Anchorage"). Returns IATA/ICAO codes, city, state,
        coordinates, runway count and longest runway length.

        Args:
            query: Airport name, city name, IATA code or ICAO code.
        """
        try:
            rows = await repo.resolve_airport(query, limit=5)
        except RepoError as exc:
            return _error("resolve_airport", str(exc))
        if not rows:
            return _error("resolve_airport", f"no airport in the dataset matches '{query}'")
        vintage, _ = await _vintage_line()
        return _ok(
            "resolve_airport",
            {"query": query, "matches": rows, "match_count": len(rows)},
            ["Airport identity and infrastructure come from FAA/OurAirports reference data.", vintage],
        )

    @tool(response_format="content_and_artifact")
    async def rank_airports(
        region: str | None = None,
        states: list[str] | None = None,
        metric: str = "opportunity",
        limit: int = 10,
    ) -> tuple[str, dict[str, Any]]:
        """Rank airports by investment-opportunity score, with the score components.

        This is the tool for "where should we expand", "best candidates in <region>",
        or any ranked shortlist. Pass either a region ("new_england") or an explicit
        list of two-letter state codes. Returns each airport's 0-100 score plus the
        five components behind it, so the ranking can be explained rather than asserted.

        Args:
            region: Named region, e.g. "new_england" (CT, ME, MA, NH, RI, VT).
            states: Two-letter state codes, used instead of or alongside region.
            metric: Ranking metric. Only "opportunity" is available.
            limit: Maximum number of airports to return (1-50).
        """
        try:
            rows = await repo.rank_airports(
                region=region, states=states, metric=metric, limit=limit
            )
        except RepoError as exc:
            return _error("rank_airports", str(exc))
        if not rows:
            return _error(
                "rank_airports",
                f"no scored airports found for region={region!r} states={states!r}",
            )
        vintage, _ = await _vintage_line()
        assumptions = [A_SCORE, A_RANK_SCOPE, vintage]
        if region and "new_england" in region.lower().replace("-", "_").replace(" ", "_"):
            assumptions.insert(1, A_REGION)
        return _ok(
            "rank_airports",
            {
                "metric": metric,
                "region": region,
                "states": states,
                "ranked": rows,
                "returned": len(rows),
            },
            assumptions,
        )

    @tool(response_format="content_and_artifact")
    async def airport_metrics(iata: str, years: int = 3) -> tuple[str, dict[str, Any]]:
        """Per-year traffic metrics for one airport, newest year first.

        Returns passengers, seats, departures, load factor, long-haul share of flights,
        and year-over-year passenger / seat / flight growth. Use this for any single
        airport question, including long-haul share.

        Args:
            iata: IATA code (e.g. "ANC") or a place name to resolve.
            years: How many recent years to return (default 3).
        """
        try:
            code = await _coerce_iata(iata)
            rows = await repo.airport_metrics(code, years=years)
        except RepoError as exc:
            return _error("airport_metrics", str(exc))
        vintage, _ = await _vintage_line()
        return _ok(
            "airport_metrics",
            {"iata": code, "years_returned": len(rows), "metrics": rows},
            [A_LONG_HAUL, vintage],
        )

    @tool(response_format="content_and_artifact")
    async def compare_airports(a: str, b: str, years: int = 3) -> tuple[str, dict[str, Any]]:
        """Compare two airports side by side on traffic and congestion.

        Returns each airport's per-year traffic metrics and its delay metrics
        (delay rate, average delay minutes) in one payload. Use this for any
        "X versus Y" question, especially congestion comparisons.

        Args:
            a: First airport - IATA code or place name.
            b: Second airport - IATA code or place name.
            years: How many recent years to return per airport (default 3).
        """
        try:
            code_a, code_b = await _coerce_iata(a), await _coerce_iata(b)
            side: dict[str, Any] = {}
            for code in (code_a, code_b):
                metrics = await repo.airport_metrics(code, years=years)
                try:
                    congestion = await repo.congestion(code, years=years)
                except RepoError as exc:
                    congestion = []
                    log.warning("no congestion rows", extra={"iata": code, "error": str(exc)})
                side[code] = {"metrics": metrics, "congestion": congestion}
        except RepoError as exc:
            return _error("compare_airports", str(exc))
        vintage, _ = await _vintage_line()
        return _ok(
            "compare_airports",
            {"a": code_a, "b": code_b, "comparison": side},
            [A_CONGESTION, A_LONG_HAUL, vintage],
        )

    @tool(response_format="content_and_artifact")
    async def unmet_demand_estimate(iata: str, years: int = 3) -> tuple[str, dict[str, Any]]:
        """Estimated unmet passenger demand at one airport, with its drivers.

        Returns est_unmet_pax per year plus the three drivers behind it: load factor,
        the passenger-vs-seat growth gap, and the delay rate. Latest traffic and
        congestion rows are included so the "why" can be explained from data.
        Always present the output as an estimate, never as an observed statistic.

        Args:
            iata: IATA code (e.g. "SFO") or a place name to resolve.
            years: How many recent years to return (default 3).
        """
        try:
            code = await _coerce_iata(iata)
            rows = await repo.unmet_demand(code, years=years)
            context_metrics = await repo.airport_metrics(code, years=years)
            try:
                context_congestion = await repo.congestion(code, years=years)
            except RepoError:
                context_congestion = []
        except RepoError as exc:
            return _error("unmet_demand_estimate", str(exc))
        vintage, _ = await _vintage_line()
        return _ok(
            "unmet_demand_estimate",
            {
                "iata": code,
                "estimates": rows,
                "context_metrics": context_metrics,
                "context_congestion": context_congestion,
                "label": "ESTIMATE",
            },
            [A_UNMET, A_CONGESTION, vintage],
        )

    return [
        resolve_airport,
        rank_airports,
        airport_metrics,
        compare_airports,
        unmet_demand_estimate,
    ]


TOOL_NAMES = (
    "resolve_airport",
    "rank_airports",
    "airport_metrics",
    "compare_airports",
    "unmet_demand_estimate",
)
