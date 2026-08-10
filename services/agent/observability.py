"""LLM tracing slot (Tier 2).

Every LLM and tool call already flows through a LangChain callback list, so
tracing is a wiring change, not a refactor. The handler itself is deliberately
NOT implemented inside the Tier 1 window - it is declared here so the gap is
explicit and typed rather than silently missing.

To finish it: add ``langfuse`` to the dependencies, build the callback handler in
``build_langfuse_handler`` from the keys already present in Settings, and set
``LANGFUSE_ENABLED=true``. Nothing else in the codebase changes.
"""

from __future__ import annotations

from typing import Any

from agent.logging_config import get_logger
from agent.settings import Settings

log = get_logger(__name__)


def build_langfuse_handler(settings: Settings) -> Any:
    """STUB (Tier 2): construct the Langfuse callback handler.

    Raises:
        NotImplementedError: always, until the Tier 2 tracing task lands.
    """
    raise NotImplementedError(
        "Langfuse tracing is designed but not implemented (Tier 2). "
        "Keys are read from LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST; "
        "install the langfuse package and build CallbackHandler here."
    )


def get_callbacks(settings: Settings) -> list[Any]:
    """Callback list for graph invocations. Empty unless tracing is switched on."""
    if not settings.langfuse_enabled:
        return []
    return [build_langfuse_handler(settings)]


def warn_if_unwired(settings: Settings) -> None:
    """Say out loud, once at boot, that credentials are present but unused."""
    if settings.langfuse_public_key and not settings.langfuse_enabled:
        log.warning(
            "Langfuse credentials present but tracing is a Tier 2 stub - no traces emitted",
            extra={"stub": "observability.build_langfuse_handler"},
        )
