"""Executor configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class ExecutorSettings(BaseSettings):
    """Executor settings."""

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/botplatform"

    # Signer service
    signer_url: str = "http://signer:8001"
    signer_shared_secret: str = "CHANGE_ME_IN_PRODUCTION"

    # Polymarket data API
    polymarketdata_api_key: str = ""

    # Execution
    poll_interval_seconds: int = 30
    dry_run: bool = True

    # Telegram notifications
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    class Config:
        env_file = ".env"
        env_prefix = "EXECUTOR_"


@lru_cache
def get_executor_settings() -> ExecutorSettings:
    """Get cached executor settings."""
    return ExecutorSettings()
