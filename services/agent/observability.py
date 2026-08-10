"""Langfuse tracing.

One trace per chat request:

    chat-request                     (agent)   input = the user's question
      +- ChatOpenAI                  (generation)  model, tokens, cost
      +- compare_airports            (tool)        args and returned rows
      +- ChatOpenAI                  (generation)  the written answer

The LangChain ``CallbackHandler`` produces the generations and tool spans; this
module owns the root span and the trace-level attributes:

* ``session_id = thread_id`` so a multi-turn conversation groups in Sessions
* ``user_id``   anonymous until Clerk lands, then the Clerk subject
* ``environment`` dev locally, prod on Cloud Run
* tags for the model and the data backend, so a bad answer can be traced back to
  whether it was served from Neon or from fixtures

Callers never branch on whether tracing is on: with no keys, ``Tracing`` hands
back a no-op span and an empty callback list.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from agent import __version__
from agent.logging_config import get_logger
from agent.settings import Settings

log = get_logger(__name__)


class _NullSpan:
    """Stand-in span so request code has no ``if tracing_enabled`` branches."""

    id: str | None = None

    def update(self, **kwargs: Any) -> None:
        return None

    def update_trace(self, **kwargs: Any) -> None:
        return None


class Tracing:
    """Langfuse wiring, or a working no-op when it is switched off."""

    def __init__(self, client: Any | None, environment: str = "dev") -> None:
        self._client = client
        self.environment = environment

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def callbacks(self) -> list[Any]:
        """Callback list for graph invocations."""
        if not self.enabled:
            return []
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler()]

    @contextmanager
    def request(
        self,
        *,
        thread_id: str,
        user_id: str,
        question: str,
        tags: list[str] | None = None,
    ) -> Iterator[Any]:
        """Root span for one chat request, with trace attributes attached."""
        if not self.enabled:
            yield _NullSpan()
            return

        from langfuse import propagate_attributes

        with self._client.start_as_current_observation(
            name="chat-request", as_type="agent", input={"question": question}
        ) as span:
            with propagate_attributes(
                session_id=thread_id,
                user_id=user_id,
                tags=tags or [],
                environment=self.environment,
            ):
                yield span

    def trace_id(self) -> str | None:
        """Current trace id, stored alongside the query log row."""
        if not self.enabled:
            return None
        try:
            return self._client.get_current_trace_id()
        except Exception:
            return None

    def flush(self) -> None:
        if self.enabled:
            try:
                self._client.flush()
            except Exception:
                log.warning("langfuse flush failed", exc_info=True)


def build_tracing(settings: Settings) -> Tracing:
    """Construct the Langfuse client at boot, after settings have loaded .env.

    Importing Langfuse before the environment is read is the classic way to end
    up with a silently disabled client, so the keys are passed explicitly rather
    than left to environment discovery.
    """
    if not settings.tracing_enabled:
        log.info("langfuse tracing off")
        return Tracing(None)

    keys = settings.langfuse_keys
    if keys is None:
        log.warning("LANGFUSE_ENABLED is set but the keys are missing - tracing off")
        return Tracing(None)

    public_key, secret_key = keys
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=settings.langfuse_url,
            environment=settings.langfuse_environment,
            release=__version__,
            debug=settings.langfuse_debug,
        )
        if not client.auth_check():
            log.warning(
                "langfuse credentials rejected - tracing off",
                extra={"host": settings.langfuse_url},
            )
            return Tracing(None)
    except Exception:
        log.exception("langfuse init failed - continuing without tracing")
        return Tracing(None)

    log.info(
        "langfuse tracing on",
        extra={"host": settings.langfuse_url, "environment": settings.langfuse_environment},
    )
    return Tracing(client, environment=settings.langfuse_environment)
