"""The repository contract - the shape every backend must honour."""

from __future__ import annotations

import pytest

from agent.repository import FixtureRepo, RepoError, UnknownAirportError
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


async def test_load_factor_matches_passengers_over_seats(repo: FixtureRepo) -> None:
    """Fixture integrity: a wrong fixture would silently make evals meaningless."""
    for iata in ("SFO", "LAX", "SNA", "ANC", "BOS"):
        for row in await repo.airport_metrics(iata):
            assert row["load_factor"] == pytest.approx(
                row["passengers"] / row["seats"], abs=0.001
            )
