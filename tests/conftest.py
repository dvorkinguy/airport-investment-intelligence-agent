"""Shared test fixtures.

Everything here runs with no database, no network and no LLM: ``FixtureRepo``
backs the data and ``ScriptedChatModel`` replays a fixed tool-calling script, so
graph routing is asserted deterministically.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agent.repository import FixtureRepo
from agent.settings import Settings, get_settings


class ScriptedChatModel(BaseChatModel):
    """Replays pre-built AIMessages in order; the last one repeats if exhausted.

    Tool binding is modelled faithfully: an instance that was never given tools
    cannot emit a tool call, so the graph's tool-call cap (which deliberately
    drops the tools) is exercised exactly as a real model would experience it.
    """

    responses: list[AIMessage] = []
    seen: list[list[BaseMessage]] = []
    tools_bound: bool = False
    unbound_answer: str = "Stopping here with what I have."

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.seen.append(list(messages))
        message = self.responses[min(len(self.seen) - 1, len(self.responses) - 1)]
        if message.tool_calls and not self.tools_bound:
            message = AIMessage(content=self.unbound_answer)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        # Shares ``responses``/``seen`` with the original, so the script advances
        # across both the bound and the unbound instance.
        return self.model_copy(update={"tools_bound": True})


def tool_call_message(name: str, args: dict[str, Any], call_id: str = "c1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


@pytest.fixture
def repo() -> FixtureRepo:
    return FixtureRepo()


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Deterministic settings: fixture backend, fake key, no external state."""
    for key in ("DATABASE_URL", "LANGFUSE_ENABLED", "CLERK_AUTH_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("REPO_BACKEND", "fixture")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    monkeypatch.setenv("LOG_JSON", "false")
    # Settings reads the repo .env; point it at nothing so a developer's real
    # values cannot leak into a test run.
    monkeypatch.setattr(
        "agent.settings.Settings.model_config",
        {**Settings.model_config, "env_file": "__tests_use_no_env_file__"},
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
