# Agent backend

FastAPI + LangGraph service that answers airport investment questions. Every
number comes from read-only SQL; the model chooses tools and writes the analysis
around what came back.

## Run it

From the repo root (the `.env` template lives there, not in this folder):

```bash
uv sync --extra dev
cp .env.example .env          # fill OPENROUTER_API_KEY (+ DATABASE_URL if you have one)
uv run python -m agent        # http://127.0.0.1:8000
```

Use `python -m agent`, not `uvicorn agent.main:app`. On Windows the event loop has
to be selected before uvicorn creates one - psycopg's async pool refuses the
default `ProactorEventLoop` and **startup aborts** after ~15s with
`psycopg_pool.PoolTimeout: pool initialization incomplete` and "Application
startup failed. Exiting.", with a psycopg WARNING naming `ProactorEventLoop`
just above it. `python -m agent` selects the right loop first
(`agent.configure_event_loop`); no-op on Linux.

With no `DATABASE_URL` the service starts on the JSON fixture backend, so the
whole stack is runnable before the database exists. `/health` always says which
backend answered.

```bash
curl localhost:8000/health
curl -N -X POST localhost:8000/chat \
  -H 'content-type: application/json' \
  -d '{"message":"Which New England airports are the best terminal-expansion candidates?"}'
```

Deployed at `https://airport-agent-532602559497.europe-west3.run.app` (Cloud Run,
europe-west3). Deploy instructions are at the bottom of this file.

## API

| Route | Notes |
|---|---|
| `GET /health` | 200 healthy / 503 degraded. Reports data backend, model, data vintage, whether tracing and the query log are live, and which pieces are still stubs. After ~5 min idle the first probe can return 503 once while Neon wakes a suspended compute; the next call recovers. |
| `POST /chat` | `{message, thread_id?, stream?}`. Same `thread_id` continues a conversation. |
| `GET /docs` | Generated OpenAPI. |

`stream: true` (default) returns Server-Sent Events; `stream: false` returns one
JSON object with `answer`, `assumptions` and `tools_used`.

SSE event types, in order: `start`, then interleaved `tool_call` / `tool_result`
/ `token`, then `assumptions`, then `done` (which repeats the full answer so a
client that missed tokens still renders). `error` replaces `done` on failure.

```
data: {"type":"tool_call","name":"rank_airports","args":{"region":"new_england"}}
data: {"type":"token","content":"Boston Logan"}
data: {"type":"done","thread_id":"...","answer":"...","assumptions":[...]}
```

## Layout

```
services/agent/
  main.py              FastAPI app, SSE streaming, health
  graph.py             LangGraph StateGraph: agent <-> tools
  state.py             typed state: messages, thread_id, assumptions
  tools.py             seven tools: six read-only over SQL, one live
  faa.py               FAA NAS live-status client (cached, fail-soft)
  prompts.py           system prompt (the anti-hallucination guardrail)
  settings.py          pydantic-settings; everything from .env
  logging_config.py    one JSON log line per event, request-scoped context
  auth.py              Clerk session-token verification (JWKS, RS256)
  observability.py     Langfuse tracing
  query_log.py         the `queries` audit table
  repository/          AirportRepo protocol + PostgresRepo + FixtureRepo
  fixtures/            offline JSON dataset (synthetic)
```

## Tools

| Tool | Source | Notes |
|---|---|---|
| `resolve_airport` | `airports` | Place name or code -> IATA + reference facts. |
| `rank_airports` | `v_opportunity_score` | Ranked shortlist with the five score components. |
| `airport_metrics` | `v_airport_metrics` | Traffic, load factor, long-haul share, YoY growth. |
| `compare_airports` | `+ v_congestion` | Two airports side by side. Historical congestion lives here. |
| `unmet_demand_estimate` | `v_unmet_demand_est` | Labelled ESTIMATE, with its three drivers. |
| `investment_context` | T2.5 views (ADR-004) | Carrier concentration (HHI), FAA Form 127 finances, ROI proxy. |
| `faa_live_status` | FAA NAS feed (live) | Ground stops, delay programmes, closures happening now. |

`investment_context` is the financial reality check on a capacity case: traffic
growth says an airport is under pressure, it does not say the airport can pay for
terminal capacity. An airport with negative net revenue per enplanement is
running an operating loss on every passenger. Its three sources are independently
optional - a Tier 1-only database returns "unavailable" per source rather than
failing the question.

`faa_live_status` is the one tool that leaves the dataset, and it is fenced off
in both the prompt and the payload: **live status is today's operations colour,
never long-term investment evidence.** A thunderstorm over Boston this afternoon
says nothing about a terminal expansion case. The client caches the whole
document for five minutes behind a lock (one fetch serves every airport asked
about), times out at five seconds, and degrades to "FAA feed unavailable" rather
than raising - a dead external feed cannot break an answer built on SQL.

## How it holds the line on invented numbers

1. **Tools own the arithmetic.** Scores, growth rates and estimates are computed
   in SQL views. The model never calculates.
2. **Every tool result carries its own assumptions and data vintage**, so the
   answer cites definitions rather than reconstructing them.
3. **Assumptions are typed state**, merged by a reducer as tools return - the API
   hands back the exact set behind an answer instead of parsing it out of prose.
4. **Failures are explicit.** A missing view or unknown airport returns an error
   payload instructing the model to say so. It cannot silently fall back to a
   remembered figure.
5. **Read-only by construction.** Every statement runs inside
   `SET TRANSACTION READ ONLY` under a statement timeout, and every filter is a
   bound parameter - no SQL is assembled from model output.

## Tests and evals

```bash
uv run pytest                      # unit + integration, no network, no database
uv run python -m evals.run_evals   # 4 exam questions + the financial check, live model
uv run python -m evals.run_evals --case q3 --verbose
```

`tests/` runs entirely offline: a scripted chat model drives graph routing, so a
routing regression fails deterministically instead of costing a model call.

`evals/` grades the four target questions with code, not an LLM judge:

| Grader | Fails when |
|---|---|
| `tools` | the answer did not come from the right instrument |
| `numbers` | a tool's figure did not survive into the answer |
| `assumptions` | no assumption line in the prose, or none captured in state |
| `terms` | a required entity or definition is missing |

Evals run against `fixtures/dataset.json`, which is **synthetic**. They prove
routing, number fidelity and assumption discipline - never that a given airport
is a good investment.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | - | Required. Without it `/chat` returns 503. |
| `AGENT_MODEL` | `openai/gpt-4o-mini` | Any OpenRouter tool-calling model. Evals verified green on `openai/gpt-4o-mini` and `anthropic/claude-sonnet-4.5`. |
| `DATABASE_URL` | - | Absent -> fixture backend + in-memory checkpoints. |
| `REPO_BACKEND` | `auto` | Force `postgres` or `fixture`. |
| `MAX_TOOL_ITERATIONS` | `8` | Past the cap the model answers without tools, so a turn always ends in prose. |
| `REQUEST_TIMEOUT_SECONDS` | `180` | Whole-request ceiling. |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | JSON list. A web UI on any other port or domain is blocked by the browser preflight and shows only "backend not connected" - add its origin here. |
| `LOG_JSON` | `true` | `false` for readable local logs. |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | - | Present -> tracing on. |
| `LANGFUSE_HOST` / `LANGFUSE_BASE_URL` | cloud | `BASE_URL` is the v4 name and wins if both are set. |
| `LANGFUSE_ENVIRONMENT` | `dev` | `prod` on Cloud Run, so demo traffic never pollutes prod analytics. |
| `LANGFUSE_ENABLED` | unset | Tri-state: unset follows the keys; set it to force on or off. |
| `LOG_QUERIES` | `true` | `false` disables the `queries` table write. |
| `CLERK_AUTH_ENABLED` | `false` | **Requires** a token; it does not switch verification on. Off = anonymous callers allowed. |
| `CLERK_JWT_ISSUER` | dev instance | Clerk Frontend API origin. Set per environment. |
| `CLERK_JWKS_URL` | derived | Defaults to `<issuer>/.well-known/jwks.json`. |
| `CLERK_SECRET_KEY` | - | Not used to verify tokens (JWKS is public). Held for Clerk Backend API calls. |
| `FAA_STATUS_URL` | FAA NAS feed | Keyless public XML. |
| `FAA_TIMEOUT_SECONDS` / `FAA_CACHE_SECONDS` | `5` / `300` | Feed timeout and in-process cache TTL. |

## Authentication

Identity comes only from a signature the service verified. `Authorization:
Bearer <clerk session token>` is checked against Clerk's JWKS (RS256, issuer and
expiry enforced, `alg: none` rejected by an algorithm allowlist), and `sub` /
`email` are read from the verified claims. Caller-supplied `X-User-Id` /
`X-User-Email` headers are ignored by design - honouring one would let any caller
write any user's name into the audit log.

Two independent switches, which is what lets the public demo and a signed-in user
share one endpoint:

| | No token | Valid token | Bad token |
|---|---|---|---|
| `CLERK_AUTH_ENABLED=false` (default) | anonymous | identified | **401** |
| `CLERK_AUTH_ENABLED=true` | 401 | identified | **401** |

A present-but-invalid token is always a 401. Downgrading a forged token to
"anonymous" would hide exactly the event worth seeing.

Verified end to end against the deployed service on 2026-08-11: a real Clerk
session token minted from the Backend API was accepted, and the verified `sub`
reached both the `queries` row and the Langfuse trace; a request carrying a
spoofed `X-User-Id` logged as `anonymous`. `user_email` stays NULL because
Clerk's default session token carries no email claim - add one via a Clerk JWT
template if the audit log needs it.

## Observability

**Langfuse** (`observability.py`) traces every request against
`langfuse.guydvorkin.com`. One trace per question:

```
chat-request                 agent        input = the question, output = answer + assumptions
  LangGraph                  chain
    agent                    agent
      agent-step             generation   model, tokens, cost
      compare_airports       tool         arguments and returned rows
```

`session_id` is the `thread_id`, so a multi-turn conversation groups under
Sessions. `user_id` is the verified Clerk `sub`, or `anonymous`. The environment tag is
`dev` locally and `prod` on Cloud Run, and tags carry the model and whether the
answer came from Neon or from fixtures.

Tracing switches itself on when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`
are present. Bad keys or an unreachable host disable tracing with a warning -
they never take the service down.

OpenRouter model names carry a provider prefix (`anthropic/claude-sonnet-4.5`)
that Langfuse's built-in price list does not match, so traces reported `$0`
despite correct token counts. Custom model definitions are registered in the
Langfuse project; a question currently costs about $0.03 on Sonnet 4.5.

**Query log** (`query_log.py`) writes one row per answered question to the Neon
`queries` table: thread, request, user, question, answer, tools used, latency,
model, data backend, Langfuse `trace_id`, error. The table is created at startup
with `CREATE TABLE IF NOT EXISTS` - it belongs to the service, not to the
dataset in `db/`. Writes are best-effort: a logging failure can never fail an
answer.

## Deploy (Cloud Run)

Build first, because `--source` cannot pass a `--build-arg` and the image's OCI
revision label is one:

```bash
TAG=$(git rev-parse --short=12 HEAD)
REPO=europe-west3-docker.pkg.dev/airport-intel-agent/airport-agent/airport-agent
gcloud builds submit --project airport-intel-agent --config cloudbuild.yaml \
  --substitutions=_GIT_SHA=$TAG,_IMAGE=$REPO:$TAG

gcloud run deploy airport-agent --project airport-intel-agent \
  --region europe-west3 --image $REPO:$TAG \
  --service-account airport-agent-run@airport-intel-agent.iam.gserviceaccount.com \
  --min-instances 0 --max-instances 2 --timeout 120s --concurrency 20 \
  --allow-unauthenticated \
  --set-env-vars '^@^AGENT_MODEL=anthropic/claude-sonnet-4.5@LANGFUSE_ENVIRONMENT=prod@LANGFUSE_HOST=https://langfuse.guydvorkin.com@LOG_JSON=true@CLERK_JWT_ISSUER=https://busy-viper-68.clerk.accounts.dev@CORS_ORIGINS=["https://airport.guydvorkin.com","http://localhost:3000"]' \
  --set-secrets '^@^OPENROUTER_API_KEY=openrouter-api-key:latest@DATABASE_URL=database-url:latest@LANGFUSE_PUBLIC_KEY=langfuse-public-key:latest@LANGFUSE_SECRET_KEY=langfuse-secret-key:latest@CLERK_SECRET_KEY=clerk-secret-key:latest'
```

The `^@^` prefix sets `@` as the delimiter. It is required, not cosmetic: the
CORS value contains commas, and gcloud's default comma splitting turns the JSON
list into malformed flags.

Secrets live in Secret Manager (`openrouter-api-key`, `database-url`,
`langfuse-public-key`, `langfuse-secret-key`, `clerk-secret-key`) and are mounted
as environment variables. The service runs as a dedicated least-privilege service account with
`secretAccessor` on those five secrets and nothing else - not the default
compute account. `.dockerignore` keeps `.env` and the exam PDF out of the build
context, so neither can reach an image layer.

## Stubbed on purpose

Nothing. Clerk verification was the last stub and landed 2026-08-11; `/health`
reports `stubs: {}`. The web client attaches the Clerk session token as
`Authorization: Bearer` when signed in (`apps/web/src/lib/api.ts`), so a
signed-in user's verified `sub` flows through to the query log and traces;
spoofable `X-User-*` headers are gone from both sides.
