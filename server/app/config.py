"""Application configuration, loaded from environment (.env in dev).

Secrets never have defaults that would work in production; they default empty so a
misconfiguration fails loudly rather than silently using a fake value.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    database_url: str = "sqlite:///./dev.db"
    token_encryption_key: str = ""
    app_secret: str = "change-me"

    # Classifier
    classifier: str = "demo"
    price_per_billion_tokens: float = 0.0

    # Jev
    jev_api_key: str = ""
    jev_base_url: str = ""

    # LLM (no defaults — required when classifier == "llm")
    llm_provider: str = ""
    llm_model: str = ""
    llm_api_key: str = ""

    # Gmail
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/google/callback"
    gmail_mode: str = "poll"
    gmail_poll_seconds: int = 60
    pubsub_topic: str = ""
    pubsub_audience: str = ""
    pubsub_service_account: str = ""

    # SMTP
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "triage@example.com"

    # Retention / limits
    retention_days: int = 30
    max_enabled_questions: int = 12

    # Default tenant (single-tenant v0.1)
    default_tenant_name: str = "Default Firm"
    default_template: str = "general"

    # Dashboard
    dashboard_origin: str = "http://localhost:3000"

    # Public "try the triage" demo endpoint (for the marketing site)
    demo_template: str = "general"
    demo_rate_per_hour: int = 20          # per-IP requests/hour
    demo_daily_jev_budget: int = 1000     # max real-Jev classifications/day; then fall back to demo
    demo_shared_secret: str = ""          # if set, callers must send X-Demo-Token
    turnstile_secret: str = ""            # Cloudflare Turnstile secret (optional bot check)


@lru_cache
def get_settings() -> Settings:
    return Settings()
