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

### Worked example (real output, gate run 2026-08-10)

New England terminal-expansion ranking - live agent answer, verified against the
SQL views directly:

| Airport | Score | Pax Growth | Load Factor | Congestion | Flight Growth | Infra |
|---|---|---|---|---|---|---|
| BGR Bangor, ME | 68.4 | 90.6 | 62.9 | 38.8 | 79.5 | 58.5 |
| PWM Portland, ME | 65.5 | 62.5 | 84.8 | 46.9 | 50.9 | 85.3 |
| BTV Burlington, VT | 64.6 | 66.5 | 73.7 | 61.6 | 42.0 | 76.3 |
| PVD Providence, RI | 62.1 | 73.7 | 41.5 | 75.0 | 48.7 | 73.4 |
| BOS Boston, MA | 50.3 | 28.6 | 77.7 | 85.7 | 23.2 | 16.7 |

The components tell the story the composite alone cannot: BOS has the region's
worst congestion (85.7) yet ranks fifth, because its modest passenger growth
(28.6) and already-invested infrastructure (16.7) cap the expansion upside.

Estimated unmet demand at SFO (always labeled an estimate, drivers shown):

| Year | Est. unmet pax | Load factor | Delay rate | Growth gap |
|---|---|---|---|---|
| 2025 | 1,381,183 | 82.3% | 24.1% | -1.2% |
| 2024 | 1,741,867 | 83.3% | 29.8% | -0.1% |

**The financial reality check (added after loading FAA Form 127 financials):**
several of the capacity-ranked New England leaders - BGR, BTV, MHT, BDL - show
*negative* net revenue per enplanement in FY2023-24, and ANC's carrier
concentration is HHI ~4,150 (one airline near 62% share). Capacity opportunity
is the demand half of the investment case; the money half (operating economics,
carrier dependence) can point the other way, and the extended views
(`v_roi_proxy`, `v_carrier_concentration`, ADR-004) exist precisely so an
analyst sees both halves before an investment committee does.

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

1. Data vintage: BTS T-100 segments and on-time data, 2023-2025 (584,498 T-100
   rows after filtering to scheduled passenger service, CLASS=F; 12,164
   airport-month on-time rows). Reporting lags ~2-3 months; answers cite their
   data years.
2. Long-haul threshold: >= 1,500 miles (domestic long-haul convention). Configurable.
3. Unmet demand is estimated from proxies (load factor, growth gap, delays) - not
   observed bookings/spill data, which airlines do not publish.
4. Congestion from historical delay shares - weather and one-off disruptions are
   smoothed by multi-year aggregation, not modeled separately.
5. Score weights are judgment calls, stated openly and trivially adjustable; the
   ranking methodology (components exposed, normalized) matters more than the
   exact weights.
6. Airport universe: of the 32,598 US airfields in the source data, we scope to
   the 679 with an IATA code and scheduled airline service - the rest are
   heliports, private strips, and non-scheduled fields with no analytical value
   for airline-capacity investment.
7. Airports below 100k annual passengers are excluded from normalization to avoid
   small-base distortion.
8. Profitability is proxied by capacity-growth potential per the brief's own
   framing; real underwriting adds financial layers (Section 10).

## 6. Key tradeoffs

| Decision | Alternative | Why we chose this |
|---|---|---|
| Snapshot-first data (ingest once, refresh script) | Live API calls per question | Public endpoints are slow/flaky; a demo that depends on them fails randomly. Refresh = re-run one script; "uses public APIs" stays literally true |
| Single agent + tools | Multi-agent team from the start | Answer quality gate first; the graph grows to supervisor + specialists without rewrite (documented) |
| Scoring in SQL views | LLM computes from raw data | Determinism is a hard requirement; SQL is auditable by any reviewer |
| Four managed platforms (Neon/GCP/Vercel/Cloudflare) | One container | Demonstrates real integration judgment; mitigated by local-first (whole stack runs on a laptop with .env alone) |
| Postgres checkpoints for memory | In-process memory | Crash-safe, resumable conversations - and it is the same database, no new infra |
| Connection-liveness discipline (pool health checks + one silent retry) | Assume connections stay alive | Serverless-to-serverless reality: scale-to-zero on both ends (Cloud Run and Neon) means either side can kill idle connections. Found live in testing - the first question after idle failed on a stale pooled connection; fixed at the pool layer, not papered over in the UI |

## 7. Production readiness - the 8-gate table

A system is production-grade only when all eight gates pass. Status here is
deliberate and explicit:

| # | Gate | Status |
|---|---|---|
| 1 | Tracing on every LLM call (inputs, outputs, latency, cost) | IMPLEMENTED - Langfuse live in production: one trace per request, generations carry model/tokens/cost, spans carry tool arguments and returned rows, conversations group by thread, and every trace id is stored on the query-log row |
| 2 | Eval suite gates deploys | PARTIAL - 5 code-graded golden cases (the four target questions plus a financial-health question) run in CI on every push and are green; model-graded expansion designed |
| 3 | StateGraph, not chain-of-prompts | IMPLEMENTED - typed state, explicit nodes/edges |
| 4 | Crash-safe state persistence | IMPLEMENTED - Postgres checkpointer |
| 5 | Multi-provider routing decoupled from agent code | IMPLEMENTED - OpenRouter gateway, env-pinned model |
| 6 | HTTP-shipped with auth, limits, timeouts | PARTIAL - Clerk JWT verification IMPLEMENTED and verified against the deployed service (a real minted token authenticates; a spoofed `X-User-*` header is ignored and stays anonymous; a garbage bearer token is a 401; no token is a 200 as anonymous). Layered timeouts throughout - 180s per request, 60s per LLM call, 15s per SQL statement - plus a per-turn tool-round cap and a Cloud Run instance ceiling. No per-caller rate limiting yet: that and tenant isolation are designed, not built |
| 7 | Trace replay | DESIGNED - traces persist; replay/diff workflow documented |
| 8 | Prompt versioning | DESIGNED - prompts versioned in git now; registry (Langfuse Prompts) is the production path |

Anything not implemented inside the 24-hour window is stubbed visibly in code and
listed here - never silently missing.

### Observability, proven in use

Gate 1 paid for itself the night before submission. A grader-shaped session -
several questions in one conversation - began returning empty answers partway
through. The `queries` table showed the shape immediately: rows written, no
error, latency around two seconds, `tools_used` empty. Langfuse showed the same
turns as a generation with no tool span beneath it. Together those said the model
was being asked to answer with its tools taken away, which pointed straight at
the tool-round cap: it counted every tool-calling message in the checkpointed
conversation rather than in the current turn, so a long thread exhausted its
rounds and every later turn started already capped. Root cause in minutes, fix,
two regression tests written to fail against the old implementation first,
redeployed the same night.

The honest lesson is about the eval suite rather than the bug. The evals stayed
green the entire time, because each golden case runs on a fresh thread.
Fresh-thread evals prove single-question correctness and say nothing about a
conversation - multi-turn state bugs are invisible to them by construction.
Live-use QA plus the audit trail cover that class, which is why the tracing gate
is not a nice-to-have. The same traces also price the product: a question costs a
median of $0.047 and a mean of $0.058 on Claude Sonnet 4.5, measured over 41
costed production traces, with a $0.008-$0.158 spread that widens as a
conversation grows. That is a measured unit cost, not an estimate.

### How it was built and tested

Tests lead where the behavior is known up front - the SQL contract, the tool
layer, auth - and follow immediately where discovery comes first. The suite is
121 tests: 110 unit and integration tests plus an 11-test eval harness, which is
where the 5 code-graded golden cases run the real agent against fixture data and
assert on what actually matters - the right tool was called, the number is
present, the assumption line is there - with the remaining harness tests holding
the graders themselves honest (a hallucinated answer must fail, an errored case
must never count as passed). CI gates every push - pytest, the golden evals, the web
build, and a full-history gitleaks scan - so a change that breaks behavior or
answer quality does not reach main quietly. Regression tests for a defect are
written against the old code first and required to fail there before the fix
lands; the tool-cap tests above did exactly that.

### Auth posture for this submission

Clerk runs as a development instance, deliberately. Promoting to a production
instance puts a Google OAuth consent screen carrying an unverified-application
interstitial in front of a first-time reviewer, which is a worse opening ninety
seconds than a dev-mode strip. The production path is instance promotion plus a
verified OAuth application - configuration, not code. Verification itself is
always on in either mode: the service trusts a signature, never a header.

## 8. Analyst workflow fit

Analysts live in Excel, BI dashboards, and IC memos. The tool meets them there:

- Every answer renders as verdict -> data table -> chart -> assumptions -> sources.
  Tables export to CSV / copy-paste directly into Excel.
- The REST API is the integration: Excel Power Query, a Python notebook, or a BI
  tool can read the same scoring views - no UI required.
- Click-to-ask examples on the landing page reproduce this document's four
  questions in one click.
- Production path: scheduled morning briefs, Slack/Teams bot, SSO - designed, in
  the queue described in Section 11. The delivery mechanism is already sitting in
  the data: the `queries` log stores user, question, answer, tools used and
  latency per row, so a server-rendered email digest or a Slack/Teams push is a
  scheduled read over that table through a transactional provider (Resend, SES)
  rather than new agent work - designed, not built.

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
- IAM posture (GCP): the service runs on a dedicated service account whose only
  grant is `secretAccessor` on its own four secrets - never the default compute
  account. Blast radius of a container compromise: its own secrets, nothing
  else. Deliberately NOT added at this scale: custom roles, IAM conditions,
  VPC Service Controls, and a separate CI deploy identity (Workload Identity
  Federation) - each is a production-path line, not a demo build. Knowing
  where that line sits is the security decision this section documents.

## 10. The complete picture - production data layers

Professional airport underwriting runs on rating-agency scorecards (Moody's
publishes a three-factor US Airport Revenue Bonds methodology). The verified
industry benchmarks our production path targets: cost per enplanement typically
$8-18 at large hubs; debt per enplanement $5-15 common, above $20 highly
leveraged; Fitch coverage bands from 1.0x (BBB) to above 2.0x (AAA); and
non-aeronautical revenue at roughly 37-40% of airport income globally (ACI) -
which is the direct money link to terminal renovation: expanded terminals grow
exactly that revenue line. Our capacity-growth score is the demand half of that
story.

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

None of this is locked to the platform it runs on today: the LangGraph graph
deploys unchanged to Vertex AI Agent Engine, which hosts LangGraph natively, when
a client standardizes on GCP.

## 11. With another week

Designed and deliberately not built inside the window, listed so the line between
what runs and what is planned stays visible: a supervisor plus specialist agent
split (analyst SQL / live-ops FAA and weather), an `/explore` league-table page
with CSV export, an analyst dashboard (Looker Studio on the same views), product
analytics (PostHog), and scheduled data refresh.

Voice is a partial exception worth stating precisely: dictation into the composer
and read-aloud on any answer ship today, both on the browser's Web Speech API, so
the interface is hands-free but still turn-based text underneath. Full
conversational voice-to-voice is the designed step, and it arrives as a managed
real-time layer - ElevenLabs Agents, OpenAI Realtime, or Gemini Live - speaking
to the same `/chat` backend, leaving the agent, its tools, and auth unchanged.

These come in the order an investment committee would pay for them, not in the
order they are fun to build - which is why the financial and demographic layers
in Section 10 sit ahead of every item in this list.
