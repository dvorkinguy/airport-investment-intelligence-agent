# Design Document - Airport Investment Intelligence Agent

> The short version, in plain language: analysts ask investment questions in a chat.
> The agent turns each question into deterministic database queries over public US
> aviation data, computes transparent scores, and explains the result - citing every
> number, stating every assumption. The AI orchestrates and explains; it never
> invents figures.

## 1. Problem and scope

An airport-modernization investment firm wants to find US airports where renovation
pays off through increased flight and passenger capacity. The agent answers
questions like:

1. Which airports in New England are strong candidates for terminal expansion?
2. Compare LA and Santa Ana airport congestion levels.
3. What is the percentage of long-haul flights out of Anchorage?
4. What is the unmet flight demand at SFO, and why?

Scope decisions (per the brief's own emphasis on clarity over completeness): US
airports with meaningful scheduled service; multi-year historical signal over
single-day snapshots; estimates clearly labeled as estimates.

## 2. Architecture

```
User
 └─ Chat UI - Next.js (Vercel) - public landing, chat behind sign-in
     └─ Agent backend - FastAPI + LangGraph (Python)
         ├─ LLM via OpenRouter - model swappable by one env var
         ├─ Tools (read-only SQL): resolve_airport, rank_airports,
         │   airport_metrics, compare_airports, unmet_demand_estimate
         └─ Conversation state - Postgres checkpoints (crash-safe, resumable)
 Data plane: BTS T-100 + on-time stats + OurAirports/FAA metadata
             -> snapshot ingestion -> Neon Postgres -> deterministic SQL views
```

Division of labor is the core design idea: **SQL decides, AI explains.**

| Layer | Job | Why it is trusted |
|---|---|---|
| SQL views | All scoring, ranking, comparisons, estimates | Deterministic, versioned, re-runnable by any reviewer |
| LangGraph agent | Chooses tools, composes explanations, tracks conversation | Explicit state machine - testable, drawable |
| LLM | Language understanding + explanation | Constrained by system prompt to cite tool outputs only |

## 3. Scoring methodology

### Opportunity Score (0-100)

Weighted sum of five components, each normalized 0-100 across airports with at
least 100k annual passengers:

| Component | Weight | Signal | Source |
|---|---|---|---|
| Passenger growth | 0.30 | Demand trajectory | BTS T-100, YoY |
| Load factor | 0.25 | How full planes fly - demand pressure vs offered seats | BTS T-100 (passengers/seats) |
| Congestion | 0.20 | Persistent delays - operating at or past comfortable capacity | BTS on-time (share of arrivals delayed 15+ min) |
| Flight growth | 0.15 | Airline commitment trajectory | BTS T-100 departures, YoY |
| Infrastructure constraint | 0.10 | Physical headroom - fewer/shorter runways = more constrained = higher expansion upside | OurAirports/FAA runway data |

The component values are always shown alongside the total - an analyst can see WHY
an airport ranks, not just where.

### Named metrics

- **Load factor** = passengers / seats (route-weighted, by airport-year).
- **Long-haul share** = departures on segments >= 1,500 miles / total departures.
  The 1,500-mile threshold is a stated assumption, configurable in one place.
- **Congestion** = share of arrivals delayed >= 15 minutes + average delay minutes,
  from multi-year BTS on-time data. Long-term signal, not a one-day snapshot.
- **Estimated unmet demand** = max(0, demand pressure - available capacity),
  driven by load factor above sustainable norms, passenger growth outpacing seat
  growth, and persistent delay rates. This is an ESTIMATE - no public source
  observes turned-away demand directly - and the agent labels it as such,
  with its drivers, every time.

### Worked example

[GATE: insert a real ranked New England table + one unmet-demand breakdown from
the live views once data is loaded.]

## 4. Where and how AI is used - and where it is not

| Task | AI? | Detail |
|---|---|---|
| Understanding the question, resolving "LA" -> LAX vs "Los Angeles area" | Yes | LLM + resolve_airport lookup tool |
| Choosing which tools to call, in what order | Yes | LangGraph agent node, conditional routing |
| Computing scores, rankings, percentages, estimates | **No - never** | Deterministic SQL views |
| Composing the explanation, stating assumptions, suggesting follow-ups | Yes | LLM, constrained to cite tool outputs |
| Conversation memory | No | Postgres checkpoints (LangGraph) |

Model access goes through OpenRouter: one spend-capped key, model pinned by env
var. Swapping models is a configuration change, not a code change - and the
production path (cheap model for routing, stronger model for synthesis) is a
per-node setting in the same graph.

## 5. Assumptions, uncertainty, scoping

Stated in-product (the agent says these when relevant) and here:

1. Data vintage: BTS T-100 and on-time data, [GATE: years loaded]. Reporting lags
   ~2-3 months; answers cite their data years.
2. Long-haul threshold: >= 1,500 miles (domestic long-haul convention). Configurable.
3. Unmet demand is estimated from proxies (load factor, growth gap, delays) - not
   observed bookings/spill data, which airlines do not publish.
4. Congestion from historical delay shares - weather and one-off disruptions are
   smoothed by multi-year aggregation, not modeled separately.
5. Score weights are judgment calls, stated openly and trivially adjustable; the
   ranking methodology (components exposed, normalized) matters more than the
   exact weights.
6. Airports below 100k annual passengers are excluded from normalization to avoid
   small-base distortion.
7. Profitability is proxied by capacity-growth potential per the brief's own
   framing; real underwriting adds financial layers (Section 10).

## 6. Key tradeoffs

| Decision | Alternative | Why we chose this |
|---|---|---|
| Snapshot-first data (ingest once, refresh script) | Live API calls per question | Public endpoints are slow/flaky; a demo that depends on them fails randomly. Refresh = re-run one script; "uses public APIs" stays literally true |
| Single agent + tools | Multi-agent team from the start | Answer quality gate first; the graph grows to supervisor + specialists without rewrite (documented) |
| Scoring in SQL views | LLM computes from raw data | Determinism is a hard requirement; SQL is auditable by any reviewer |
| Four managed platforms (Neon/GCP/Vercel/Cloudflare) | One container | Demonstrates real integration judgment; mitigated by local-first (whole stack runs on a laptop with .env alone) |
| Postgres checkpoints for memory | In-process memory | Crash-safe, resumable conversations - and it is the same database, no new infra |

## 7. Production readiness - the 8-gate table

A system is production-grade only when all eight gates pass. Status here is
deliberate and explicit:

| # | Gate | Status |
|---|---|---|
| 1 | Tracing on every LLM call (inputs, outputs, latency, cost) | [GATE: Langfuse wired = IMPLEMENTED / else DESIGNED - slot in code] |
| 2 | Eval suite gates deploys | PARTIAL - golden dataset (the 4 target questions + variants), code-graded, runs in CI; model-graded expansion designed |
| 3 | StateGraph, not chain-of-prompts | IMPLEMENTED - typed state, explicit nodes/edges |
| 4 | Crash-safe state persistence | IMPLEMENTED - Postgres checkpointer |
| 5 | Multi-provider routing decoupled from agent code | IMPLEMENTED - OpenRouter gateway, env-pinned model |
| 6 | HTTP-shipped with auth, limits, timeouts | PARTIAL - FastAPI + timeouts + rate limit; Clerk JWT [GATE: status]; tenant isolation designed |
| 7 | Trace replay | DESIGNED - traces persist; replay/diff workflow documented |
| 8 | Prompt versioning | DESIGNED - prompts versioned in git now; registry (Langfuse Prompts) is the production path |

Anything not implemented inside the 24-hour window is stubbed visibly in code and
listed here - never silently missing.

## 8. Analyst workflow fit

Analysts live in Excel, BI dashboards, and IC memos. The tool meets them there:

- Every answer renders as verdict -> data table -> chart -> assumptions -> sources.
  Tables export to CSV / copy-paste directly into Excel.
- The REST API is the integration: Excel Power Query, a Python notebook, or a BI
  tool can read the same scoring views - no UI required.
- Click-to-ask examples on the landing page reproduce this document's four
  questions in one click.
- Production path: scheduled morning briefs, Slack/Teams bot, SSO - designed,
  listed in Section 10.

## 9. Responsible AI

- Data: US-government public domain (BTS/FAA) and open OurAirports data. No
  personal data anywhere in the system.
- Estimates are labeled; numbers trace to a named public source and data year.
- The model cannot fabricate figures by construction (tool-only numbers) - and the
  eval suite checks that behavior.
- Human-in-the-loop stance: this is decision support for analysts, not an
  auto-investing system; final judgment stays human.
- Bot protection (Cloudflare Turnstile via Clerk), secrets in managed stores,
  secret scanning + push protection + gitleaks in CI on the repository.

## 10. The complete picture - production data layers

What real underwriting would add, in priority order, each with a named public
source - designed, not built in the 24-hour window:

| Layer | Source | What it adds |
|---|---|---|
| Airport financials | FAA Form 127 / CATS (public, airport-level operating revenue + expenses) | Real operating margin; ROI proxy = est. unmet pax x net revenue per enplanement |
| Catchment demographics | US Census population + income by MSA | Demand fundamentals behind the traffic trend |
| Regulatory context | FAA AIP grants, PFC program, NEPA review timelines (curated mini-RAG) | Feasibility and timeline risk on expansion |
| Financing reality | Muni-bond structures, airport authority ownership, tax-exempt status | Why corporate-style tax modeling mostly does not apply to US airports - and what applies instead |
| Environmental constraints | Noise/curfew rules, emissions reviews | Expansion friction |
| Passenger sentiment | Maps ratings/reviews (~$0.21 per 50 airports via managed scraper) | Soft demand-quality signal |

## 11. With another week

Supervisor + specialist agents (analyst SQL / live-ops FAA+weather), voice
interface, analyst dashboard (Looker Studio on the same views), scheduled data
refresh, the layers above - in the order an investment committee would pay for
them, not in the order they are fun to build.
