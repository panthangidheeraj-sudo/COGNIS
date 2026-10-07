"""Central configuration. Every limit lives here (no magic numbers in modules).

Values come from environment variables (or a local ``.env``). Optional API keys
are never required to start: a connector without credentials reports
``not_configured`` and the rest of the system degrades gracefully.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def default_data_dir() -> Path:
    """``backend/data``, except on Windows inside a OneDrive-synced folder, where SQLite files are kept in
    ``%LOCALAPPDATA%\\cognis`` (cloud sync locks and corrupts live database files). ``DATA_DIR`` overrides both."""
    local = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local and "onedrive" in str(BACKEND_ROOT).lower():
        return Path(local) / "cognis"
    return BACKEND_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BACKEND_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore", case_sensitive=False,
                                      env_ignore_empty=True)

    # ---- mode -------------------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    run_mode: Literal["development", "competition"] = "development"
    version: str = "1.0.0"

    # ---- storage ----------------------------------------------------------
    data_dir: Path = default_data_dir()
    database_path: Path | None = None  # defaults to data_dir/app.sqlite

    # ---- HTTP identity / politeness --------------------------------------
    contact_email: str = "submit@builderr.ai"
    user_agent: str = "COGNIS-Signalpost/1.0 (company research agent; respects robots.txt)"
    http_timeout_seconds: float = 15.0
    http_connect_timeout_seconds: float = 6.0
    max_fetch_bytes: int = 2_500_000
    max_pdf_bytes: int = 12_000_000
    max_redirects: int = 5
    retry_attempts: int = 2
    retry_base_delay_seconds: float = 0.6
    retry_max_delay_seconds: float = 6.0
    host_concurrency: int = 2
    brreg_concurrency: int = 6
    brreg_account_copies_min_interval_seconds: float = 2.1  # ~30 starts/min allowance
    respect_robots: bool = True

    # ---- cache ------------------------------------------------------------
    cache_enabled: bool = True
    cache_ttl_registry_seconds: int = 6 * 3600
    cache_ttl_web_seconds: int = 24 * 3600
    cache_ttl_search_seconds: int = 24 * 3600

    # ---- run budgets (hard limits) ---------------------------------------
    max_run_seconds: float = 2700.0
    max_requests: int = 2000
    max_external_cost_usd: float = 10.0
    budget_headroom: float = 0.9  # optional enrichment stops at this fraction of a limit
    finalize_reserve_seconds: float = 45.0
    max_concurrency: int = 8

    # ---- per-company budgets ---------------------------------------------
    per_company_max_seconds: float = 120.0
    per_company_max_requests: int = 30
    max_searches_per_company: int = 3
    max_pages_per_site: int = 8
    max_llm_calls_per_company: int = 4
    max_jobs_per_company: int = 50
    max_research_rounds: int = 3

    # ---- LLM --------------------------------------------------------------
    llm_provider: Literal["none", "groq", "openai_compatible", "fake"] = "none"
    groq_api_key: str | None = None
    groq_model: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = 30.0
    llm_min_interval_seconds: float = 0.0  # spacing between LLM calls (e.g. 2.0 for a 30 requests/minute plan)
    llm_max_output_tokens: int = 900
    llm_reasoning_effort: str | None = None  # low | medium | high | none; default is chosen per model (gpt-oss: low, qwen3: none)
    llm_cost_per_1k_input_usd: float = 0.0005
    llm_cost_per_1k_output_usd: float = 0.0008

    # ---- search -----------------------------------------------------------
    search_provider: Literal["none", "tavily"] = "tavily"
    tavily_api_key: str | None = None
    # Free plan: 1,000 credits/month at no cost (a basic search = 1 credit). Pay-as-you-go is about USD 0.008 per credit.
    tavily_cost_per_request_usd: float = 0.0

    # ---- optional credentialed sources -----------------------------------
    proff_api_key: str | None = None
    doffin_api_key: str | None = None
    patentstyret_api_key: str | None = None
    nav_feed_token: str | None = None

    # ---- connector switches ----------------------------------------------
    enable_website: bool = True
    enable_search: bool = True
    enable_geocoding: bool = True
    enable_norid: bool = True
    enable_jobs: bool = True
    enable_group_structure: bool = True
    enable_financial_history: bool = True
    enable_linkedin: bool = False  # no permitted automated access; company-linked profiles only
    enable_proff: bool = False
    enable_doffin: bool = False
    enable_patentstyret: bool = False
    enable_nav_jobs: bool = False
    enable_industry_registries: bool = False

    # ---- API server -------------------------------------------------------
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    public_base_url: str = ""  # optional absolute base for export URLs
    enable_debug_endpoints: bool = True

    # ---- derived ----------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.database_path or (self.data_dir / "app.sqlite")

    @property
    def competition(self) -> bool:
        return self.run_mode == "competition"

    @property
    def http_user_agent(self) -> str:
        return f"{self.user_agent} contact:{self.contact_email}"

    @property
    def llm_enabled(self) -> bool:
        if self.llm_provider == "fake":
            return True
        if self.llm_provider == "groq":
            return bool(self.groq_api_key and self.groq_model)
        if self.llm_provider == "openai_compatible":
            return bool(self.llm_base_url and self.llm_model)
        return False

    @property
    def search_enabled(self) -> bool:
        return self.enable_search and self.search_provider == "tavily" and bool(self.tavily_api_key)

    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def limits_summary(self) -> dict[str, float | int]:
        return {
            "max_run_seconds": self.max_run_seconds,
            "max_requests": self.max_requests,
            "max_external_cost_usd": self.max_external_cost_usd,
            "per_company_max_seconds": self.per_company_max_seconds,
            "per_company_max_requests": self.per_company_max_requests,
            "max_searches_per_company": self.max_searches_per_company,
            "max_pages_per_site": self.max_pages_per_site,
            "max_llm_calls_per_company": self.max_llm_calls_per_company,
        }


_override: Settings | None = None


@lru_cache(maxsize=1)
def _cached() -> Settings:
    return Settings()


def get_settings() -> Settings:
    return _override or _cached()


def override_settings(settings: Settings | None) -> None:
    """Test/CLI hook: replace the process-wide settings object."""
    global _override
    _override = settings


class ConfigurationError(RuntimeError):
    """Raised at startup when configuration is internally inconsistent."""


def validate_configuration(settings: Settings) -> list[str]:
    """Return human-readable warnings; raise for configurations that cannot work.

    Missing optional keys are warnings, never crashes (the system degrades).
    """
    warnings: list[str] = []
    if settings.llm_provider == "groq" and not settings.groq_api_key:
        warnings.append("LLM_PROVIDER=groq but GROQ_API_KEY is not set — LLM steps are skipped (deterministic fallbacks are used).")
    if settings.llm_provider == "groq" and settings.groq_api_key and not settings.groq_model:
        raise ConfigurationError("GROQ_API_KEY is set but GROQ_MODEL is empty. Add a line such as GROQ_MODEL=llama-3.3-70b-versatile to .env (any model your Groq account may use; see https://console.groq.com/docs/models).")
    if settings.llm_provider == "openai_compatible" and not (settings.llm_base_url and settings.llm_model):
        raise ConfigurationError("LLM_PROVIDER=openai_compatible requires LLM_BASE_URL and LLM_MODEL.")
    if settings.enable_search and settings.search_provider == "tavily" and not settings.tavily_api_key:
        warnings.append("TAVILY_API_KEY is not set — web discovery is disabled (registry and registry-linked websites still work).")
    if settings.tavily_api_key and not settings.tavily_api_key.startswith("tvly-"):
        warnings.append("TAVILY_API_KEY does not start with 'tvly-' — check that you copied the whole key from the Tavily dashboard.")
    if settings.max_requests <= 0 or settings.max_run_seconds <= 0:
        raise ConfigurationError("MAX_REQUESTS and MAX_RUN_SECONDS must be positive.")
    if settings.finalize_reserve_seconds >= settings.max_run_seconds:
        raise ConfigurationError("FINALIZE_RESERVE_SECONDS must be smaller than MAX_RUN_SECONDS.")
    for name in ("proff", "doffin", "patentstyret"):
        if getattr(settings, f"enable_{name}") and not getattr(settings, f"{name}_api_key"):
            warnings.append(f"ENABLE_{name.upper()}=true but {name.upper()}_API_KEY is missing — the connector reports not_configured.")
    return warnings

