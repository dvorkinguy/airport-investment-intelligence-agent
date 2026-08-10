"""The agent graph.

    START -> agent -> (tool_calls?) -> tools -> agent -> ... -> END

Two nodes, one conditional edge. The reasoning path is an explicit state machine
rather than a hidden loop, so it can be tested node by node, drawn, and later
extended to supervisor + specialists without a rewrite.

The tools node is hand-written instead of the prebuilt one for a specific reason:
it lifts each tool's ``assumptions`` artifact into typed graph state, so an
answer's assumption set is structured data rather than something to re-parse out
of prose.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph

from agent.logging_config import get_logger
from agent.prompts import SYSTEM_PROMPT
from agent.repository.base import AirportRepo
from agent.settings import Settings, get_settings
from agent.state import AgentState
from agent.tools import build_tools

log = get_logger(__name__)

FORCED_ANSWER_NUDGE = (
    "You have reached the tool-call limit for this turn. Answer now using only the "
    "tool results already in this conversation. If they are insufficient, say exactly "
    "what is missing rather than estimating."
)


def build_llm(settings: Settings | None = None) -> BaseChatModel:
    """Chat model behind OpenRouter. Swapping models is an ``AGENT_MODEL`` change."""
    from langchain_openai import ChatOpenAI  # imported lazily: tests inject a fake

    s = settings or get_settings()
    if not s.openrouter_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to .env (see .env.example) - "
            "the agent cannot reason without an LLM gateway."
        )
    return ChatOpenAI(
        model=s.agent_model,
        api_key=s.openrouter_key,
        base_url=s.openrouter_base_url,
        temperature=s.llm_temperature,
        timeout=s.llm_timeout_seconds,
        max_retries=s.llm_max_retries,
        default_headers={
            "HTTP-Referer": "https://airport.guydvorkin.com",
            "X-Title": "Airport Investment Intelligence Agent",
        },
    )


def _tool_rounds(state: AgentState) -> int:
    """How many times the model has already asked for tools this thread."""
    return sum(
        1
        for m in state["messages"]
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
    )


def build_graph(
    repo: AirportRepo,
    *,
    llm: BaseChatModel | None = None,
    checkpointer: Any | None = None,
    settings: Settings | None = None,
):
    """Compile the agent graph against a repository backend."""
    s = settings or get_settings()
    tools: list[BaseTool] = build_tools(repo, s)
    by_name = {t.name: t for t in tools}
    model = llm or build_llm(s)
    # Named runs, so a trace reads "agent-step" / "final-answer" rather than two
    # identical "ChatOpenAI" rows that give no clue which step is which. The
    # tool-bound call is "agent-step" because it decides: call tools, or answer.
    model_with_tools = model.bind_tools(tools).with_config(run_name="agent-step")
    model_final = model.with_config(run_name="final-answer")

    async def agent_node(state: AgentState) -> dict[str, Any]:
        capped = _tool_rounds(state) >= s.max_tool_iterations
        system = SYSTEM_PROMPT + (f"\n\n{FORCED_ANSWER_NUDGE}" if capped else "")
        # Past the cap the model answers without tools, so a turn always ends in prose.
        runnable = model_final if capped else model_with_tools
        response = await runnable.ainvoke([SystemMessage(content=system), *state["messages"]])
        log.info(
            "agent step",
            extra={
                "tool_calls": [c["name"] for c in getattr(response, "tool_calls", []) or []],
                "capped": capped,
            },
        )
        return {"messages": [response]}

    async def _run_call(call: dict[str, Any]) -> ToolMessage:
        tool = by_name.get(call["name"])
        if tool is None:
            return ToolMessage(
                content=f'{{"error":"unknown tool {call["name"]}"}}',
                tool_call_id=call["id"],
                name=call["name"],
            )
        try:
            return await tool.ainvoke(call)
        except Exception as exc:  # a tool must never take the request down
            log.exception("tool raised", extra={"tool": call["name"]})
            return ToolMessage(
                content=f'{{"error":"tool {call["name"]} failed: {exc}"}}',
                tool_call_id=call["id"],
                name=call["name"],
                artifact={"tool": call["name"], "ok": False, "assumptions": []},
            )

    async def tools_node(state: AgentState) -> dict[str, Any]:
        last = state["messages"][-1]
        calls = list(getattr(last, "tool_calls", None) or [])
        messages = await asyncio.gather(*(_run_call(c) for c in calls))
        assumptions: list[str] = []
        for m in messages:
            artifact = getattr(m, "artifact", None) or {}
            assumptions.extend(artifact.get("assumptions") or [])
        return {"messages": list(messages), "assumptions": assumptions}

    def route(state: AgentState) -> Literal["tools", "__end__"]:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)
