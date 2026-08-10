"""Stale-connection handling.

Neon's free tier suspends when idle and terminates its server-side connections.
The pool then hands out a corpse and the first question after an idle period
fails with SQLSTATE 57P01. These tests pin the three properties that fix it,
without needing a database.
"""

from __future__ import annotations

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from agent.db import STALE_ERRORS, build_pool, pool_stats, with_stale_retry
from agent.settings import Settings

DSN = "postgresql://user:pw@localhost/db"


def test_admin_shutdown_is_treated_as_a_dead_connection() -> None:
    """57P01 is the exact error Neon raises on a terminated connection."""
    assert psycopg.errors.AdminShutdown.sqlstate == "57P01"
    assert issubclass(psycopg.errors.AdminShutdown, STALE_ERRORS)


def test_query_mistakes_are_not_retried() -> None:
    """Retrying a bad statement just fails twice as slowly."""
    assert not issubclass(psycopg.errors.UndefinedTable, STALE_ERRORS)
    assert not issubclass(psycopg.errors.SyntaxError, STALE_ERRORS)


def test_pool_validates_connections_on_acquire() -> None:
    pool = build_pool(DSN, autocommit=False)
    assert pool._check is AsyncConnectionPool.check_connection


def test_pool_keeps_no_idle_connection_for_neon_to_kill() -> None:
    """max_idle only prunes connections above min_size, so the minimum must be 0."""
    pool = build_pool(DSN, autocommit=False)
    assert pool.min_size == 0
    assert pool.max_idle <= 60
    assert pool.max_lifetime <= 600


def test_pools_stay_small_for_the_free_tier_connection_cap() -> None:
    s = Settings()
    assert s.db_pool_max_size <= 3
    assert s.db_write_pool_max_size <= 3
    assert s.db_pool_min_size == 0


async def test_retry_runs_once_more_after_a_dead_connection() -> None:
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise psycopg.errors.AdminShutdown(
                "terminating connection due to administrator command"
            )
        return "ok"

    assert await with_stale_retry(flaky, what="test") == "ok"
    assert calls["n"] == 2


async def test_a_second_failure_is_a_real_outage_and_surfaces() -> None:
    async def always_dead() -> str:
        raise psycopg.OperationalError("connection is closed")

    with pytest.raises(psycopg.OperationalError):
        await with_stale_retry(always_dead, what="test")


async def test_a_healthy_call_is_not_repeated() -> None:
    calls = {"n": 0}

    async def fine() -> str:
        calls["n"] += 1
        return "ok"

    assert await with_stale_retry(fine, what="test") == "ok"
    assert calls["n"] == 1


async def test_query_errors_pass_straight_through_without_a_retry() -> None:
    calls = {"n": 0}

    async def bad_sql() -> str:
        calls["n"] += 1
        raise psycopg.errors.UndefinedTable('relation "v_nope" does not exist')

    with pytest.raises(psycopg.errors.UndefinedTable):
        await with_stale_retry(bad_sql, what="test")
    assert calls["n"] == 1


def test_pool_stats_never_raise() -> None:
    class Broken:
        def get_stats(self) -> dict:
            raise RuntimeError("no")

    assert pool_stats(None) == {}
    assert pool_stats(Broken()) == {}


async def test_repository_retries_a_dead_connection_transparently() -> None:
    """The whole point: the user gets an answer, not a stale-pool error."""
    from agent.repository.postgres import PostgresRepo

    repo = PostgresRepo.__new__(PostgresRepo)
    repo._statement_timeout_ms = 1000
    calls = {"n": 0}

    async def run(sql: str, params: dict) -> list[dict]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise psycopg.errors.AdminShutdown(
                "terminating connection due to administrator command"
            )
        return [{"iata": "SFO"}]

    repo._run_select = run  # type: ignore[method-assign]
    assert await repo._select("SELECT 1", {}) == [{"iata": "SFO"}]
    assert calls["n"] == 2


async def test_checkpointer_retries_reads_and_writes() -> None:
    from agent.checkpointer import ResilientAsyncPostgresSaver

    for method in ("aget_tuple", "aput", "aput_writes", "alist"):
        assert method in vars(ResilientAsyncPostgresSaver), f"{method} is not wrapped"
