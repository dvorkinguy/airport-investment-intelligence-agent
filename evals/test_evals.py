"""Eval suite, two layers.

Layer 1 (always runs, no LLM, no database): the graders and the runner are
themselves tested - a grader that cannot fail is worse than no grader.

Layer 2 (``-m eval``, needs OPENROUTER_API_KEY): the four golden cases against a
live model and fixture data. Skipped rather than silently passed when the key is
absent, so a green run without the marker never claims more than it checked.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from langchain_core.messages import AIMessage

from agent.repository import FixtureRepo
from agent.settings import Settings, get_settings
from evals.cases import CASES, EvalCase
from evals.graders import (
    CaseResult,
    grade,
    grade_assumptions,
    grade_numbers,
    grade_terms,
    grade_tools,
)
from evals.runner import run_all, run_case

GOOD_Q1_ANSWER = """\
**Answer** Boston Logan (BOS) is the strongest terminal-expansion candidate in New
England at 78.4 of 100, ahead of Providence (PVD) at 71.6.

**Evidence**
| Airport | Score |
|---|---|
| BOS | 78.4 |
| PVD | 71.6 |

**Assumptions and data vintage** Scores are a deterministic SQL composite; figures
cover 2022-2024.
"""


# --- Layer 1: the graders themselves -------------------------------------


def case(case_id: str) -> EvalCase:
    return next(c for c in CASES if c.id.startswith(case_id))


def test_the_suite_covers_the_four_exam_questions_plus_the_financial_check() -> None:
    assert len(CASES) == 5
    assert {c.id for c in CASES} == {
        "q1_new_england_expansion",
        "q2_lax_vs_sna_congestion",
        "q3_anchorage_long_haul",
        "q4_sfo_unmet_demand",
        # Not one of the four target questions: the T2.5 differentiator (ADR-004), guarding that a
        # capacity case gets tested against the airport's actual finances.
        "q5_bangor_financial_health",
    }
    assert all(c.required_tools and c.required_numbers for c in CASES)


def test_tool_grader_rejects_the_wrong_instrument() -> None:
    c = case("q2")
    assert grade_tools(c, ["compare_airports"]).passed
    assert not grade_tools(c, ["airport_metrics"]).passed
    assert not grade_tools(c, []).passed


def test_number_grader_rejects_an_answer_without_the_figure() -> None:
    c = case("q1")
    assert grade_numbers(c, "BOS scores 78.4 of 100.").passed
    assert not grade_numbers(c, "BOS is the clear leader.").passed


def test_number_grader_accepts_documented_renderings() -> None:
    c = case("q4")
    for rendering in ("3,180,000", "3180000", "about 3.18 million"):
        assert grade_numbers(c, f"Estimated {rendering} passengers.").passed


def test_assumption_grader_needs_both_prose_and_state() -> None:
    c = case("q3")
    assert grade_assumptions(c, "Assumptions: 1,500 miles.", ["a"]).passed
    assert not grade_assumptions(c, "46.3% are long-haul.", ["a"]).passed
    assert not grade_assumptions(c, "Assumptions: 1,500 miles.", []).passed


def test_terms_grader_accepts_either_spelling() -> None:
    c = case("q3")
    assert grade_terms(c, "ANC, threshold 1,500 miles").passed
    assert grade_terms(c, "Anchorage, threshold 1500 miles").passed
    assert not grade_terms(c, "Anchorage long-haul share is high").passed


def test_forbidden_terms_fail_a_case() -> None:
    c = EvalCase(
        id="x", question="q", required_tools=(), required_numbers=(),
        forbidden_terms=("i estimate",),
    )
    assert not grade_terms(c, "I estimate the figure at 3 million.").passed


def test_a_case_that_errored_never_counts_as_passed() -> None:
    result = CaseResult("x", "q", "", [], [], error="boom")
    assert not grade(case("q1"), result).passed


async def test_runner_grades_a_scripted_correct_answer() -> None:
    """End-to-end wiring check for the eval harness itself - no live model."""
    from tests.conftest import ScriptedChatModel, tool_call_message

    llm = ScriptedChatModel(
        responses=[
            tool_call_message("rank_airports", {"region": "new_england", "limit": 5}),
            AIMessage(content=GOOD_Q1_ANSWER),
        ]
    )
    result = await run_case(
        case("q1"),
        repo=FixtureRepo(),
        llm=llm,
        settings=Settings(openrouter_api_key="sk-or-test", repo_backend="fixture"),
    )
    assert result.tools_called == ["rank_airports"]
    assert result.assumptions
    assert result.passed, result.failures


async def test_runner_fails_a_scripted_hallucination() -> None:
    """An answer with an invented number must be caught, not waved through."""
    from tests.conftest import ScriptedChatModel, tool_call_message

    llm = ScriptedChatModel(
        responses=[
            tool_call_message("rank_airports", {"region": "new_england", "limit": 5}),
            AIMessage(content="Boston Logan leads with a score of 91.2. Providence follows."),
        ]
    )
    result = await run_case(
        case("q1"),
        repo=FixtureRepo(),
        llm=llm,
        settings=Settings(openrouter_api_key="sk-or-test", repo_backend="fixture"),
    )
    assert not result.passed
    assert any("numbers" in f for f in result.failures)


# --- Layer 2: the live golden cases --------------------------------------

live = pytest.mark.skipif(
    not os.getenv("OPENROUTER_API_KEY") and not get_settings().openrouter_key,
    reason="OPENROUTER_API_KEY not set; live golden cases need a model",
)


@live
@pytest.mark.eval
def test_golden_cases_against_a_live_model() -> None:
    results = asyncio.run(run_all(CASES))
    failures = [f"{r.case_id}: {r.failures or r.error}" for r in results if not r.passed]
    assert not failures, "\n".join(failures)
