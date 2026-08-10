"""Usage log - one row per answered question (ADR-003).

Doubles as per-user history and as the audit trail for "what did it say, from
which tools, how long did it take, and which Langfuse trace shows why".

The table is created on startup with CREATE TABLE IF NOT EXISTS rather than in
``db/`` migrations: that directory is owned by the data workstream, and this
table belongs to the service, not to the dataset.

Writes are best-effort by design. A failure to log must never fail an answer, so
every path here swallows its exception into a warning.
"""

from __future__ import annotations

from typing import Any

from agent.logging_config import get_logger

log = get_logger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS queries (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    thread_id     TEXT        NOT NULL,
    request_id    TEXT,
    user_id       TEXT        NOT NULL DEFAULT 'anonymous',
    question      TEXT        NOT NULL,
    answer        TEXT,
    tools_used    TEXT[]      NOT NULL DEFAULT '{}',
    latency_ms    INTEGER,
    model         TEXT,
    data_backend  TEXT,
    trace_id      TEXT,
    error         TEXT
)
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS queries_created_at_idx ON queries (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS queries_thread_id_idx  ON queries (thread_id)",
)

INSERT = """
INSERT INTO queries (thread_id, request_id, user_id, question, answer,
                     tools_used, latency_ms, model, data_backend, trace_id, error)
VALUES (%(thread_id)s, %(request_id)s, %(user_id)s, %(question)s, %(answer)s,
        %(tools_used)s, %(latency_ms)s, %(model)s, %(data_backend)s,
        %(trace_id)s, %(error)s)
"""


class QueryLog:
    """Writes to the ``queries`` table over the service's write pool."""

    def __init__(self, pool: Any | None) -> None:
        self._pool = pool

    @property
    def enabled(self) -> bool:
        return self._pool is not None

    async def ensure_table(self) -> bool:
        if not self.enabled:
            log.warning("query log disabled - no write pool")
            return False
        try:
            async with self._pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(DDL)
                    for statement in INDEXES:
                        await cur.execute(statement)
            log.info("queries table ready")
            return True
        except Exception:
            log.exception("could not create the queries table - logging disabled")
            self._pool = None
            return False

    async def record(
        self,
        *,
        thread_id: str,
        request_id: str | None,
        user_id: str,
        question: str,
        answer: str | None,
        tools_used: list[str],
        latency_ms: int,
        model: str | None,
        data_backend: str | None,
        trace_id: str | None = None,
        error: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        try:
            async with self._pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        INSERT,
                        {
                            "thread_id": thread_id,
                            "request_id": request_id,
                            "user_id": user_id,
                            "question": question,
                            "answer": answer,
                            "tools_used": list(tools_used),
                            "latency_ms": latency_ms,
                            "model": model,
                            "data_backend": data_backend,
                            "trace_id": trace_id,
                            "error": error,
                        },
                    )
        except Exception:
            # Never fail an answer because the audit row did not land.
            log.warning("query log write failed", exc_info=True)
