"""Tool behaviour: the numbers, the assumptions, and the refusal path."""

from __future__ import annotations

import json
from typing import Any

import pytest

from agent.repository import FixtureRepo
from agent.tools import TOOL_NAMES, build_tools


@pytest.fixture
def tools(repo: FixtureRepo) -> dict[str, Any]:
    return {t.name: t for t in build_tools(repo)}


async def call(tool: Any, **args: Any):
    return await tool.ainvoke(
        {"name": tool.name, "args": args, "id": "t1", "type": "tool_call"}
    )


def test_exactly_five_tools_with_the_contract_names(tools: dict[str, Any]) -> None:
    assert set(tools) == set(TOOL_NAMES)
    assert len(TOOL_NAMES) == 5


def test_every_tool_documents_itself_for_the_model(tools: dict[str, Any]) -> None:
    for tool in tools.values():
        assert tool.description and len(tool.description) > 60


async def test_rank_airports_returns_scores_and_assumptions(tools: dict[str, Any]) -> None:
    msg = await call(tools["rank_airports"], region="new_england", limit=5)
    payload = json.loads(msg.content)
    assert payload["ranked"][0]["iata"] == "BOS"
    assert msg.artifact["ok"] is True
    joined = " ".join(payload["assumptions"])
    assert "CT, ME, MA, NH, RI and VT" in joined
    assert "deterministic" in joined


async def test_airport_metrics_states_the_long_haul_threshold(tools: dict[str, Any]) -> None:
    msg = await call(tools["airport_metrics"], iata="ANC")
    payload = json.loads(msg.content)
    assert payload["iata"] == "ANC"
    assert payload["metrics"][0]["long_haul_pct"] == 0.463
    assert any("1500 miles" in a for a in payload["assumptions"])


async def test_place_names_resolve_to_codes(tools: dict[str, Any]) -> None:
    msg = await call(tools["airport_metrics"], iata="Anchorage")
    assert json.loads(msg.content)["iata"] == "ANC"


async def test_compare_returns_both_sides_with_congestion(tools: dict[str, Any]) -> None:
    msg = await call(tools["compare_airports"], a="LAX", b="Santa Ana")
    payload = json.loads(msg.content)
    assert payload["a"] == "LAX" and payload["b"] == "SNA"
    for code in ("LAX", "SNA"):
        side = payload["comparison"][code]
        assert side["metrics"] and side["congestion"]
        assert "delay_rate" in side["congestion"][0]


async def test_unmet_demand_is_labelled_an_estimate(tools: dict[str, Any]) -> None:
    msg = await call(tools["unmet_demand_estimate"], iata="SFO")
    payload = json.loads(msg.content)
    assert payload["label"] == "ESTIMATE"
    assert payload["estimates"][0]["est_unmet_pax"] == 3_180_000
    assert all(k in payload["estimates"][0] for k in
               ("driver_load_factor", "driver_growth_gap", "driver_delay_rate"))
    assert any("ESTIMATE, not an observed statistic" in a for a in payload["assumptions"])


async def test_every_success_payload_carries_the_data_vintage(tools: dict[str, Any]) -> None:
    for name, args in (
        ("resolve_airport", {"query": "BOS"}),
        ("rank_airports", {"region": "new_england"}),
        ("airport_metrics", {"iata": "SFO"}),
        ("compare_airports", {"a": "LAX", "b": "SNA"}),
        ("unmet_demand_estimate", {"iata": "SFO"}),
    ):
        payload = json.loads((await call(tools[name], **args)).content)
        assert any("2022-2024" in a for a in payload["assumptions"]), name


async def test_unknown_airport_returns_an_instruction_not_to_guess(
    tools: dict[str, Any]
) -> None:
    msg = await call(tools["airport_metrics"], iata="ZZZ")
    payload = json.loads(msg.content)
    assert "error" in payload
    assert "Do not substitute an estimate" in payload["instruction"]
    assert msg.artifact["ok"] is False


async def test_unsupported_metric_is_refused(tools: dict[str, Any]) -> None:
    msg = await call(tools["rank_airports"], region="new_england", metric="roi")
    assert "not available" in json.loads(msg.content)["error"]
