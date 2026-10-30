"""Application settings, loaded from environment variables (prefix ``APP_``) or a .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./shortener.db"
    base_url: str = "http://localhost:8000"

    code_length: int = 7
    code_max_attempts: int = 5

    max_url_length: int = 2048

    # Rate limit on link creation: N requests per window per client IP.
    rate_limit_requests: int = 30
    rate_limit_window_seconds: int = 60

    # In-process lookup cache for redirects.
    cache_ttl_seconds: int = 300
    cache_max_entries: int = 10_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
