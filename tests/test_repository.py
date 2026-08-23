"""The repository contract - the shape every backend must honour."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import psycopg
import pytest

from agent.repository import FixtureRepo, RepoError, UnknownAirportError
from agent.repository.postgres import (
    Q_LAST_REFRESH_RUN,
    Q_LAST_SUCCESSFUL_REFRESH,
    Q_RANK,
    PostgresRepo,
    coerce_numeric,
    coerce_sources,
)
from agent.repository.base import (
    AIRPORT_COLUMNS,
    CONGESTION_COLUMNS,
    METRIC_COLUMNS,
    SCORE_COLUMNS,
    UNMET_COLUMNS,
    AirportRepo,
)


def test_fixture_repo_satisfies_the_protocol(repo: FixtureRepo) -> None:
    assert isinstance(repo, AirportRepo)


async def test_resolve_by_code_city_and_name(repo: FixtureRepo) -> None:
    assert (await repo.resolve_airport("SFO"))[0]["iata"] == "SFO"
    assert (await repo.resolve_airport("Santa Ana"))[0]["iata"] == "SNA"
    assert (await repo.resolve_airport("Anchorage"))[0]["iata"] == "ANC"
    assert set(AIRPORT_COLUMNS) <= set((await repo.resolve_airport("BOS"))[0])


async def test_resolve_rejects_empty_query(repo: FixtureRepo) -> None:
    with pytest.raises(RepoError):
        await repo.resolve_airport("  ")


async def test_new_england_region_is_the_six_states(repo: FixtureRepo) -> None:
    rows = await repo.rank_airports(region="new_england", limit=25)
    assert {r["state"] for r in rows} <= {"CT", "ME", "MA", "NH", "RI", "VT"}
    assert "LAX" not in {r["iata"] for r in rows}


async def test_ranking_is_descending_and_exposes_components(repo: FixtureRepo) -> None:
    rows = await repo.rank_airports(region="new_england", limit=5)
    scores = [r["score_0_100"] for r in rows]
    assert scores == sorted(scores, reverse=True)
    assert set(SCORE_COLUMNS) <= set(rows[0])


async def test_rank_accepts_explicit_states(repo: FixtureRepo) -> None:
    rows = await repo.rank_airports(states=["ca"], limit=10)
    assert {r["iata"] for r in rows} == {"LAX", "SFO", "SNA"}


async def test_rank_needs_a_filter_and_a_known_metric(repo: FixtureRepo) -> None:
    with pytest.raises(RepoError):
        await repo.rank_airports()
    with pytest.raises(RepoError):
        await repo.rank_airports(region="new_england", metric="vibes")


async def test_metrics_are_newest_first_and_complete(repo: FixtureRepo) -> None:
    rows = await repo.airport_metrics("ANC")
    assert [r["year"] for r in rows] == sorted((r["year"] for r in rows), reverse=True)
    assert set(METRIC_COLUMNS) <= set(rows[0])


async def test_congestion_and_unmet_columns(repo: FixtureRepo) -> None:
    assert set(CONGESTION_COLUMNS) <= set((await repo.congestion("LAX"))[0])
    assert set(UNMET_COLUMNS) <= set((await repo.unmet_demand("SFO"))[0])


async def test_unknown_airport_raises_rather_than_returning_empty(repo: FixtureRepo) -> None:
    for call in (repo.airport_metrics, repo.congestion, repo.unmet_demand):
        with pytest.raises(UnknownAirportError):
            await call("ZZZ")


async def test_vintage_and_ping(repo: FixtureRepo) -> None:
    vintage = await repo.data_vintage()
    assert vintage["backend"] == "fixture"
    assert vintage["first_year"] <= vintage["last_year"]
    assert await repo.ping() is True


def test_postgres_numerics_land_as_plain_numbers() -> None:
    """A Decimal reaching the model as a quoted string invites reformatting."""
    assert coerce_numeric(Decimal("3180000.00")) == 3_180_000
    assert isinstance(coerce_numeric(Decimal("3180000.00")), int)
    assert coerce_numeric(Decimal("0.8355")) == pytest.approx(0.8355)
    assert coerce_numeric("BOS") == "BOS"
    assert coerce_numeric(None) is None


def test_ranking_sql_filters_by_region_and_states_without_interpolation() -> None:
    """Read-only by construction: filters are bound parameters, never f-strings."""
    assert "%(region)s" in Q_RANK and "%(states)s" in Q_RANK
    assert Q_RANK.strip().upper().startswith("SELECT")
    assert "FROM regions" in Q_RANK


async def test_load_factor_matches_passengers_over_seats(repo: FixtureRepo) -> None:
    """Fixture integrity: a wrong fixture would silently make evals meaningless."""
    for iata in ("SFO", "LAX", "SNA", "ANC", "BOS"):
        for row in await repo.airport_metrics(iata):
            assert row["load_factor"] == pytest.approx(
                row["passengers"] / row["seats"], abs=0.001
            )


# --- ADR-005: scheduled ingestion (data_refresh_runs) ---------------------


async def test_fixture_repo_has_no_refresh_ledger(repo: FixtureRepo) -> None:
    """Fixtures have no scheduled-ingestion table; this is the same "unknown"
    state PostgresRepo reports when data_refresh_runs does not exist yet."""
    assert await repo.refresh_status() == {}


def test_coerce_sources_accepts_a_list_or_a_dict_and_rejects_the_rest() -> None:
    assert coerce_sources(["BTS T-100 Segment", "OurAirports"]) == [
        "BTS T-100 Segment",
        "OurAirports",
    ]
    assert coerce_sources({"BTS T-100 Segment": {"rows": 1}}) == ["BTS T-100 Segment"]
    assert coerce_sources(None) is None
    assert coerce_sources("BTS T-100 Segment") is None


def _postgres_repo() -> PostgresRepo:
    """A PostgresRepo with no real connection - only ``_run_select`` is ever
    called, matching the pattern in test_db_resilience.py."""
    repo = PostgresRepo.__new__(PostgresRepo)
    repo._statement_timeout_ms = 1000
    return repo


async def test_refresh_status_pairs_the_last_success_with_the_true_last_run() -> None:
    """The exact ADR-005 invariant: a failed run must never advance
    last_successful_at, but must still be reported as the current status."""
    good_at = datetime(2026, 8, 9, 3, 5, 0, tzinfo=timezone.utc)
    failed_at = datetime(2026, 8, 23, 3, 0, 0, tzinfo=timezone.utc)

    async def run(sql: str, params: dict) -> list[dict]:
        if sql is Q_LAST_SUCCESSFUL_REFRESH:
            return [
                {
                    "finished_at": good_at,
                    "latest_period": "2026-01",
                    "sources": ["BTS T-100 Segment"],
                }
            ]
        if sql is Q_LAST_REFRESH_RUN:
            return [{"started_at": failed_at, "status": "failed"}]
        raise AssertionError(f"unexpected query: {sql}")

    repo = _postgres_repo()
    repo._run_select = run  # type: ignore[method-assign]
    status = await repo.refresh_status()

    assert status["last_successful_at"] == good_at
    assert status["latest_period"] == "2026-01"
    assert status["sources"] == ["BTS T-100 Segment"]
    assert status["last_run_status"] == "failed"
    assert status["last_run_started_at"] == failed_at


async def test_refresh_status_degrades_to_unknown_when_the_table_is_absent() -> None:
    async def run(sql: str, params: dict) -> list[dict]:
        raise psycopg.errors.UndefinedTable('relation "data_refresh_runs" does not exist')

    repo = _postgres_repo()
    repo._run_select = run  # type: ignore[method-assign]
    assert await repo.refresh_status() == {}


async def test_refresh_status_returns_empty_when_no_runs_exist() -> None:
    async def run(sql: str, params: dict) -> list[dict]:
        return []

    repo = _postgres_repo()
    repo._run_select = run  # type: ignore[method-assign]
    status = await repo.refresh_status()
    assert status["last_successful_at"] is None
    assert status["last_run_status"] is None
    assert status["last_run_started_at"] is None


def test_stale_running_rows_are_excluded_at_the_sql_level() -> None:
    """A crashed job leaves a permanent 'running' row; the query itself, not
    Python, must be the thing that refuses to treat it as current."""
    assert "status <> 'running'" in Q_LAST_REFRESH_RUN
    assert "%(stale_after)s" in Q_LAST_REFRESH_RUN


def test_refresh_queries_are_read_only_and_parameterised() -> None:
    for sql in (Q_LAST_SUCCESSFUL_REFRESH, Q_LAST_REFRESH_RUN):
        assert sql.strip().upper().startswith("SELECT")
        assert "data_refresh_runs" in sql
