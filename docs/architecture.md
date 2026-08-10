# Architecture

> Living document - one section per decision. The reasoning trail lives in
> [adr/](adr/); this file is the current-state picture.

## System overview

**Plain language:** a user asks investment questions in a chat. The agent
translates each question into deterministic database queries against public
aviation data, computes scores with transparent SQL, and explains the result -
citing numbers, assumptions, and data vintage.

```
User
 └─ Chat UI - Next.js on Vercel (public landing; chat behind Clerk sign-in)
     └─ Agent backend - FastAPI + LangGraph on Cloud Run (local-first)
         ├─ LLM via OpenRouter (AGENT_MODEL env var, spend-capped key)
         ├─ Tools (read-only SQL against Neon views):
         │    rank_airports · compare_airports · airport_metrics
         │    unmet_demand_estimate · resolve_airport
         └─ Conversation checkpoints - Postgres (LangGraph PostgresSaver)
 Data plane (snapshot-first):
   BTS T-100 + on-time CSVs -> ingestion script -> Neon tables -> scoring views
 Observability: Langfuse traces (T2) · queries log table
 Security: no secrets in code/history · gitleaks (pre-commit + CI) ·
           GitHub secret scanning + push protection · Turnstile via Clerk
```

## Component sections

Each locked decision gets its section here as it is implemented.

- Data sources and scoring: see [adr/ADR-001-data-sources.md](adr/ADR-001-data-sources.md)
- Platforms: see [adr/ADR-002-platform-architecture.md](adr/ADR-002-platform-architecture.md)
- Agent runtime / LLM / auth: see [adr/ADR-003-agent-runtime-llm-auth.md](adr/ADR-003-agent-runtime-llm-auth.md)
- Scoring methodology + production-readiness (8-gate) table: docs/design.md
