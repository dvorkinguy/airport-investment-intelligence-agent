"""Conversation checkpointer with the same stale-connection defence as the repo.

The pool's ``check`` already replaces dead connections on acquire, so this class
is the second line: a connection can still die between the check and the query,
and LangGraph reads a checkpoint on the very first hop of every request - which
is exactly the moment after an idle period when Neon has suspended the database.

Retries are deliberately narrow:

* ``aget_tuple`` / ``aput`` / ``aput_writes`` are idempotent enough to repeat -
  a checkpoint write is keyed by thread and checkpoint id.
* ``alist`` is an async generator, so it is only retried when nothing has been
  yielded yet. Restarting a partly-consumed stream would duplicate history.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agent.db import STALE_ERRORS, with_stale_retry
from agent.logging_config import get_logger

log = get_logger(__name__)


class ResilientAsyncPostgresSaver(AsyncPostgresSaver):
    """``AsyncPostgresSaver`` that survives a connection dying under it."""

    async def aget_tuple(self, config: Any) -> Any:
        parent = super().aget_tuple
        return await with_stale_retry(lambda: parent(config), what="checkpoint.get")

    async def aput(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        parent = super().aput
        return await with_stale_retry(
            lambda: parent(config, checkpoint, metadata, new_versions),
            what="checkpoint.put",
        )

    async def aput_writes(self, config: Any, writes: Any, task_id: str, *args: Any) -> Any:
        parent = super().aput_writes
        return await with_stale_retry(
            lambda: parent(config, writes, task_id, *args), what="checkpoint.put_writes"
        )

    async def alist(self, config: Any, **kwargs: Any) -> AsyncIterator[Any]:
        parent = super().alist
        yielded = False
        try:
            async for item in parent(config, **kwargs):
                yielded = True
                yield item
        except STALE_ERRORS as exc:
            if yielded:
                # Restarting here would replay checkpoints the caller already has.
                raise
            log.warning(
                "stale connection - retrying once",
                extra={"operation": "checkpoint.list", "error": str(exc).strip()[:200]},
            )
            async for item in parent(config, **kwargs):
                yield item
