"""FastAPI service.

    GET  /health      liveness + which backend, model and data vintage are live
    GET  /freshness   public: is the scheduled refresh (ADR-005) current
    POST /chat        ask a question on a thread; streamed (SSE) or single JSON

Conversation memory is the LangGraph checkpointer keyed by ``thread_id``, so a
follow-up question is just another POST with the same thread id.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from agent import __version__
from agent.auth import ANONYMOUS, Principal, current_principal
from agent.db import build_pool, pool_stats
from agent.graph import build_graph
from agent.logging_config import bind, clear, configure, get_logger
from agent.observability import Tracing, build_tracing
from agent.query_log import QueryLog
from agent.repository import AirportRepo, FixtureRepo, PostgresRepo
from agent.settings import Settings, get_settings
from agent.state import merge_assumptions

log = get_logger(__name__)


# --- Wire format ---------------------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = Field(
        default=None, description="Omit to start a new conversation."
    )
    stream: bool = Field(default=True, description="False returns one JSON object.")


class ChatResponse(BaseModel):
    thread_id: str
    answer: str
    assumptions: list[str]
    tools_used: list[str]


@dataclass
class Runtime:
    """Everything built once at boot and shared by every request."""

    settings: Settings
    repo: AirportRepo
    graph: Any
    backend: str
    checkpointer_kind: str
    vintage: dict[str, Any] = field(default_factory=dict)
    tracing: Tracing = field(default_factory=lambda: Tracing(None))
    query_log: QueryLog = field(default_factory=lambda: QueryLog(None))
    queries_ready: bool = False
    write_pool: Any | None = None


# --- Boot ----------------------------------------------------------------


async def _build_repo(s: Settings) -> tuple[AirportRepo, str]:
    if s.effective_backend == "postgres":
        repo = PostgresRepo(
            s.database_dsn or "",
            min_size=s.db_pool_min_size,
            max_size=s.db_pool_max_size,
            statement_timeout_ms=s.db_statement_timeout_ms,
            max_idle_seconds=s.db_pool_max_idle_seconds,
            max_lifetime_seconds=s.db_pool_max_lifetime_seconds,
        )
        await repo.open()
        return repo, "postgres"
    log.warning("no DATABASE_URL - serving fixture data; answers are NOT real analysis")
    return FixtureRepo(), "fixture"


async def _build_write_pool(s: Settings) -> Any | None:
    """One writable pool, shared by the checkpointer and the query log.

    The repository pool cannot be reused: it runs every statement inside
    SET TRANSACTION READ ONLY, which is the guarantee that the analysis path
    cannot mutate the dataset.
    """
    if not s.database_dsn:
        return None
    try:
        pool = build_pool(
            s.database_dsn,
            autocommit=True,
            min_size=0,
            max_size=s.db_write_pool_max_size,
            max_idle_seconds=s.db_pool_max_idle_seconds,
            max_lifetime_seconds=s.db_pool_max_lifetime_seconds,
        )
        await pool.open(wait=True, timeout=20)
        return pool
    except Exception:
        log.exception("write pool unavailable")
        return None


async def _build_checkpointer(s: Settings, pool: Any | None) -> tuple[Any, str]:
    """Postgres-checkpointed threads, with an in-memory fallback so local runs work."""
    from langgraph.checkpoint.memory import MemorySaver

    if pool is None:
        return MemorySaver(), "memory"
    try:
        from agent.checkpointer import ResilientAsyncPostgresSaver

        saver = ResilientAsyncPostgresSaver(pool)
        await saver.setup()
        return saver, "postgres"
    except Exception:
        log.exception("PostgresSaver unavailable - falling back to in-memory checkpoints")
        return MemorySaver(), "memory"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure(s.log_level, s.log_json)

    repo, backend = await _build_repo(s)
    write_pool = await _build_write_pool(s)
    checkpointer, ckpt_kind = await _build_checkpointer(s, write_pool)
    graph = build_graph(repo, checkpointer=checkpointer, settings=s)
    tracing = build_tracing(s)

    query_log = QueryLog(write_pool if s.log_queries else None)
    queries_ready = await query_log.ensure_table()

    try:
        vintage = await repo.data_vintage()
    except Exception as exc:
        log.warning("data vintage unavailable", extra={"error": str(exc)})
        vintage = {}

    app.state.rt = Runtime(
        settings=s,
        repo=repo,
        graph=graph,
        backend=backend,
        checkpointer_kind=ckpt_kind,
        vintage=vintage,
        tracing=tracing,
        query_log=query_log,
        queries_ready=queries_ready,
        write_pool=write_pool,
    )
    log.info(
        "service ready",
        extra={
            "backend": backend,
            "checkpointer": ckpt_kind,
            "model": s.agent_model,
            "tracing": tracing.enabled,
            "query_log": queries_ready,
            "version": __version__,
        },
    )
    try:
        yield
    finally:
        tracing.flush()
        await repo.close() if hasattr(repo, "close") else None
        if write_pool is not None:
            await write_pool.close()


app = FastAPI(
    title="Airport Investment Intelligence Agent",
    version=__version__,
    summary="Ask investment questions about US airports; answers are computed in SQL and explained by an LLM.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def get_runtime(request: Request) -> Runtime:
    return request.app.state.rt


# --- Routes --------------------------------------------------------------

#: ADR-005's declared cadence. Cloud Scheduler's actual cron expression is
#: infra config this service cannot poll, so "next scheduled" is estimated
#: from the last recorded run rather than asserted as a live schedule fact -
#: and only once a run has actually happened (see _freshness_body).
REFRESH_CADENCE = "weekly"
REFRESH_INTERVAL = timedelta(days=7)


def _iso(dt: datetime | None) -> str | None:
    """UTC, second precision, ``Z`` suffix - matches every other timestamp this
    service already emits. Never raises: a naive value (should not happen for
    a TIMESTAMPTZ column, but this endpoint must never 500 either way) is
    treated as UTC rather than rejected."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


async def _freshness_body(rt: Runtime) -> dict[str, Any]:
    """ADR-005: is the scheduled refresh current, reported honestly.

    ``last_successful_refresh`` only ever moves for a 'success' or 'no_change'
    run - see ``AirportRepo.refresh_status``. ``last_run_status`` reports the
    newest run as-is, including 'failed': a failed attempt is surfaced next to
    the older-but-good timestamp rather than hidden behind it, because a
    silently stale-but-confident endpoint is the exact defect ADR-005 exists
    to fix. Everything is null and ``last_run_status`` is "unknown" until the
    ledger has produced at least one usable row - a normal pre-launch state,
    never an error.
    """
    try:
        status = await rt.repo.refresh_status()
    except Exception as exc:
        log.warning("refresh status unavailable", extra={"error": str(exc)})
        status = {}

    last_run_started_at = status.get("last_run_started_at")
    return {
        "last_successful_refresh": _iso(status.get("last_successful_at")),
        "last_run_status": status.get("last_run_status") or "unknown",
        "cadence": REFRESH_CADENCE if last_run_started_at else None,
        "next_scheduled": (
            _iso(last_run_started_at + REFRESH_INTERVAL) if last_run_started_at else None
        ),
        "latest_period": status.get("latest_period"),
        "sources": status.get("sources"),
    }


@app.get("/health")
async def health(rt: Runtime = Depends(get_runtime)) -> JSONResponse:
    """Liveness plus the facts needed to trust an answer: backend, model, vintage."""
    try:
        db_ok = await rt.repo.ping()
    except Exception as exc:
        log.warning("health probe failed", extra={"error": str(exc)})
        db_ok = False
    body = {
        "status": "ok" if db_ok else "degraded",
        "version": __version__,
        "data_backend": rt.backend,
        "data_ok": db_ok,
        "checkpointer": rt.checkpointer_kind,
        "model": rt.settings.agent_model,
        "llm_configured": bool(rt.settings.openrouter_key),
        "data_vintage": rt.vintage,
        # ADR-005, additive: data_vintage above is unchanged and already public.
        "last_refresh": await _freshness_body(rt),
        "tracing": rt.tracing.enabled,
        "tracing_environment": rt.tracing.environment if rt.tracing.enabled else None,
        "query_log": rt.queries_ready,
        "pools": {
            "read": rt.repo.stats() if hasattr(rt.repo, "stats") else {},
            "write": pool_stats(rt.write_pool),
        },
        "auth": {
            # Verification is always on when configured; "required" is the switch
            # that decides whether an anonymous caller is still allowed. See auth.py.
            "clerk_verification": rt.settings.clerk_configured,
            "clerk_required": rt.settings.clerk_auth_enabled,
            "issuer": rt.settings.clerk_jwt_issuer,
        },
        "stubs": {},
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)


@app.get("/freshness")
async def freshness(rt: Runtime = Depends(get_runtime)) -> JSONResponse:
    """Public, unauthenticated (ADR-005): whether the scheduled refresh is
    current, verifiable by anyone without asking. Always 200 - degrades to
    nulls, never errors, so a missing ledger or an unreachable database can
    never take this endpoint down."""
    return JSONResponse(await _freshness_body(rt), status_code=200)


@app.get("/")
async def root(rt: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return {
        "service": rt.settings.app_name,
        "version": __version__,
        "endpoints": {
            "health": "GET /health",
            "freshness": "GET /freshness",
            "chat": "POST /chat",
            "docs": "GET /docs",
        },
    }


def _chunk_text(chunk: Any) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return ""


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


#: Shown when the graph completes without producing any prose. Says what happened
#: and what to do; it never invents an analysis.
EMPTY_ANSWER_FALLBACK = (
    "I could not produce an answer for this question - please ask again."
)


def _final_answer(parts: list[str], whole_message: str, thread_id: str) -> str:
    """Never hand back an empty answer.

    A completed run with no prose is always a defect on our side - the thread-wide
    tool-cap bug produced exactly this - and a blank bubble gives the user nothing
    to act on and leaves no signal in the logs. Substitute honest text and log it
    loudly so the next occurrence is findable by thread.
    """
    answer = ("".join(parts) or whole_message).strip()
    if answer:
        return answer
    log.warning("graph produced an empty answer", extra={"thread_id": thread_id})
    return EMPTY_ANSWER_FALLBACK


async def _events(
    rt: Runtime,
    message: str,
    thread_id: str,
    principal: Principal = ANONYMOUS,
    request_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Normalised event stream over the graph run, traced and logged end to end."""
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": rt.tracing.callbacks(),
        "recursion_limit": rt.settings.max_tool_iterations * 2 + 4,
    }
    inputs = {"messages": [HumanMessage(content=message)], "thread_id": thread_id}
    assumptions: list[str] = []
    tools_used: list[str] = []
    answer_parts: list[str] = []
    # Fallback for gateways/models that return a whole message instead of tokens.
    final_message = ""
    started = time.perf_counter()
    failure: str | None = None
    answer = ""

    yield {"type": "start", "thread_id": thread_id}
    with rt.tracing.request(
        thread_id=thread_id,
        user_id=principal.user_id,
        question=message,
        tags=[f"model:{rt.settings.agent_model}", f"data:{rt.backend}"],
    ) as span:
        try:
            async with asyncio.timeout(rt.settings.request_timeout_seconds):
                async for event in _graph_events(rt, inputs, config):
                    kind = event.pop("_kind")
                    if kind == "token":
                        answer_parts.append(event["content"])
                    elif kind == "tool_call":
                        tools_used.append(event["name"])
                    elif kind == "final_message":
                        final_message = event["text"] or final_message
                        continue
                    elif kind == "assumptions":
                        assumptions = merge_assumptions(assumptions, event["items"])
                        continue
                    yield event

            answer = _final_answer(answer_parts, final_message, thread_id)
            if assumptions:
                yield {"type": "assumptions", "items": assumptions}
            yield {
                "type": "done",
                "thread_id": thread_id,
                "tools_used": tools_used,
                "answer": answer,
                "assumptions": assumptions,
            }
        except BaseException as exc:  # includes timeouts and client disconnects
            failure = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            # On the error path `done` never ran, so keep whatever prose arrived
            # before the failure rather than pretending the turn completed.
            answer = answer or "".join(answer_parts) or final_message
            span.update(
                output={"answer": answer, "assumptions": assumptions},
                metadata={"tools_used": tools_used, "data_backend": rt.backend},
            )
            await rt.query_log.record(
                thread_id=thread_id,
                request_id=request_id,
                user_id=principal.user_id,
                user_email=principal.email,
                question=message,
                answer=answer or None,
                tools_used=tools_used,
                latency_ms=int((time.perf_counter() - started) * 1000),
                model=rt.settings.agent_model,
                data_backend=rt.backend,
                trace_id=rt.tracing.trace_id(),
                error=failure,
            )


async def _graph_events(
    rt: Runtime, inputs: dict[str, Any], config: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    """Raw graph stream translated into wire events, tagged with a ``_kind``.

    Split out so the tracing and logging wrapper above stays readable.
    """
    async for mode, payload in rt.graph.astream(
        inputs, config, stream_mode=["updates", "messages"]
    ):
        if mode == "messages":
            chunk, meta = payload
            if meta.get("langgraph_node") == "agent":
                text = _chunk_text(chunk)
                if text:
                    yield {"_kind": "token", "type": "token", "content": text}
            continue

        for node, update in (payload or {}).items():
            if node == "agent":
                for m in update.get("messages", []):
                    calls = getattr(m, "tool_calls", None) or []
                    for call in calls:
                        yield {
                            "_kind": "tool_call",
                            "type": "tool_call",
                            "name": call["name"],
                            "args": call.get("args", {}),
                        }
                    if not calls:
                        yield {"_kind": "final_message", "text": _chunk_text(m)}
            elif node == "tools":
                for m in update.get("messages", []):
                    artifact = getattr(m, "artifact", None) or {}
                    yield {
                        "_kind": "tool_result",
                        "type": "tool_result",
                        "name": getattr(m, "name", None),
                        "ok": bool(artifact.get("ok")),
                        "error": artifact.get("error"),
                    }
                yield {"_kind": "assumptions", "items": update.get("assumptions", [])}


@app.post("/chat")
async def chat(
    body: ChatRequest,
    rt: Runtime = Depends(get_runtime),
    principal: Principal = Depends(current_principal),
):
    """Ask a question. Same ``thread_id`` continues the conversation."""
    thread_id = body.thread_id or str(uuid.uuid4())
    request_id = str(uuid.uuid4())[:8]
    bind(request_id=request_id, thread_id=thread_id, user_id=principal.user_id)
    log.info("chat request", extra={"chars": len(body.message), "stream": body.stream})

    if not rt.settings.openrouter_key:
        clear()
        return JSONResponse(
            {"error": "OPENROUTER_API_KEY is not configured; the agent cannot run."},
            status_code=503,
        )

    if body.stream:

        async def gen() -> AsyncIterator[str]:
            try:
                async for event in _events(
                    rt, body.message, thread_id, principal, request_id
                ):
                    yield _sse(event)
            except asyncio.TimeoutError:
                log.warning("request timed out")
                yield _sse({"type": "error", "message": "the request timed out"})
            except Exception as exc:
                log.exception("chat stream failed")
                yield _sse({"type": "error", "message": f"agent error: {exc}"})
            finally:
                clear()

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    try:
        final: dict[str, Any] = {}
        async for event in _events(rt, body.message, thread_id, principal, request_id):
            if event["type"] == "done":
                final = event
        return ChatResponse(
            thread_id=thread_id,
            answer=final.get("answer", ""),
            assumptions=final.get("assumptions", []),
            tools_used=final.get("tools_used", []),
        )
    except asyncio.TimeoutError:
        return JSONResponse({"error": "the request timed out"}, status_code=504)
    except Exception as exc:
        log.exception("chat failed")
        return JSONResponse({"error": f"agent error: {exc}"}, status_code=500)
    finally:
        clear()


__all__ = ["app", "ChatRequest", "ChatResponse", "Runtime"]
