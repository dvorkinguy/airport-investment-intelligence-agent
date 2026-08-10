"""The agent tools.

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

from agent import faa
from agent.logging_config import get_logger
from agent.repository.base import (
    HHI_HIGHLY_CONCENTRATED,
    HHI_UNCONCENTRATED,
    LONG_HAUL_THRESHOLD_MILES,
    AirportRepo,
    RepoError,
    hhi_band,
)
from agent.settings import Settings, get_settings

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
A_NO_VINTAGE = (
    "The dataset holds no yearly rows yet, so its data vintage is UNKNOWN. State that "
    "the vintage is unknown; do not name a year, a cutoff or an 'as of' date."
)
A_HHI = (
    "Carrier concentration is the Herfindahl-Hirschman Index of an airport's carrier "
    "passenger shares on the standard 0-10,000 scale, computed from BTS T-100 scheduled "
    f"passenger service only (cargo excluded). Bands used for reading it: below "
    f"{HHI_UNCONCENTRATED:,} unconcentrated, {HHI_UNCONCENTRATED:,}-{HHI_HIGHLY_CONCENTRATED:,} "
    f"moderately concentrated, above {HHI_HIGHLY_CONCENTRATED:,} highly concentrated - the "
    "DOJ/FTC merger-guideline convention, used here as an interpretation aid and not as a "
    "regulatory claim about airports."
)
A_FINANCIALS = (
    "Airport financials come from FAA Form 127 (CATS) filings. net_rev_per_enplanement is "
    "(operating revenue - operating expenses) / enplanements, computed from the filing "
    "rather than published by the FAA; a negative value means the airport ran an operating "
    "loss per passenger that year. Form 127 filings lag the fiscal year they cover, so the "
    "newest financial year available is older than the newest traffic year."
)
A_ROI = (
    "roi_proxy is an ESTIMATE BUILT ON AN ESTIMATE: estimated unmet passengers multiplied by "
    "net revenue per enplanement. It is a rough expansion-value proxy, not a financial "
    "projection - it ignores capacity cost, fare-mix shift and demand elasticity."
)
A_FAA_LIVE = (
    "FAA National Airspace System status is a live snapshot of today's operations - ground "
    "stops, ground delay programmes, closures - at the feed's stated update time. It reflects "
    "current weather and traffic management. It is NOT evidence about long-term investment "
    "merit and must never be used to argue for or against an expansion case."
)


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def _error(
    tool_name: str, message: str, assumptions: list[str] | None = None
) -> tuple[str, dict[str, Any]]:
    log.warning("tool failed", extra={"tool": tool_name, "error": message})
    assumptions = assumptions or []
    return (
        _dump(
            {
                "error": message,
                "instruction": (
                    "Tell the user this figure is unavailable and why. Do not "
                    "substitute an estimate or a remembered number, and do not "
                    "state a data vintage that is not in this payload."
                ),
                "assumptions": assumptions,
            }
        ),
        {"tool": tool_name, "ok": False, "assumptions": assumptions, "error": message},
    )


def _ok(
    tool_name: str, payload: dict[str, Any], assumptions: list[str]
) -> tuple[str, dict[str, Any]]:
    content = {**payload, "assumptions": assumptions}
    return _dump(content), {"tool": tool_name, "ok": True, "assumptions": assumptions, **payload}


def build_tools(repo: AirportRepo, settings: Settings | None = None) -> list[BaseTool]:
    """Bind the read-only tools to a repository backend."""
    s = settings or get_settings()

    async def _vintage_line() -> tuple[str, dict[str, Any]]:
        v = await repo.data_vintage()
        first, last = v.get("first_year"), v.get("last_year")
        if first is None or last is None:
            # A vintage rendered as "None-None" is worse than no vintage: it reads
            # as a broken field, and the model quietly replaces it with its own
            # training cutoff. Say "unknown" out loud instead.
            return A_NO_VINTAGE, v
        return A_VINTAGE.format(first_year=first, last_year=last, source=v.get("source")), v

    async def _fail(tool_name: str, message: str) -> tuple[str, dict[str, Any]]:
        """Failure payloads still carry the vintage.

        Left with no vintage, a model fills the gap from memory - an earlier run
        answered "the data is current as of October 2023", which was its own
        training cutoff, not this dataset.
        """
        try:
            vintage, _ = await _vintage_line()
            return _error(tool_name, message, [vintage])
        except Exception:
            return _error(tool_name, message, ["The data vintage could not be read."])

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
            return await _fail("resolve_airport", str(exc))
        if not rows:
            return await _fail("resolve_airport", f"no airport in the dataset matches '{query}'")
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
            return await _fail("rank_airports", str(exc))
        if not rows:
            return await _fail(
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
            return await _fail("airport_metrics", str(exc))
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
            return await _fail("compare_airports", str(exc))
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
            return await _fail("unmet_demand_estimate", str(exc))
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

    @tool(response_format="content_and_artifact")
    async def investment_context(iata: str, years: int = 2) -> tuple[str, dict[str, Any]]:
        """Carrier concentration, airport finances and an expansion-ROI estimate for one airport.

        The financial reality check behind a capacity case. Returns three things:
        carrier concentration (HHI plus the top carrier and its share, i.e. how much
        of the airport's service rides on one airline's decisions); FAA Form 127
        operating revenue, expenses and net revenue per enplanement; and roi_proxy,
        an estimated expansion value. Use it whenever the question asks whether an
        airport is a financially sound or healthy investment, and alongside a
        ranking or an unmet-demand answer to test whether the airport can actually
        fund or benefit from the capacity.

        Each of the three sources is optional and reported as unavailable on its own
        if that airport did not file or the view is not deployed.

        Args:
            iata: IATA code (e.g. "BGR") or a place name to resolve.
            years: How many recent years to return per source (default 2).
        """
        try:
            code = await _coerce_iata(iata)
        except RepoError as exc:
            return await _fail("investment_context", str(exc))

        sources: dict[str, Any] = {}
        available: list[str] = []
        for key, fetch in (
            ("carrier_concentration", repo.carrier_concentration),
            ("financials", repo.financials),
            ("roi_proxy_estimate", repo.roi_proxy),
        ):
            try:
                rows = await fetch(code, years=years)
            except RepoError as exc:
                # One missing view must not cost the other two.
                sources[key] = {"unavailable": str(exc)}
                continue
            if not rows:
                sources[key] = {"unavailable": f"no {key.replace('_', ' ')} rows for {code}"}
                continue
            if key == "carrier_concentration":
                rows = [{**r, "concentration_band": hhi_band(r.get("hhi"))} for r in rows]
            sources[key] = rows
            available.append(key)

        if not available:
            return await _fail(
                "investment_context",
                f"no carrier-concentration, financial or ROI-estimate rows exist for {code}",
            )

        vintage, _ = await _vintage_line()
        assumptions = [A_HHI, A_FINANCIALS, A_ROI, vintage]
        financial_years = sorted(
            {r["year"] for r in sources.get("financials", []) if isinstance(r, dict) and "year" in r},
            reverse=True,
        )
        return _ok(
            "investment_context",
            {
                "iata": code,
                "sources_available": available,
                "financial_years_covered": financial_years,
                "roi_proxy_label": "ESTIMATE",
                **sources,
            },
            assumptions,
        )

    @tool(response_format="content_and_artifact")
    async def faa_live_status(iata: str) -> tuple[str, dict[str, Any]]:
        """Live FAA operational status for one airport: ground stops, delays, closures.

        Reads the FAA National Airspace System status feed for what is happening at
        this airport RIGHT NOW. Use it only when the user asks about current or
        today's conditions, delays or closures.

        This is an operations snapshot, not investment evidence. Never cite it as a
        reason to invest or not invest in an airport, and never mix it into a
        historical trend: a thunderstorm this afternoon says nothing about a terminal
        expansion case. Historical congestion belongs to `compare_airports`.

        Args:
            iata: IATA code (e.g. "BOS") or a place name to resolve.
        """
        try:
            code = await _coerce_iata(iata)
        except RepoError as exc:
            return await _fail("faa_live_status", str(exc))
        status = await faa.airport_status(
            code,
            url=s.faa_status_url,
            timeout=s.faa_timeout_seconds,
            ttl=s.faa_cache_seconds,
        )
        if not status.get("available"):
            # A dead external feed is a normal outcome, reported as data, not an error:
            # the rest of the answer is built on SQL and stays valid.
            return _ok(
                "faa_live_status",
                {
                    "iata": code,
                    "live_status_available": False,
                    "reason": status.get("error"),
                    "instruction": (
                        "Say the FAA live feed is unavailable right now. Do not "
                        "substitute historical delay data for live status."
                    ),
                },
                [A_FAA_LIVE],
            )
        return _ok(
            "faa_live_status",
            {"live_status_available": True, "source": "FAA NAS status feed", **status},
            [A_FAA_LIVE],
        )

    return [
        resolve_airport,
        rank_airports,
        airport_metrics,
        compare_airports,
        unmet_demand_estimate,
        investment_context,
        faa_live_status,
    ]


TOOL_NAMES = (
    "resolve_airport",
    "rank_airports",
    "airport_metrics",
    "compare_airports",
    "unmet_demand_estimate",
    "investment_context",
    "faa_live_status",
)
