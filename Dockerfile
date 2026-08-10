# Agent backend image (services/agent). Build context is the repo root so the
# lockfile and package share one layer graph:
#   docker build -t airport-agent .
#
# Secrets are never baked in - Cloud Run mounts them from Secret Manager as env,
# and .dockerignore keeps .env and the exam PDF out of the context entirely.

FROM python:3.12-slim AS base

# uv resolves from the committed lockfile, so the image matches local exactly.
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first: this layer only rebuilds when the lockfile moves.
COPY pyproject.toml uv.lock README.md ./
COPY services/ ./services/
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Cloud Run sends traffic to $PORT and expects the listener on all interfaces.
ENV HOST=0.0.0.0 \
    PORT=8080 \
    LOG_JSON=true

RUN useradd --create-home --uid 1001 agent && chown -R agent:agent /app
USER agent

EXPOSE 8080

CMD ["python", "-m", "agent"]
