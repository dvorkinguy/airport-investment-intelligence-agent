# ADR-003: Agent runtime, LLM gateway, auth

Status: accepted | Date: 2026-08-10

**Plain language:** the agent's reasoning process is an explicit flowchart
(a LangGraph state machine), not a hidden loop - so it can be tested, drawn, and
extended. The AI model behind it is swappable by changing one configuration line.
Users sign in with Google or an email link; the landing page stays public.

## Decisions

1. **LangGraph StateGraph** as the agent runtime: typed state, explicit
   agent/tools nodes, conditional routing, Postgres-checkpointed conversations
   (crash-safe, and conversational follow-ups come from the same mechanism).
   Single agent first; the graph grows to supervisor + specialists without a
   rewrite (documented production path).
2. **OpenRouter as the LLM gateway**: one spend-capped key, model pinned via
   `AGENT_MODEL` env var. Provider routing is decoupled from agent code - swapping
   models is a config change, not a refactor.
3. **Clerk authentication**: Google one-click + email magic link, no passwords.
   Chat requires sign-in; landing page is public so a reviewer sees value before
   authenticating. Bot protection (Cloudflare Turnstile) enabled through Clerk.
4. **Usage tracking**: every question/answer logged to a `queries` table in Neon
   (user, question, tools used, latency) - doubles as per-user history.
5. **Langfuse tracing** on every LLM call (Tier 2): inputs, outputs, latency, cost.

## Rejected for this build

| Considered | Verdict |
|---|---|
| n8n for ingestion scheduling | Rejected - a script run on demand beats a workflow runtime for a snapshot pipeline; production path (scheduled refresh) documented instead |
| Grafana dashboards | Deferred - Langfuse covers LLM observability at this scale |
| Multi-agent from the start | Deferred - single agent must pass the answer-quality gate first |
