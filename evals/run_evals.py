"""CLI entry point for the golden-case evals.

    uv run python -m evals.run_evals            # all four cases
    uv run python -m evals.run_evals --case q3  # one case, with the full answer
    uv run python -m evals.run_evals --verbose  # print every answer
    uv run python -m evals.run_evals --repeat 3 # every case three times

    # Real visitor questions (one per line) on the real database, graded on
    # behaviour only - tools used, no failure loop, assumptions stated:
    uv run python -m evals.run_evals --questions q.txt --backend postgres --repeat 3

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
from evals.cases import CASES, smoke_case
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
    parser.add_argument("--repeat", type=int, default=1, help="run every case N times")
    parser.add_argument(
        "--questions", type=Path,
        help="file of real questions, one per line, run instead of the golden cases",
    )
    parser.add_argument(
        "--backend", choices=("fixture", "postgres"), default="fixture",
        help="data behind the tools; golden cases only hold on fixture",
    )
    parser.add_argument("--concurrency", type=int, default=4, help="parallel cases")
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

    if args.questions:
        lines = [q.strip() for q in args.questions.read_text(encoding="utf-8").splitlines()]
        cases = tuple(smoke_case(f"real{i + 1:02d}", q) for i, q in enumerate(x for x in lines if x))
    else:
        cases = tuple(c for c in CASES if not args.case or args.case in c.id)
    if not cases:
        print(f"no case matches {args.case!r}", file=sys.stderr)
        return 2
    if args.backend == "postgres" and not settings.database_dsn:
        print("--backend postgres needs DATABASE_URL", file=sys.stderr)
        return 2

    print(BANNER if args.backend == "fixture" else "Evals run against the live Neon database.\n")
    print(
        f"model: {settings.agent_model}   providers: {settings.agent_providers or '(OpenRouter picks)'}"
        f"   cases: {len(cases)} x {args.repeat}"
    )
    results = asyncio.run(_run(cases, settings, args))
    print(render(results, args.verbose))

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                {
                    "model": settings.agent_model,
                    "providers": settings.agent_providers,
                    "backend": args.backend,
                    "repeat": args.repeat,
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
                            "tool_failures": r.tool_failures,
                            "capped": r.capped,
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


async def _run(cases, settings, args) -> list[CaseResult]:
    repo = None
    if args.backend == "postgres":
        from agent.repository import PostgresRepo

        repo = PostgresRepo(
            settings.database_dsn or "",
            min_size=settings.db_pool_min_size,
            max_size=settings.db_pool_max_size,
            statement_timeout_ms=settings.db_statement_timeout_ms,
            max_idle_seconds=settings.db_pool_max_idle_seconds,
            max_lifetime_seconds=settings.db_pool_max_lifetime_seconds,
        )
        await repo.open()
    try:
        return await run_all(
            cases, repo=repo, settings=settings,
            repeat=args.repeat, concurrency=args.concurrency,
        )
    finally:
        if repo is not None:
            await repo.close()


if __name__ == "__main__":
    raise SystemExit(main())
