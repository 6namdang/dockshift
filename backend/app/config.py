"""Application settings, loaded from environment variables and ``backend/.env``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App -----------------------------------------------------------------
    app_name: str = "Dockshift API"
    environment: str = "development"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- Literature search: credentials ------------------------------------------
    # Sent to NCBI / Europe PMC as a polite contact address (recommended by both).
    contact_email: str | None = None
    # Optional. Raises the NCBI E-utilities limit from 3 to 10 requests/second.
    ncbi_api_key: str | None = None

    # --- LLM (candidate proposal) --------------------------------------------------
    # Any OpenAI-compatible endpoint. Without a key the candidate step reports that it
    # is not configured; everything else keeps working.
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    # OPENAI_MODEL is accepted as well, since that is the more familiar name.
    llm_model: str = Field(
        "gpt-4o-mini", validation_alias=AliasChoices("llm_model", "openai_model")
    )
    llm_timeout_seconds: float = 90.0
    # How many papers are shown to the model, and how much of each abstract.
    llm_max_documents: int = 24
    llm_max_abstract_chars: int = 700

    # --- Literature search: behaviour ----------------------------------------------
    http_timeout_seconds: float = 20.0
    http_max_retries: int = 2
    default_max_results_per_source: int = 10
    max_results_per_source_limit: int = 50

    # Full text is fetched automatically only for documents whose lexical
    # confidence score (0-1) is at or above this threshold.
    fulltext_confidence_threshold: float = Field(0.75, ge=0.0, le=1.0)
    # At most this many documents get full text per search call.
    fulltext_max_docs: int = 3
    # Full text is truncated to this many characters to protect the agent's context.
    fulltext_max_chars: int = 20_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
