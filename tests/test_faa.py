"""FAA live-status client.

Two properties matter here and both are about blast radius:

  1. the parser reads the feed's real shape, including the quirk that the same
     section name appears in more than one <Delay_type> block;
  2. a feed that is down, slow or malformed degrades to "unavailable" and never
     raises into an answer that is otherwise built on SQL.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from agent import faa
from agent.repository import FixtureRepo
from agent.tools import build_tools

# Trimmed from a live capture, keeping one row per section and - critically -
# the duplicated "Airport Closures" section the real feed emits.
FEED = """<?xml version="1.0" encoding="UTF-8"?>
<AIRPORT_STATUS_INFORMATION>
  <Update_Time>Mon Aug 10 19:51:43 2026 GMT</Update_Time>
  <Delay_type><Name>Ground Stop Programs</Name><Ground_Stop_List>
    <Program><ARPT>BOS</ARPT><Reason>thunderstorms</Reason><End_Time>4:30 pm EDT</End_Time></Program>
  </Ground_Stop_List></Delay_type>
  <Delay_type><Name>Ground Delay Programs</Name><Ground_Delay_List>
    <Ground_Delay><ARPT>SFO</ARPT><Reason>other</Reason><Avg>46 minutes</Avg><Max>1 hour and 35 minutes</Max></Ground_Delay>
  </Ground_Delay_List></Delay_type>
  <Delay_type><Name>General Arrival/Departure Delay Info</Name><Arrival_Departure_Delay_List>
    <Delay><ARPT>BOS</ARPT><Reason>TM Initiatives:SWAP:WX</Reason>
      <Arrival_Departure Type="Departure"><Min>1 hour and 31 minutes</Min><Max>1 hour and 45 minutes</Max><Trend>Increasing</Trend></Arrival_Departure>
    </Delay>
  </Arrival_Departure_Delay_List></Delay_type>
  <Delay_type><Name>Airport Closures</Name><Airport_Closure_List>
    <Airport><ARPT>LMT</ARPT><Reason>!LMT 08/022 AD AP CLSD</Reason><Start>Aug 10 at 00:01 UTC.</Start><Reopen>Aug 14 at 13:00 UTC.</Reopen></Airport>
  </Airport_Closure_List></Delay_type>
  <Delay_type><Name>Airport Closures</Name><Airport_Closure_List>
    <Airport><ARPT>LAX</ARPT><Reason>!LAX 05/277 AD AP CLSD TO NON SKED GA</Reason><Start>May 27 at 18:26 UTC.</Start><Reopen>May 28 at 16:00 UTC.</Reopen></Airport>
  </Airport_Closure_List></Delay_type>
</AIRPORT_STATUS_INFORMATION>
"""


@pytest.fixture(autouse=True)
def clean_cache() -> Any:
    faa.reset_cache()
    yield
    faa.reset_cache()


def test_parse_reads_every_section() -> None:
    doc = faa.parse(FEED)
    assert doc["available"] is True
    assert doc["updated"] == "Mon Aug 10 19:51:43 2026 GMT"
    assert [r["iata"] for r in doc["ground_stops"]] == ["BOS"]
    assert doc["ground_delays"][0]["average_delay"] == "46 minutes"
    assert doc["delays"][0]["direction"] == "Departure"
    assert doc["delays"][0]["trend"] == "Increasing"


def test_a_repeated_section_name_does_not_drop_rows() -> None:
    """The live feed emits two separate 'Airport Closures' blocks; both count."""
    doc = faa.parse(FEED)
    assert {r["iata"] for r in doc["closures"]} == {"LMT", "LAX"}


async def test_airport_status_slices_one_airport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(faa, "_fetch", _serving(FEED))
    status = await faa.airport_status("BOS", url="x")
    assert status["available"] is True
    assert status["has_impacts"] is True
    assert status["impact_count"] == 2  # one ground stop, one departure delay
    assert status["ground_delays"] == []  # SFO's, not BOS's


async def test_a_quiet_airport_reports_normal_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(faa, "_fetch", _serving(FEED))
    status = await faa.airport_status("BGR", url="x")
    assert status["has_impacts"] is False
    assert "normal" in status["status"]


async def test_the_document_is_fetched_once_per_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def counting(url: str, timeout: float) -> dict[str, Any]:
        calls["n"] += 1
        return faa.parse(FEED)

    monkeypatch.setattr(faa, "_fetch", counting)
    for code in ("BOS", "SFO", "LAX"):
        await faa.airport_status(code, url="x", ttl=300)
    assert calls["n"] == 1


async def test_a_dead_feed_is_data_not_an_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(url: str, timeout: float) -> dict[str, Any]:
        raise AssertionError("_fetch should absorb its own failures")

    monkeypatch.setattr(faa, "_fetch", faa._fetch)
    # Unroutable host: exercises the real timeout/DNS path, not a mocked one.
    status = await faa.airport_status(
        "BOS", url="http://127.0.0.1:9/status", timeout=1.0
    )
    assert status["available"] is False
    assert "unavailable" in status["note"]


async def test_the_tool_never_lets_a_feed_failure_break_the_answer(
    repo: FixtureRepo,
) -> None:
    tool = {t.name: t for t in build_tools(repo)}["faa_live_status"]
    msg = await tool.ainvoke(
        {"name": "faa_live_status", "args": {"iata": "BOS"}, "id": "t1", "type": "tool_call"}
    )
    payload = json.loads(msg.content)
    # Whether the live feed answered or not, the tool returns a usable payload and
    # says which case it is.
    assert "live_status_available" in payload
    assert msg.artifact["ok"] is True


async def test_the_tool_always_carries_the_do_not_use_for_investment_warning(
    repo: FixtureRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(faa, "_fetch", _serving(FEED))
    tool = {t.name: t for t in build_tools(repo)}["faa_live_status"]
    msg = await tool.ainvoke(
        {"name": "faa_live_status", "args": {"iata": "BOS"}, "id": "t1", "type": "tool_call"}
    )
    joined = " ".join(json.loads(msg.content)["assumptions"])
    assert "NOT evidence about long-term investment merit" in joined


def _serving(xml: str):
    async def fetch(url: str, timeout: float) -> dict[str, Any]:
        return faa.parse(xml)

    return fetch
