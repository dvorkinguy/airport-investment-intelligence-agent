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
