"""FastAPI service.

    GET  /health   liveness + which backend, model and data vintage are live
    POST /chat     ask a question on a thread; streamed (SSE) or single JSON

Conversation memory is the LangGraph checkpointer keyed by ``thread_id``, so a
follow-up question is just another POST with the same thread id.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from agent import __version__
from agent.auth import Principal, current_principal
from agent.graph import build_graph
from agent.logging_config import bind, clear, configure, get_logger
from agent.observability import get_callbacks, warn_if_unwired
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


# --- Boot ----------------------------------------------------------------


async def _build_repo(s: Settings) -> tuple[AirportRepo, str]:
    if s.effective_backend == "postgres":
        repo = PostgresRepo(
            s.database_dsn or "",
            min_size=s.db_pool_min_size,
            max_size=s.db_pool_max_size,
            statement_timeout_ms=s.db_statement_timeout_ms,
        )
        await repo.open()
        return repo, "postgres"
    log.warning("no DATABASE_URL - serving fixture data; answers are NOT real analysis")
    return FixtureRepo(), "fixture"


async def _build_checkpointer(s: Settings) -> tuple[Any, str, Any]:
    """Postgres-checkpointed threads, with an in-memory fallback so local runs work."""
    from langgraph.checkpoint.memory import MemorySaver

    if not s.database_dsn:
        return MemorySaver(), "memory", None
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(
            conninfo=s.database_dsn,
            min_size=1,
            max_size=3,
            open=False,
            kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": None},
        )
        await pool.open(wait=True, timeout=15)
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        return saver, "postgres", pool
    except Exception:
        log.exception("PostgresSaver unavailable - falling back to in-memory checkpoints")
        return MemorySaver(), "memory", None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure(s.log_level, s.log_json)
    warn_if_unwired(s)

    repo, backend = await _build_repo(s)
    checkpointer, ckpt_kind, ckpt_pool = await _build_checkpointer(s)
    graph = build_graph(repo, checkpointer=checkpointer, settings=s)

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
    )
    log.info(
        "service ready",
        extra={
            "backend": backend,
            "checkpointer": ckpt_kind,
            "model": s.agent_model,
            "version": __version__,
        },
    )
    try:
        yield
    finally:
        await repo.close() if hasattr(repo, "close") else None
        if ckpt_pool is not None:
            await ckpt_pool.close()


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
        "stubs": {
            "langfuse_tracing": not rt.settings.langfuse_enabled,
            "clerk_auth": not rt.settings.clerk_auth_enabled,
        },
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)


@app.get("/")
async def root(rt: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return {
        "service": rt.settings.app_name,
        "version": __version__,
        "endpoints": {"health": "GET /health", "chat": "POST /chat", "docs": "GET /docs"},
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


async def _events(
    rt: Runtime, message: str, thread_id: str
) -> AsyncIterator[dict[str, Any]]:
    """Normalised event stream over the graph run."""
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": get_callbacks(rt.settings),
        "recursion_limit": rt.settings.max_tool_iterations * 2 + 4,
    }
    inputs = {"messages": [HumanMessage(content=message)], "thread_id": thread_id}
    assumptions: list[str] = []
    tools_used: list[str] = []
    answer_parts: list[str] = []
    # Fallback for gateways/models that return a whole message instead of tokens.
    final_message = ""

    yield {"type": "start", "thread_id": thread_id}
    async with asyncio.timeout(rt.settings.request_timeout_seconds):
        async for mode, payload in rt.graph.astream(
            inputs, config, stream_mode=["updates", "messages"]
        ):
            if mode == "messages":
                chunk, meta = payload
                if meta.get("langgraph_node") == "agent":
                    text = _chunk_text(chunk)
                    if text:
                        answer_parts.append(text)
                        yield {"type": "token", "content": text}
            elif mode == "updates":
                for node, update in (payload or {}).items():
                    if node == "agent":
                        for m in update.get("messages", []):
                            calls = getattr(m, "tool_calls", None) or []
                            for call in calls:
                                tools_used.append(call["name"])
                                yield {
                                    "type": "tool_call",
                                    "name": call["name"],
                                    "args": call.get("args", {}),
                                }
                            if not calls:
                                final_message = _chunk_text(m) or final_message
                    elif node == "tools":
                        for m in update.get("messages", []):
                            artifact = getattr(m, "artifact", None) or {}
                            yield {
                                "type": "tool_result",
                                "name": getattr(m, "name", None),
                                "ok": bool(artifact.get("ok")),
                                "error": artifact.get("error"),
                            }
                        assumptions = merge_assumptions(
                            assumptions, update.get("assumptions", [])
                        )

    if assumptions:
        yield {"type": "assumptions", "items": assumptions}
    yield {
        "type": "done",
        "thread_id": thread_id,
        "tools_used": tools_used,
        "answer": "".join(answer_parts) or final_message,
        "assumptions": assumptions,
    }


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
                async for event in _events(rt, body.message, thread_id):
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
        async for event in _events(rt, body.message, thread_id):
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
