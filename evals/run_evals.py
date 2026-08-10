"""CLI entry point for the golden-case evals.

    uv run python -m evals.run_evals            # all four cases
    uv run python -m evals.run_evals --case q3  # one case, with the full answer
    uv run python -m evals.run_evals --verbose  # print every answer

Exit code 0 when every case passes, 1 otherwise - safe to wire into CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from agent import configure_event_loop
from agent.logging_config import configure
from agent.settings import get_settings
from evals.cases import CASES
from evals.graders import CaseResult
from evals.runner import run_all

BANNER = (
    "Evals run against services/agent/fixtures/dataset.json (SYNTHETIC data).\n"
    "They prove routing, number fidelity and assumption discipline - not the\n"
    "real-world ranking of any airport.\n"
)


def render(results: list[CaseResult], verbose: bool) -> str:
    lines: list[str] = []
    width = max(len(r.case_id) for r in results)
    lines.append("")
    lines.append(f"{'CASE':<{width}}  {'RESULT':<7}  {'LAT':>6}  GRADERS")
    lines.append("-" * (width + 40))
    for r in results:
        graders = " ".join(
            f"{'+' if g.passed else 'x'}{g.name}" for g in r.graders
        ) or "(not run)"
        lines.append(
            f"{r.case_id:<{width}}  {'PASS' if r.passed else 'FAIL':<7}  "
            f"{r.latency_s:>5.1f}s  {graders}"
        )
        if r.error:
            lines.append(f"    error: {r.error}")
        for failure in r.failures:
            lines.append(f"    {failure}")
        if verbose and r.answer:
            lines.append("    " + "\n    ".join(r.answer.splitlines()))
            lines.append("")
    passed = sum(1 for r in results if r.passed)
    lines.append("-" * (width + 40))
    lines.append(f"{passed}/{len(results)} cases passed")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the four golden cases.")
    parser.add_argument("--case", help="substring of a case id to run just one")
    parser.add_argument("--verbose", action="store_true", help="print each full answer")
    parser.add_argument("--report", type=Path, help="write a JSON report to this path")
    args = parser.parse_args()

    configure_event_loop()
    settings = get_settings()
    configure(settings.log_level, json_output=False)
    if not settings.openrouter_key:
        print(
            "OPENROUTER_API_KEY is not set - evals need a live model. "
            "Add it to .env (see .env.example).",
            file=sys.stderr,
        )
        return 2

    cases = tuple(c for c in CASES if not args.case or args.case in c.id)
    if not cases:
        print(f"no case matches {args.case!r}", file=sys.stderr)
        return 2

    print(BANNER)
    print(f"model: {settings.agent_model}   cases: {len(cases)}")
    results = asyncio.run(run_all(cases, settings=settings))
    print(render(results, args.verbose))

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                {
                    "model": settings.agent_model,
                    "passed": sum(1 for r in results if r.passed),
                    "total": len(results),
                    "cases": [
                        {
                            "id": r.case_id,
                            "passed": r.passed,
                            "tools_called": r.tools_called,
                            "latency_s": r.latency_s,
                            "failures": r.failures,
                            "error": r.error,
                            "answer": r.answer,
                            "assumptions": r.assumptions,
                        }
                        for r in results
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nreport written to {args.report}")

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
