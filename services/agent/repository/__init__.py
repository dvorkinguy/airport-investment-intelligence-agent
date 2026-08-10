"""Repository layer - the only place that knows where the numbers come from.

``AirportRepo`` is the contract. ``PostgresRepo`` reads the Neon scoring views;
``FixtureRepo`` reads JSON snapshots so tests and evals run with no database.
Tools depend on the protocol, never on a concrete backend.
"""

from agent.repository.base import AirportRepo, RepoError, UnknownAirportError
from agent.repository.fixture import FixtureRepo
from agent.repository.postgres import PostgresRepo

__all__ = [
    "AirportRepo",
    "FixtureRepo",
    "PostgresRepo",
    "RepoError",
    "UnknownAirportError",
]
