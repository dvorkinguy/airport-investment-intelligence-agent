"""Tracing and query-log behaviour, with no Langfuse and no database.

The property that matters here is that neither is load-bearing: the agent must
answer identically whether tracing and logging are on, off, or broken.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent.observability import Tracing, build_tracing
from agent.query_log import DDL, INSERT, QueryLog
from agent.settings import Settings


# --- Enablement ----------------------------------------------------------


def test_tracing_is_on_when_keys_are_present() -> None:
    """The .env is owned by another lane, so keys alone must switch it on."""
    s = Settings(langfuse_public_key="pk-lf-x", langfuse_secret_key="sk-lf-x")
    assert s.tracing_enabled is True


def test_tracing_is_off_without_keys() -> None:
    assert Settings().tracing_enabled is False


def test_explicit_flag_wins_in_both_directions() -> None:
    on = Settings(langfuse_enabled=True)
    off = Settings(
        langfuse_enabled=False,
        langfuse_public_key="pk-lf-x",
        langfuse_secret_key="sk-lf-x",
    )
    assert on.tracing_enabled is True
    assert off.tracing_enabled is False


def test_base_url_overrides_host() -> None:
    assert Settings(langfuse_host="https://a").langfuse_url == "https://a"
    assert (
        Settings(langfuse_host="https://a", langfuse_base_url="https://b").langfuse_url
        == "https://b"
    )


def test_enabled_without_keys_degrades_to_off_rather_than_crashing() -> None:
    assert build_tracing(Settings(langfuse_enabled=True)).enabled is False


def test_bad_credentials_do_not_take_the_service_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected key must disable tracing, not break booting."""

    class Boom:
        def __init__(self, **kwargs: Any) -> None:
            raise RuntimeError("langfuse unreachable")

    import langfuse

    monkeypatch.setattr(langfuse, "Langfuse", Boom)
    s = Settings(langfuse_public_key="pk-lf-x", langfuse_secret_key="sk-lf-x")
    assert build_tracing(s).enabled is False


# --- No-op path ----------------------------------------------------------


def test_disabled_tracing_yields_a_usable_span_and_no_callbacks() -> None:
    tracing = Tracing(None)
    assert tracing.enabled is False
    assert tracing.callbacks() == []
    assert tracing.trace_id() is None
    with tracing.request(thread_id="t", user_id="anonymous", question="q") as span:
        span.update(output={"answer": "a"})  # must not raise
    tracing.flush()


# --- Query log -----------------------------------------------------------


async def test_query_log_without_a_pool_is_inert() -> None:
    log = QueryLog(None)
    assert log.enabled is False
    assert await log.ensure_table() is False
    await log.record(
        thread_id="t", request_id="r", user_id="anonymous", question="q",
        answer="a", tools_used=["rank_airports"], latency_ms=1,
        model="m", data_backend="fixture",
    )  # must not raise


async def test_a_write_failure_never_reaches_the_caller() -> None:
    class ExplodingPool:
        def connection(self) -> Any:
            raise RuntimeError("neon is down")

    log = QueryLog(ExplodingPool())
    assert await log.ensure_table() is False
    assert log.enabled is False
    await log.record(
        thread_id="t", request_id="r", user_id="anonymous", question="q",
        answer="a", tools_used=[], latency_ms=1, model="m", data_backend="postgres",
    )


def test_schema_is_create_if_not_exists_and_owns_no_dataset_tables() -> None:
    """db/ belongs to the data workstream; this table is the service's own."""
    assert "CREATE TABLE IF NOT EXISTS queries" in DDL
    for column in ("thread_id", "user_id", "question", "answer", "tools_used",
                   "latency_ms", "trace_id"):
        assert column in DDL
    assert INSERT.strip().upper().startswith("INSERT INTO QUERIES")
    assert "%(thread_id)s" in INSERT  # bound parameters, never interpolation
