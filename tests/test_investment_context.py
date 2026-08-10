"""The T2.5 financial reality check (ADR-004).

Three sources behind one tool - carrier concentration, FAA Form 127 financials,
and an ROI proxy - each of which can legitimately be absent. The tests pin the
two things that make it safe to put in front of an investment question: the
figures arrive intact, and a partial dataset degrades one source at a time
instead of failing the whole answer.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from agent.repository import FixtureRepo
from agent.repository.base import RepoError, hhi_band
from agent.tools import build_tools


@pytest.fixture
def tool(repo: FixtureRepo) -> Any:
    return {t.name: t for t in build_tools(repo)}["investment_context"]


async def call(tool: Any, **args: Any) -> Any:
    return await tool.ainvoke(
        {"name": tool.name, "args": args, "id": "t1", "type": "tool_call"}
    )


def test_hhi_bands_follow_the_documented_cutoffs() -> None:
    assert hhi_band(880.4) == "unconcentrated"
    assert hhi_band(1500) == "moderately concentrated"
    assert hhi_band(2500) == "moderately concentrated"
    assert hhi_band(4142.4) == "highly concentrated"
    assert hhi_band(None) is None


async def test_all_three_sources_come_back_for_a_covered_airport(tool: Any) -> None:
    payload = json.loads((await call(tool, iata="BGR")).content)
    assert set(payload["sources_available"]) == {
        "carrier_concentration",
        "financials",
        "roi_proxy_estimate",
    }
    assert payload["iata"] == "BGR"


async def test_the_operating_loss_survives_into_the_payload(tool: Any) -> None:
    """The whole point of the tool: BGR loses money on every enplanement."""
    payload = json.loads((await call(tool, iata="BGR")).content)
    latest = payload["financials"][0]
    assert latest["net_rev_per_enplanement"] == -11.7
    assert latest["op_expenses"] > latest["op_revenue"]


async def test_the_roi_proxy_is_labelled_an_estimate(tool: Any) -> None:
    msg = await call(tool, iata="BGR")
    payload = json.loads(msg.content)
    assert payload["roi_proxy_label"] == "ESTIMATE"
    joined = " ".join(payload["assumptions"])
    assert "ESTIMATE BUILT ON AN ESTIMATE" in joined
    assert "not a financial projection" in joined


async def test_concentration_rows_are_banded_so_the_model_need_not_remember(
    tool: Any,
) -> None:
    payload = json.loads((await call(tool, iata="ANC")).content)
    assert payload["carrier_concentration"][0]["concentration_band"] == "highly concentrated"
    assert payload["carrier_concentration"][0]["top_carrier"] == "AS"


async def test_the_assumptions_explain_where_the_money_figures_come_from(
    tool: Any,
) -> None:
    joined = " ".join(json.loads((await call(tool, iata="SFO")).content)["assumptions"])
    assert "FAA Form 127" in joined
    assert "operating loss per passenger" in joined
    assert "Herfindahl-Hirschman" in joined


async def test_a_place_name_resolves_before_the_lookup(tool: Any) -> None:
    payload = json.loads((await call(tool, iata="Bangor")).content)
    assert payload["iata"] == "BGR"


# --- Degradation ---------------------------------------------------------


class PartialRepo(FixtureRepo):
    """A Tier 1-only database: the T2.5 views were never deployed."""

    async def carrier_concentration(self, iata: str, years: int = 3) -> list[dict]:
        raise RepoError('relation "v_carrier_concentration" does not exist')

    async def roi_proxy(self, iata: str, years: int = 3) -> list[dict]:
        raise RepoError('relation "v_roi_proxy" does not exist')


class BareRepo(PartialRepo):
    async def financials(self, iata: str, years: int = 3) -> list[dict]:
        raise RepoError('relation "airport_financials" does not exist')


async def test_one_missing_view_does_not_cost_the_others() -> None:
    tool = {t.name: t for t in build_tools(PartialRepo())}["investment_context"]
    payload = json.loads((await call(tool, iata="BGR")).content)
    assert payload["sources_available"] == ["financials"]
    assert "does not exist" in payload["carrier_concentration"]["unavailable"]
    assert payload["financials"][0]["net_rev_per_enplanement"] == -11.7


async def test_an_airport_with_no_t25_rows_is_reported_not_invented() -> None:
    """Absence is a normal case - most US airports never filed a Form 127."""
    tool = {t.name: t for t in build_tools(FixtureRepo())}["investment_context"]
    payload = json.loads((await call(tool, iata="PWM")).content)
    assert "PWM" == payload["iata"]

    msg = await call(tool, iata="ZZZ")
    assert msg.artifact["ok"] is False


async def test_no_sources_at_all_is_an_honest_failure() -> None:
    tool = {t.name: t for t in build_tools(BareRepo())}["investment_context"]
    msg = await call(tool, iata="BGR")
    payload = json.loads(msg.content)
    assert msg.artifact["ok"] is False
    assert "no carrier-concentration, financial or ROI-estimate rows" in payload["error"]
    # Even a total failure carries the vintage, so the model cannot substitute its own.
    assert payload["assumptions"]


async def test_the_fixture_roi_proxy_is_arithmetically_consistent(
    repo: FixtureRepo,
) -> None:
    """roi_proxy = est_unmet_pax * net_rev_per_enplanement, or the fixture lies."""
    for code in ("BGR", "SFO", "ANC"):
        unmet = {r["year"]: r["est_unmet_pax"] for r in await repo.unmet_demand(code)}
        net = {r["year"]: r["net_rev_per_enplanement"] for r in await repo.financials(code)}
        for row in await repo.roi_proxy(code):
            expected = round(unmet[row["year"]] * net[row["year"]])
            assert row["roi_proxy"] == expected, f"{code} {row['year']}"
