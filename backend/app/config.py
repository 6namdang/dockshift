"""Application settings, loaded from environment variables and ``backend/.env``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
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

    # --- Literature search: credentials --------------------------------------
    contact_email: str | None = None
    ncbi_api_key: str | None = None
    lens_api_token: str | None = None

    # --- Literature search: behaviour ----------------------------------------
    http_timeout_seconds: float = 20.0
    http_max_retries: int = 2
    default_max_results_per_source: int = 10
    max_results_per_source_limit: int = 50
    fulltext_confidence_threshold: float = Field(0.75, ge=0.0, le=1.0)
    fulltext_max_docs: int = 3
    fulltext_max_chars: int = 20_000

    # --- Structural discovery -------------------------------------------------
    # REST execution and HTTP MCP are independently opt-in. MCP stdio remains local.
    structural_rest_enabled: bool = False
    structural_api_token: SecretStr | None = None
    mcp_http_enabled: bool = False
    mcp_http_token: SecretStr | None = None
    structural_max_concurrent_jobs: int = Field(1, ge=1, le=8)

    # Runtime output and caller-provided scientific input are separate roots.
    # Relative paths are resolved beneath backend/.
    structural_artifact_root: Path = Path(".dockshift-runs")
    structural_input_root: Path = Path(".dockshift-inputs")
    structural_command_timeout_seconds: float = Field(1_800.0, gt=0, le=86_400)
    structural_log_max_bytes: int = Field(10_000_000, ge=65_536, le=100_000_000)

    tmalign_executable: str = "TMalign"
    fpocket_executable: str = "fpocket"
    vina_executable: str = "vina"
    obabel_executable: str = "obabel"
    gromacs_executable: str = "gmx"

    # AlphaFold 3 is optional and external. All four values are required to run it.
    alphafold3_python_executable: str = "python"
    alphafold3_script: Path | None = None
    alphafold3_model_dir: Path | None = None
    alphafold3_database_dir: Path | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
