"""Connection handling that survives Neon autosuspend.

Neon's free tier suspends a database after a few minutes idle and terminates its
server-side connections. A pooled connection then looks alive to the client and
fails on first use with

    terminating connection due to administrator command   (SQLSTATE 57P01)

which surfaced as the first question after an idle period erroring out, while
the second worked. Three defences, in order of who catches it first:

1. ``check`` on acquire - the pool validates a connection before handing it out
   and silently replaces a dead one. This is the fix; the rest is insurance.
2. ``min_size=0`` with a short ``max_idle`` - idle connections are closed by us
   rather than left for Neon to kill. ``max_idle`` only prunes connections above
   ``min_size``, so a non-zero minimum would pin exactly the stale connection
   this is meant to avoid.
3. One automatic retry - a connection can still die in the window between the
   check and the query. The user never sees the first failure.

The pool stays small on purpose: the free tier has a low connection cap, and
this service shares it with the checkpointer.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent.logging_config import get_logger

log = get_logger(__name__)

T = TypeVar("T")

#: Failures that mean "this connection is dead", not "this query is wrong".
#: Retrying a ProgrammingError would just fail twice as slowly.
STALE_ERRORS = (psycopg.OperationalError, psycopg.InterfaceError)


def build_pool(
    dsn: str,
    *,
    autocommit: bool,
    min_size: int = 0,
    max_size: int = 3,
    max_idle_seconds: float = 30.0,
    max_lifetime_seconds: float = 300.0,
    acquire_timeout_seconds: float = 20.0,
    connect_timeout_seconds: int = 10,
) -> AsyncConnectionPool:
    """A pool that validates connections on the way out."""
    return AsyncConnectionPool(
        conninfo=dsn,
        min_size=min_size,
        max_size=max_size,
        open=False,
        check=AsyncConnectionPool.check_connection,
        max_idle=max_idle_seconds,
        max_lifetime=max_lifetime_seconds,
        timeout=acquire_timeout_seconds,
        kwargs={
            "row_factory": dict_row,
            "autocommit": autocommit,
            # Neon's pooled endpoint runs pgbouncer; server-side prepared
            # statements must stay off.
            "prepare_threshold": None,
            "connect_timeout": connect_timeout_seconds,
        },
    )


async def with_stale_retry(
    operation: Callable[[], Awaitable[T]], *, what: str
) -> T:
    """Run ``operation``, retrying once if the connection turned out to be dead.

    Exactly one retry. A second failure is a real outage and must reach the
    caller rather than being hidden behind a retry loop.
    """
    try:
        return await operation()
    except STALE_ERRORS as exc:
        log.warning(
            "stale connection - retrying once",
            extra={"operation": what, "error": str(exc).strip()[:200]},
        )
        return await operation()


def pool_stats(pool: Any | None) -> dict[str, Any]:
    """Pool counters for /health. Never raises - it is a diagnostic, not a check."""
    if pool is None:
        return {}
    try:
        stats = pool.get_stats()
        return {
            "size": stats.get("pool_size"),
            "available": stats.get("pool_available"),
            "requests_waiting": stats.get("requests_waiting"),
        }
    except Exception:
        return {}
