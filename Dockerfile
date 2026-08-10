# Agent backend image (services/agent). Build context is the repo root:
#   gcloud run deploy airport-agent --source .
#
# Secrets are never baked in - Cloud Run mounts them from Secret Manager as env,
# and .dockerignore keeps .env and the exam PDF out of the context entirely.
#
# Deliberately NO HEALTHCHECK instruction: Cloud Run ignores Docker HEALTHCHECK
# entirely and runs its own startup and liveness probes against the container
# port, so one here would never execute. GET /health is the surface those probes
# and the load balancer actually use.

# --- Builder -------------------------------------------------------------
# python:3.12-slim, digest-pinned so a rebuild months from now resolves the same
# base rather than whatever the tag has moved to.
FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36 AS builder

# ghcr.io/astral-sh/uv:0.11.28, digest-pinned for the same reason. uv lives only
# in this stage; the runtime image never carries the build tooling.
COPY --from=ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies resolve from the committed lockfile into their own layer.
# --no-install-project is the point of this split: without it, editing any file
# under services/ invalidates the layer and reinstalls the whole dependency tree
# on every build.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Source next, so a code change only ever re-runs this much cheaper install.
COPY services/ ./services/
RUN uv sync --frozen --no-dev

# --- Runtime -------------------------------------------------------------
FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36 AS runtime

ARG GIT_SHA=dev
LABEL org.opencontainers.image.source="https://github.com/dvorkinguy/airport-investment-intelligence-agent" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.title="airport-agent" \
      org.opencontainers.image.description="Airport investment intelligence agent - FastAPI + LangGraph over read-only SQL views"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8080 \
    LOG_JSON=true

RUN useradd --create-home --uid 1001 agent

WORKDIR /app

# The project is installed into the venv in editable mode, so the interpreter
# resolves `agent` through /app/services. Both must land at the paths they had
# in the builder or the import breaks.
COPY --from=builder --chown=agent:agent /app/.venv /app/.venv
COPY --from=builder --chown=agent:agent /app/services /app/services

USER agent

EXPOSE 8080

CMD ["python", "-m", "agent"]
