"""Run the golden cases against the graph.

Data comes from ``FixtureRepo`` - no database, no network beyond the LLM call -
so a red run means the agent changed, never that the data moved.
"""

from __future__ import annotations

import asyncio
import time

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from agent.graph import _tool_rounds, build_graph
from agent.repository import AirportRepo, FixtureRepo
from agent.settings import Settings, get_settings
from evals.cases import CASES, EvalCase
from evals.graders import CaseResult, grade


def message_text(message: AIMessage) -> str:
    """Plain text of a message across content shapes and langchain versions."""
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content or "")


async def run_case(
    case: EvalCase,
    *,
    repo: AirportRepo | None = None,
    llm: BaseChatModel | None = None,
    settings: Settings | None = None,
) -> CaseResult:
    s = settings or get_settings()
    graph = build_graph(
        repo or FixtureRepo(), llm=llm, checkpointer=MemorySaver(), settings=s
    )
    started = time.perf_counter()
    try:
        state = await asyncio.wait_for(
            graph.ainvoke(
                {"messages": [HumanMessage(content=case.question)], "thread_id": case.id},
                {
                    "configurable": {"thread_id": case.id},
                    "recursion_limit": s.max_tool_iterations * 2 + 4,
                },
            ),
            timeout=s.request_timeout_seconds,
        )
    except Exception as exc:
        return CaseResult(
            case_id=case.id,
            question=case.question,
            answer="",
            tools_called=[],
            assumptions=[],
            error=f"{type(exc).__name__}: {exc}",
            latency_s=round(time.perf_counter() - started, 2),
        )

    messages = state["messages"]
    tools_called = [
        call["name"]
        for m in messages
        if isinstance(m, AIMessage)
        for call in (m.tool_calls or [])
    ]
    tool_failures = [
        f"{m.name}: {(m.artifact or {}).get('error') or m.content}"
        for m in messages
        if isinstance(m, ToolMessage) and (m.artifact or {}).get("ok") is False
    ]
    answer = ""
    for m in reversed(messages):
        if isinstance(m, AIMessage) and not m.tool_calls and message_text(m):
            answer = message_text(m)
            break

    return grade(
        case,
        CaseResult(
            case_id=case.id,
            question=case.question,
            answer=answer,
            tools_called=tools_called,
            assumptions=list(state.get("assumptions", [])),
            latency_s=round(time.perf_counter() - started, 2),
            tool_failures=tool_failures,
            capped=_tool_rounds(state) >= s.max_tool_iterations,
        ),
    )


async def run_all(
    cases: tuple[EvalCase, ...] = CASES,
    *,
    repo: AirportRepo | None = None,
    llm: BaseChatModel | None = None,
    settings: Settings | None = None,
    repeat: int = 1,
    concurrency: int = 0,
) -> list[CaseResult]:
    """Cases are independent; run them concurrently.

    ``repeat`` runs every case that many times: one pass of a non-deterministic
    model proves little (GLM passed q1 once, then failed the same question live).
    ``concurrency`` > 0 bounds parallel cases, for a small database pool.
    """
    shared_repo = repo or FixtureRepo()
    gate = asyncio.Semaphore(concurrency) if concurrency > 0 else None

    async def one(c: EvalCase, k: int) -> CaseResult:
        if gate is None:
            r = await run_case(c, repo=shared_repo, llm=llm, settings=settings)
        else:
            async with gate:
                r = await run_case(c, repo=shared_repo, llm=llm, settings=settings)
        if repeat > 1:
            r.case_id = f"{c.id}#{k + 1}"
        return r

    return list(
        await asyncio.gather(*(one(c, k) for c in cases for k in range(repeat)))
    )
