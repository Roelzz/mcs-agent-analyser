"""Centralised configuration — reads all env vars once at import time."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Logging
    log_level: str = "INFO"

    # Auth
    users: str = ""

    # API keys
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # Feature flags
    mcs_enable_model_comparison: bool = False

    # Custom rules
    custom_rules_file: str = ""

    # Server ports (rxconfig reads these directly, listed here for reference)
    port: int = 2009
    frontend_port: int = 3000
    backend_port: int = 8000


settings = Settings()
