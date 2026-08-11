# Airport Investment Intelligence Agent

[![ci](https://github.com/dvorkinguy/airport-investment-intelligence-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/dvorkinguy/airport-investment-intelligence-agent/actions/workflows/ci.yml)
[![security](https://github.com/dvorkinguy/airport-investment-intelligence-agent/actions/workflows/security.yml/badge.svg)](https://github.com/dvorkinguy/airport-investment-intelligence-agent/actions/workflows/security.yml)
[![license](https://img.shields.io/badge/license-proprietary-blue)](LICENSE)

An AI agent that helps investment analysts identify US airports where modernization
and expansion are most likely to pay off.

**In plain language:** you ask questions like *"Which airports in New England are
strong candidates for terminal expansion?"* and the agent answers with ranked,
explained, number-backed results - every score traceable to public government data,
every assumption stated.

Built in 24 hours as a technical exercise. Designed production-grade; parts not
implemented in the window are explicitly stubbed and documented, never silently
missing.

**Live demo:** [airport.guydvorkin.com](https://airport.guydvorkin.com) - landing is
public, chat is behind a free sign-in. Backend health:
[Cloud Run /health](https://airport-agent-532602559497.europe-west3.run.app/health).

## What it can answer

- Which airports in a region are strong candidates for terminal expansion
- Congestion comparison between any two airports
- Share of long-haul flights out of a given airport
- Estimated unmet flight demand at an airport, and why

## How it works

```
You -> Chat UI (Next.js, Vercel)
       -> Agent backend (FastAPI + LangGraph, Python)
          -> LLM via OpenRouter (swappable by env var)
          -> Tools -> deterministic SQL scoring views (Neon Postgres)
Data: US DOT/BTS T-100 + on-time statistics, FAA airport data (snapshot-first)
```

The LLM never invents numbers. All scoring and ranking is deterministic SQL that
any reviewer can read and re-run; the LLM's job is orchestration and explanation.

## Documentation

| Doc | Content |
|---|---|
| [docs/design.md](docs/design.md) | Scoring methodology, key tradeoffs, where/how AI is used |
| [docs/architecture.md](docs/architecture.md) | System architecture, one section per decision |
| [docs/adr/](docs/adr/) | Architecture Decision Records - the reasoning trail |
| [docs/research/api-comparison.html](docs/research/api-comparison.html) | Aviation data API evaluation matrix |

## Running locally

Prerequisites: [uv](https://docs.astral.sh/uv/) (it resolves Python >= 3.11 from
`pyproject.toml` itself) and Node 20+ with npm. All commands run from the repo
root, in PowerShell or any POSIX shell (in `cmd.exe`, read `cp` as `copy`).

```bash
# 1. Environment - fill in OPENROUTER_API_KEY (DATABASE_URL is optional, see below)
cp .env.example .env

# 2. Agent backend -> http://localhost:8000    (details: services/agent/README.md)
uv sync --extra dev
uv run python -m agent

# 3. Web UI -> http://localhost:3000           (details: apps/web/README.md)
cd apps/web && npm install && npm run dev
```

No `DATABASE_URL`? The backend starts on a bundled JSON fixture dataset, so the
whole stack runs before any database exists. Loading the real snapshots into
Postgres is a later step, not a prerequisite - see
[ingestion/README.md](ingestion/README.md).

Prove it works:

```bash
uv run pytest                      # unit + integration - offline, no keys needed
uv run python -m evals.run_evals   # 5 golden cases, code-graded, live model
```

## Engineering practice

- Trunk-based on `main`, with CI gating every push and pull request: pytest, the
  golden evals, the web build, and a full-history `gitleaks` scan.
- Secrets are caught before they land - `gitleaks` runs as a local pre-commit
  hook, and the same tool runs again in CI as the second net.
- Decisions are recorded as ADRs in [docs/adr/](docs/adr/), so the reasoning
  trail survives, not just the outcome.
- Agent changes are eval-driven: a defect gets a regression test written against
  the old code and proven to fail there before the fix lands.
- Verified states are tagged (for example `night-close-verified-2026-08-10`), so
  a known-good commit stays addressable.

Security posture and reporting: [SECURITY.md](SECURITY.md). Licensing:
[LICENSE](LICENSE) - shared for evaluation, no reuse rights granted.
