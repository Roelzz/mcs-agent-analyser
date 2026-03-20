"""Centralised configuration — reads all env vars once at import time."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool_env(key: str) -> bool:
    return os.getenv(key, "").strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    # Logging
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    # Auth
    users_raw: str = field(default_factory=lambda: os.getenv("USERS", ""))

    # API keys
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", "").strip())
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "").strip())

    # Feature flags
    enable_model_comparison: bool = field(default_factory=lambda: _bool_env("MCS_ENABLE_MODEL_COMPARISON"))

    # Custom rules
    custom_rules_file: str = field(default_factory=lambda: os.getenv("CUSTOM_RULES_FILE", ""))

    # Server ports (rxconfig reads these directly, listed here for reference)
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "2009")))
    frontend_port: int = field(default_factory=lambda: int(os.getenv("FRONTEND_PORT", "3000")))
    backend_port: int = field(default_factory=lambda: int(os.getenv("BACKEND_PORT", "8000")))


settings = Settings()
