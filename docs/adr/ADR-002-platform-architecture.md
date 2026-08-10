# ADR-002: Platform architecture

Status: accepted | Date: 2026-08-10

**Plain language:** the system is split across four cloud platforms, each doing the
one thing it is best at. This mirrors how enterprise systems are actually built -
and each choice is written down with its tradeoff, including what we deliberately
did NOT use.

## Decision

| Platform | Role | Why |
|---|---|---|
| Neon Postgres | Data snapshots + deterministic scoring as SQL views + agent state checkpoints | Scoring is auditable SQL any reviewer can re-run; serverless Postgres, scale-to-zero |
| GCP Cloud Run | Agent backend (FastAPI + LangGraph) + ingestion job | Serverless containers, scale-to-zero, dedicated GCP project for IAM/billing isolation |
| Vercel | Next.js chat UI, streaming | Purpose-built Next.js host; push-to-deploy CI/CD |
| Cloudflare | Turnstile bot protection (via Clerk); DNS | Real security value with zero proxy risk |
| GCP Secret Manager | Canonical secret store | Each runtime uses its native store; SM is the source of truth |

## Tradeoffs stated

- **Could have been one container.** A single VM would work. We chose distributed
  platforms to demonstrate integration judgment; the cost is four deploy surfaces,
  mitigated by local-first (everything runs locally with .env alone).
- **Cloudflare does NOT proxy the web app.** Its free-tier bot protection is
  incompatible with Vercel as an origin (verified failure mode). Cloudflare's role
  is scoped to what adds value without that risk.
- **One GCP project, not dev/prod pairs.** Right-sized for a demo; the production
  path (separate projects per environment) is documented in docs/design.md.
