"""Typed graph state.

``assumptions`` is first-class state rather than something buried in a tool
message: the API returns the exact assumption set that stood behind an answer,
and the eval graders check it without parsing prose.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


def merge_assumptions(left: list[str] | None, right: list[str] | None) -> list[str]:
    """Reducer: append new assumptions, de-duplicated, order preserved."""
    out: list[str] = []
    seen: set[str] = set()
    for item in list(left or []) + list(right or []):
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


class AgentState(TypedDict):
    """State carried across every node and checkpointed per thread."""

    messages: Annotated[list[AnyMessage], add_messages]
    thread_id: str
    assumptions: Annotated[list[str], merge_assumptions]
