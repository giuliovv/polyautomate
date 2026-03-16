"""Signer service configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class SignerSettings(BaseSettings):
    """Signer service settings."""

    # Service
    host: str = "0.0.0.0"
    port: int = 8001
    debug: bool = False

    # Database (read-only access to wallet data)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/botplatform"

    # AWS KMS
    aws_region: str = "us-east-1"
    kms_key_id: str = ""

    # Backend authentication
    backend_shared_secret: str = "CHANGE_ME_IN_PRODUCTION"

    # Polymarket
    polymarket_clob_url: str = "https://clob.polymarket.com"
    polymarket_chain_id: int = 137

    # Rate limiting
    rate_limit_per_wallet_per_minute: int = 30
    rate_limit_per_bot_per_minute: int = 10

    class Config:
        env_file = ".env"
        env_prefix = "SIGNER_"


@lru_cache
def get_signer_settings() -> SignerSettings:
    """Get cached signer settings."""
    return SignerSettings()
