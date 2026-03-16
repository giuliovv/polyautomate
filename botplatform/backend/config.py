"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    # App
    app_name: str = "Bot Platform"
    debug: bool = False
    environment: str = "development"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/botplatform"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # AWS Cognito
    aws_region: str = "us-east-1"
    cognito_user_pool_id: str = ""  # e.g., us-east-1_xxxxxxxxx
    cognito_app_client_id: str = ""  # App client ID from Cognito

    # AWS KMS (for wallet encryption)
    kms_key_id: str = ""  # KMS key ARN for envelope encryption

    # Signer service
    signer_url: str = "http://signer:8001"
    signer_shared_secret: str = "CHANGE_ME_IN_PRODUCTION"

    # Polymarket
    polymarket_clob_url: str = "https://clob.polymarket.com"

    # Rate limiting
    rate_limit_requests_per_minute: int = 60

    @property
    def cognito_issuer(self) -> str:
        """Get Cognito issuer URL."""
        return f"https://cognito-idp.{self.aws_region}.amazonaws.com/{self.cognito_user_pool_id}"

    @property
    def cognito_jwks_url(self) -> str:
        """Get Cognito JWKS URL."""
        return f"{self.cognito_issuer}/.well-known/jwks.json"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
