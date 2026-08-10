"""Graph routing, assumption collection and the tool-call cap.

No LLM and no database: ``ScriptedChatModel`` decides the path, so a routing
regression fails here rather than in an eval that costs a model call.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from agent.graph import build_graph
from agent.repository import FixtureRepo
from agent.settings import Settings
from agent.state import merge_assumptions

from .conftest import ScriptedChatModel, tool_call_message

SETTINGS = Settings(openrouter_api_key="sk-or-test", repo_backend="fixture")


def run_config(thread: str = "t-1") -> dict:
    return {"configurable": {"thread_id": thread}}


async def test_no_tool_call_ends_immediately(repo: FixtureRepo) -> None:
    llm = ScriptedChatModel(responses=[AIMessage(content="Direct answer.")])
    graph = build_graph(repo, llm=llm, settings=SETTINGS)
    out = await graph.ainvoke({"messages": [HumanMessage("hi")], "thread_id": "t"})
    assert out["messages"][-1].content == "Direct answer."
    assert out.get("assumptions", []) == []


async def test_tool_call_routes_through_tools_and_back(repo: FixtureRepo) -> None:
    llm = ScriptedChatModel(
        responses=[
            tool_call_message("rank_airports", {"region": "new_england", "limit": 5}),
            AIMessage(content="Boston Logan leads at 78.4."),
        ]
    )
    graph = build_graph(repo, llm=llm, settings=SETTINGS)
    out = await graph.ainvoke({"messages": [HumanMessage("where?")], "thread_id": "t"})

    kinds = [type(m).__name__ for m in out["messages"]]
    assert kinds == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    tool_msg = next(m for m in out["messages"] if isinstance(m, ToolMessage))
    assert "BOS" in tool_msg.content
    assert out["messages"][-1].content == "Boston Logan leads at 78.4."


async def test_assumptions_land_in_typed_state(repo: FixtureRepo) -> None:
    llm = ScriptedChatModel(
        responses=[
            tool_call_message("unmet_demand_estimate", {"iata": "SFO"}),
            AIMessage(content="About 3.18M estimated."),
        ]
    )
    graph = build_graph(repo, llm=llm, settings=SETTINGS)
    out = await graph.ainvoke({"messages": [HumanMessage("sfo?")], "thread_id": "t"})
    joined = " ".join(out["assumptions"])
    assert "ESTIMATE, not an observed statistic" in joined
    assert "2022-2024" in joined


async def test_parallel_tool_calls_all_execute(repo: FixtureRepo) -> None:
    parallel = AIMessage(
        content="",
        tool_calls=[
            {"name": "airport_metrics", "args": {"iata": "LAX"}, "id": "a", "type": "tool_call"},
            {"name": "airport_metrics", "args": {"iata": "SNA"}, "id": "b", "type": "tool_call"},
        ],
    )
    llm = ScriptedChatModel(responses=[parallel, AIMessage(content="Both fetched.")])
    graph = build_graph(repo, llm=llm, settings=SETTINGS)
    out = await graph.ainvoke({"messages": [HumanMessage("compare")], "thread_id": "t"})
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 2
    assert {m.tool_call_id for m in tool_msgs} == {"a", "b"}


async def test_unknown_tool_does_not_crash_the_turn(repo: FixtureRepo) -> None:
    llm = ScriptedChatModel(
        responses=[
            tool_call_message("predict_stock_price", {}),
            AIMessage(content="I cannot do that."),
        ]
    )
    graph = build_graph(repo, llm=llm, settings=SETTINGS)
    out = await graph.ainvoke({"messages": [HumanMessage("guess")], "thread_id": "t"})
    tool_msg = next(m for m in out["messages"] if isinstance(m, ToolMessage))
    assert "unknown tool" in tool_msg.content
    assert out["messages"][-1].content == "I cannot do that."


async def test_tool_loop_is_capped_and_still_produces_prose(repo: FixtureRepo) -> None:
    """A model that only ever asks for tools must still end the turn in text."""
    capped = Settings(openrouter_api_key="sk-or-test", repo_backend="fixture",
                      max_tool_iterations=2)
    llm = ScriptedChatModel(
        responses=[
            tool_call_message("airport_metrics", {"iata": "SFO"}, call_id=f"c{i}")
            for i in range(5)
        ]
    )
    graph = build_graph(repo, llm=llm, settings=capped)
    out = await graph.ainvoke({"messages": [HumanMessage("loop")], "thread_id": "t"})
    tool_rounds = sum(
        1 for m in out["messages"] if isinstance(m, AIMessage) and m.tool_calls
    )
    assert tool_rounds == 2
    assert out["messages"][-1].content == "Stopping here with what I have."


async def test_checkpointer_carries_the_thread_across_turns(repo: FixtureRepo) -> None:
    llm = ScriptedChatModel(
        responses=[AIMessage(content="First."), AIMessage(content="Second.")]
    )
    graph = build_graph(repo, llm=llm, settings=SETTINGS, checkpointer=MemorySaver())
    cfg = run_config("thread-A")
    await graph.ainvoke({"messages": [HumanMessage("one")], "thread_id": "thread-A"}, cfg)
    out = await graph.ainvoke({"messages": [HumanMessage("two")], "thread_id": "thread-A"}, cfg)
    assert [m.content for m in out["messages"]] == ["one", "First.", "two", "Second."]


async def test_system_prompt_is_prepended_but_not_stored(repo: FixtureRepo) -> None:
    llm = ScriptedChatModel(responses=[AIMessage(content="ok")])
    graph = build_graph(repo, llm=llm, settings=SETTINGS)
    out = await graph.ainvoke({"messages": [HumanMessage("q")], "thread_id": "t"})
    assert llm.seen[0][0].type == "system"
    assert "must come from a tool result" in llm.seen[0][0].content
    assert all(m.type != "system" for m in out["messages"])


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ([], ["a"], ["a"]),
        (["a"], ["a"], ["a"]),
        (["a"], ["b", "a"], ["a", "b"]),
        (["a"], [], ["a"]),
    ],
)
def test_assumption_reducer_dedupes_in_order(left, right, expected) -> None:
    assert merge_assumptions(left, right) == expected
