"""Code graders.

No LLM judge: every check is a deterministic assertion over the transcript, so a
run is reproducible and a failure points at one specific defect.

Five graders, one per failure mode we actually care about:
  tools       - did it reach for the right instrument?
  numbers     - did the tool's figures survive into the answer?
  assumptions - did it say what it assumed and on what data vintage?
  terms       - did it name the entities and definitions the question needs?
  loop        - did it retry a failing tool call unchanged, or run into the cap?
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from evals.cases import ASSUMPTION_MARKERS, EvalCase


@dataclass
class GraderResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class CaseResult:
    case_id: str
    question: str
    answer: str
    tools_called: list[str]
    assumptions: list[str]
    graders: list[GraderResult] = field(default_factory=list)
    error: str | None = None
    latency_s: float = 0.0
    #: "tool: error" for every tool call that came back ok=False this turn.
    tool_failures: list[str] = field(default_factory=list)
    #: The turn hit max_tool_iterations and was forced to answer without tools.
    capped: bool = False

    @property
    def passed(self) -> bool:
        return self.error is None and all(g.passed for g in self.graders)

    @property
    def failures(self) -> list[str]:
        return [f"{g.name}: {g.detail}" for g in self.graders if not g.passed]


def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace; keep digits, commas and dots intact."""
    return re.sub(r"\s+", " ", (text or "").lower())


def grade_tools(case: EvalCase, tools_called: list[str]) -> GraderResult:
    missing = [t for t in case.required_tools if t not in tools_called]
    too_few = len(tools_called) < case.min_tool_calls
    return GraderResult(
        "tools",
        not missing and not too_few,
        f"required {case.required_tools or f'{case.min_tool_calls}+ calls'}, "
        f"called {tools_called or '[]'}"
        if missing or too_few
        else "",
    )


def grade_loop(tool_failures: list[str], capped: bool) -> GraderResult:
    """The 2026-10-10 GLM failure: the same failing call ten times, then the cap.

    One failure is fine - the model is meant to read the error and fix the call.
    The same failure twice means it did not, and every further round is wasted.
    """
    repeated = sorted({f for f in tool_failures if tool_failures.count(f) > 1})
    problems = []
    if repeated:
        problems.append(f"same tool failure repeated: {repeated}")
    if capped:
        problems.append("hit the tool-call cap; answer was forced without tools")
    return GraderResult("loop", not problems, "; ".join(problems))


def grade_numbers(case: EvalCase, answer: str) -> GraderResult:
    text = _normalize(answer)
    missing = [
        alts for alts in case.required_numbers
        if not any(alt.lower() in text for alt in alts)
    ]
    return GraderResult(
        "numbers",
        not missing,
        "answer is missing figures: " + "; ".join(" | ".join(a) for a in missing)
        if missing
        else "",
    )


def grade_assumptions(case: EvalCase, answer: str, assumptions: list[str]) -> GraderResult:
    text = _normalize(answer)
    stated = any(marker in text for marker in ASSUMPTION_MARKERS)
    collected = bool(assumptions)
    if stated and collected:
        return GraderResult("assumptions", True)
    detail = []
    if not stated:
        detail.append("no assumption line in the answer")
    if not collected:
        detail.append("no assumptions captured in graph state")
    return GraderResult("assumptions", False, "; ".join(detail))


def grade_terms(case: EvalCase, answer: str) -> GraderResult:
    text = _normalize(answer)
    missing = [
        alts for alts in case.required_terms
        if not any(alt.lower() in text for alt in alts)
    ]
    banned = [t for t in case.forbidden_terms if t.lower() in text]
    problems = []
    if missing:
        problems.append("missing: " + "; ".join(" | ".join(a) for a in missing))
    if banned:
        problems.append(f"forbidden terms present: {banned}")
    return GraderResult("terms", not problems, "; ".join(problems))


def grade(case: EvalCase, result: CaseResult) -> CaseResult:
    if result.error:
        return result
    result.graders = [
        grade_tools(case, result.tools_called),
        grade_numbers(case, result.answer),
        grade_assumptions(case, result.answer, result.assumptions),
        grade_terms(case, result.answer),
        grade_loop(result.tool_failures, result.capped),
    ]
    return result
