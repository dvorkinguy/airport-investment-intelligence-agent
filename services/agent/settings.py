"""Typed application settings.

Every value comes from the environment or the repo-root ``.env``. Nothing is
hardcoded, nothing secret is ever written to logs or to the response body.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration. See ``.env.example`` for the template."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM gateway (OpenRouter is OpenAI-compatible) ---
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    agent_model: str = "openai/gpt-4o-mini"
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2

    # --- Data plane ---
    database_url: SecretStr | None = None
    db_statement_timeout_ms: int = 15_000
    db_pool_min_size: int = 1
    db_pool_max_size: int = 5

    # Which repository backs the tools. ``auto`` = postgres when DATABASE_URL is
    # set, fixtures otherwise (keeps tests/evals runnable with no database).
    repo_backend: Literal["auto", "postgres", "fixture"] = "auto"

    # --- Agent behaviour ---
    max_tool_iterations: int = 8
    request_timeout_seconds: float = 180.0

    # --- Service ---
    app_name: str = "airport-intel-agent"
    log_level: str = "INFO"
    log_json: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- Observability ---
    # Tri-state on purpose: unset means "on when keys are present". The .env is
    # owned by the command-center lane, so tracing must not need a new flag there.
    langfuse_enabled: bool | None = None
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_base_url: str | None = None
    langfuse_environment: str = "dev"
    langfuse_debug: bool = False

    # --- Query log ---
    log_queries: bool = True

    # --- Tier 2 stub (see auth.py) ---
    clerk_auth_enabled: bool = False
    clerk_secret_key: SecretStr | None = None
    clerk_jwt_issuer: str | None = None

    # --- Derived helpers -------------------------------------------------
    @property
    def effective_backend(self) -> Literal["postgres", "fixture"]:
        if self.repo_backend != "auto":
            return self.repo_backend
        return "postgres" if self.database_url else "fixture"

    @property
    def database_dsn(self) -> str | None:
        return self.database_url.get_secret_value() if self.database_url else None

    @property
    def openrouter_key(self) -> str | None:
        return self.openrouter_api_key.get_secret_value() if self.openrouter_api_key else None

    @property
    def langfuse_keys(self) -> tuple[str, str] | None:
        if self.langfuse_public_key and self.langfuse_secret_key:
            return (
                self.langfuse_public_key.get_secret_value(),
                self.langfuse_secret_key.get_secret_value(),
            )
        return None

    @property
    def langfuse_url(self) -> str:
        """LANGFUSE_BASE_URL is the v4 name; LANGFUSE_HOST is still in the wild."""
        return self.langfuse_base_url or self.langfuse_host

    @property
    def tracing_enabled(self) -> bool:
        if self.langfuse_enabled is not None:
            return self.langfuse_enabled
        return self.langfuse_keys is not None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
