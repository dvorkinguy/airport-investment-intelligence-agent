# Agent backend

FastAPI + LangGraph service that answers airport investment questions. Every
number comes from read-only SQL; the model chooses tools and writes the analysis
around what came back.

## Run it

```bash
uv sync --extra dev
cp .env.example .env          # fill OPENROUTER_API_KEY (+ DATABASE_URL if you have one)
uv run python -m agent        # http://127.0.0.1:8000
```

Use `python -m agent`, not `uvicorn agent.main:app`. On Windows the event loop has
to be selected before uvicorn creates one - psycopg's async driver refuses the
default `ProactorEventLoop` and every database call times out with a pool error
that never names the cause (`agent.configure_event_loop`). No-op on Linux.

With no `DATABASE_URL` the service starts on the JSON fixture backend, so the
whole stack is runnable before the database exists. `/health` always says which
backend answered.

```bash
curl localhost:8000/health
curl -N -X POST localhost:8000/chat \
  -H 'content-type: application/json' \
  -d '{"message":"Which New England airports are the best terminal-expansion candidates?"}'
```

## API

| Route | Notes |
|---|---|
| `GET /health` | 200 healthy / 503 degraded. Reports data backend, model, data vintage, and which Tier 2 pieces are still stubs. |
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
  tools.py             the five read-only tools
  prompts.py           system prompt (the anti-hallucination guardrail)
  settings.py          pydantic-settings; everything from .env
  logging_config.py    one JSON log line per event, request-scoped context
  auth.py              Clerk JWT dependency (Tier 2 stub)
  observability.py     Langfuse callback slot (Tier 2 stub)
  repository/          AirportRepo protocol + PostgresRepo + FixtureRepo
  fixtures/            offline JSON dataset (synthetic)
```

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
uv run python -m evals.run_evals   # the four exam questions, live model, fixture data
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
| `LOG_JSON` | `true` | `false` for readable local logs. |
| `LANGFUSE_ENABLED` / `CLERK_AUTH_ENABLED` | `false` | Turn on once the Tier 2 stubs are implemented. |

## Stubbed on purpose (Tier 2)

| Piece | Where | What is missing |
|---|---|---|
| Langfuse tracing | `observability.build_langfuse_handler` | Callback list, settings and boot warning are wired; only the handler construction raises `NotImplementedError`. |
| Clerk auth | `auth.verify_clerk_jwt` | The dependency is on the routes and returns an anonymous principal; JWKS verification raises `NotImplementedError`. |
| Queries log table | - | Designed in ADR-003; request logs currently carry user, thread and latency. |
