# Airport Investment Intelligence Agent

An AI agent that helps investment analysts identify US airports where modernization
and expansion are most likely to pay off.

**In plain language:** you ask questions like *"Which airports in New England are
strong candidates for terminal expansion?"* and the agent answers with ranked,
explained, number-backed results - every score traceable to public government data,
every assumption stated.

Built in 24 hours as a technical exercise. Designed production-grade; parts not
implemented in the window are explicitly stubbed and documented, never silently
missing.

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

```
# 1. Copy env template and fill in keys (OpenRouter + Postgres)
cp .env.example .env
# 2. Load data snapshots + views    (details: ingestion/README)
# 3. Start agent backend            (details: services/agent/README)
# 4. Start web UI                   (details: apps/web/README)
```

Full quickstart lands with the code. Security posture: no secrets in code or git
history, gitleaks pre-commit + CI, GitHub secret scanning + push protection.
