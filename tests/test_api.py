"""HTTP surface: /health, /chat streamed and unstreamed, and the failure paths."""

from __future__ import annotations

import json
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent.settings import Settings, get_settings

from .conftest import ScriptedChatModel, tool_call_message

SCRIPT = [
    tool_call_message("rank_airports", {"region": "new_england", "limit": 5}),
    AIMessage(content="**Answer** Boston Logan ranks first at 78.4 of 100."),
]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(
        "agent.graph.build_llm", lambda settings=None: ScriptedChatModel(responses=SCRIPT)
    )
    from agent.main import app

    with TestClient(app) as c:
        yield c


def sse_events(raw: str) -> list[dict]:
    return [
        json.loads(line[len("data: "):])
        for line in raw.splitlines()
        if line.startswith("data: ")
    ]


def test_health_reports_backend_model_and_auth_posture(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["data_backend"] == "fixture"
    assert body["data_ok"] is True
    assert body["checkpointer"] == "memory"
    assert body["data_vintage"]["last_year"] == 2024
    # No Langfuse keys and no database in the test environment.
    assert body["tracing"] is False
    assert body["query_log"] is False
    # Tokens are verified whenever one is sent; anonymous callers still get in.
    assert body["auth"]["clerk_verification"] is True
    assert body["auth"]["clerk_required"] is False
    assert body["stubs"] == {}


def test_root_lists_the_endpoints(client: TestClient) -> None:
    assert "chat" in client.get("/").json()["endpoints"]


def test_health_never_leaks_a_secret(client: TestClient) -> None:
    raw = client.get("/health").text
    assert "sk-or-test-not-a-real-key" not in raw
    assert client.get("/health").json()["llm_configured"] is True


def test_chat_json_returns_answer_assumptions_and_tools(client: TestClient) -> None:
    body = client.post("/chat", json={"message": "Best New England candidates?",
                                      "stream": False}).json()
    assert "Boston Logan" in body["answer"]
    assert body["tools_used"] == ["rank_airports"]
    assert any("CT, ME, MA, NH, RI and VT" in a for a in body["assumptions"])
    assert body["thread_id"]


def test_chat_stream_emits_the_full_event_sequence(client: TestClient) -> None:
    with client.stream(
        "POST", "/chat", json={"message": "Best New England candidates?"}
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = sse_events("".join(resp.iter_text()))

    kinds = [e["type"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "done"
    assert "tool_call" in kinds and "tool_result" in kinds and "assumptions" in kinds
    assert next(e for e in events if e["type"] == "tool_call")["name"] == "rank_airports"
    assert next(e for e in events if e["type"] == "tool_result")["ok"] is True
    assert "Boston Logan" in next(e for e in events if e["type"] == "done")["answer"]


def test_thread_id_is_echoed_and_reusable(client: TestClient) -> None:
    first = client.post("/chat", json={"message": "hi", "stream": False}).json()
    second = client.post(
        "/chat", json={"message": "and Providence?", "thread_id": first["thread_id"],
                       "stream": False}
    ).json()
    assert second["thread_id"] == first["thread_id"]


def test_empty_message_is_rejected(client: TestClient) -> None:
    assert client.post("/chat", json={"message": ""}).status_code == 422


def test_chat_is_unavailable_without_an_llm_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(client.app.state.rt, "settings", Settings())
    resp = client.post("/chat", json={"message": "hi", "stream": False})
    assert resp.status_code == 503
    assert "OPENROUTER_API_KEY" in resp.json()["error"]


def test_auth_dependency_is_open_until_clerk_is_enabled(client: TestClient) -> None:
    assert client.post("/chat", json={"message": "hi", "stream": False}).status_code == 200


# --- The empty-answer guard ----------------------------------------------


@pytest.fixture
def silent_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A model that completes the turn saying nothing at all."""
    monkeypatch.setattr(
        "agent.graph.build_llm",
        lambda settings=None: ScriptedChatModel(responses=[AIMessage(content="   ")]),
    )
    from agent.main import app

    with TestClient(app) as c:
        yield c


def test_a_blank_answer_is_replaced_with_honest_text(silent_client: TestClient) -> None:
    """A blank bubble tells the user nothing and hides the defect from the log."""
    from agent.main import EMPTY_ANSWER_FALLBACK

    body = silent_client.post(
        "/chat", json={"message": "anything", "stream": False}
    ).json()
    assert body["answer"] == EMPTY_ANSWER_FALLBACK


def test_the_stream_never_ends_on_an_empty_done(silent_client: TestClient) -> None:
    from agent.main import EMPTY_ANSWER_FALLBACK

    with silent_client.stream("POST", "/chat", json={"message": "anything"}) as resp:
        events = sse_events("".join(resp.iter_text()))
    done = next(e for e in events if e["type"] == "done")
    assert done["answer"] == EMPTY_ANSWER_FALLBACK


def test_a_real_answer_is_left_alone(client: TestClient) -> None:
    from agent.main import EMPTY_ANSWER_FALLBACK

    body = client.post(
        "/chat", json={"message": "Best New England candidates?", "stream": False}
    ).json()
    assert body["answer"] != EMPTY_ANSWER_FALLBACK
    assert "Boston Logan" in body["answer"]


# --- /freshness (ADR-005) --------------------------------------------------


def test_freshness_is_unknown_and_public_with_no_database(client: TestClient) -> None:
    """The client fixture runs on FixtureRepo - no data_refresh_runs table
    exists, and no auth header is sent, matching the other anonymous tests."""
    resp = client.get("/freshness")
    assert resp.status_code == 200
    assert resp.json() == {
        "last_successful_refresh": None,
        "last_run_status": "unknown",
        "cadence": None,
        "next_scheduled": None,
        "latest_period": None,
        "sources": None,
    }


def test_freshness_reports_a_known_good_refresh(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timezone

    finished = datetime(2026, 8, 23, 21, 14, 2, tzinfo=timezone.utc)
    started = datetime(2026, 8, 23, 21, 10, 0, tzinfo=timezone.utc)

    async def fake_refresh_status() -> dict:
        return {
            "last_successful_at": finished,
            "latest_period": "2026-02",
            "sources": ["BTS T-100 Segment", "OurAirports"],
            "last_run_status": "no_change",
            "last_run_started_at": started,
        }

    monkeypatch.setattr(client.app.state.rt.repo, "refresh_status", fake_refresh_status)
    body = client.get("/freshness").json()

    assert body["last_successful_refresh"] == "2026-08-23T21:14:02Z"
    assert body["last_run_status"] == "no_change"
    assert body["cadence"] == "weekly"
    assert body["next_scheduled"] == "2026-08-30T21:10:00Z"
    assert body["latest_period"] == "2026-02"
    assert body["sources"] == ["BTS T-100 Segment", "OurAirports"]


def test_freshness_never_advances_on_a_failed_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of ADR-005: a failed attempt is reported honestly, but
    it must never make an older-but-good refresh look more current than it is."""
    from datetime import datetime, timezone

    old_success = datetime(2026, 8, 9, 3, 5, 0, tzinfo=timezone.utc)
    failed_attempt = datetime(2026, 8, 23, 3, 0, 0, tzinfo=timezone.utc)

    async def fake_refresh_status() -> dict:
        return {
            "last_successful_at": old_success,
            "latest_period": "2026-01",
            "sources": ["BTS T-100 Segment"],
            "last_run_status": "failed",
            "last_run_started_at": failed_attempt,
        }

    monkeypatch.setattr(client.app.state.rt.repo, "refresh_status", fake_refresh_status)
    body = client.get("/freshness").json()

    assert body["last_successful_refresh"] == "2026-08-09T03:05:00Z"
    assert body["last_run_status"] == "failed"
    # the schedule keeps firing even though the latest attempt failed
    assert body["next_scheduled"] == "2026-08-30T03:00:00Z"


def test_freshness_never_fails_when_the_repository_raises(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken() -> dict:
        raise RuntimeError("pool exhausted")

    monkeypatch.setattr(client.app.state.rt.repo, "refresh_status", broken)
    resp = client.get("/freshness")
    assert resp.status_code == 200
    assert resp.json()["last_run_status"] == "unknown"


def test_health_gains_last_refresh_without_touching_data_vintage(client: TestClient) -> None:
    """Additive only - data_vintage is already public and must not move."""
    vintage_before = client.get("/health").json()["data_vintage"]
    body = client.get("/health").json()
    assert body["data_vintage"] == vintage_before
    assert body["last_refresh"]["last_run_status"] == "unknown"
