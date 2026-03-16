"""Cognito JWT validation service."""

import time
from typing import Any

import httpx
from jose import jwt, jwk, JWTError
from jose.utils import base64url_decode

from backend.config import get_settings

settings = get_settings()

# Cache for JWKS keys
_jwks_cache: dict[str, Any] | None = None
_jwks_cache_time: float = 0
_JWKS_CACHE_TTL = 3600  # 1 hour


async def get_jwks() -> dict[str, Any]:
    """Fetch and cache Cognito JWKS."""
    global _jwks_cache, _jwks_cache_time

    now = time.time()
    if _jwks_cache and (now - _jwks_cache_time) < _JWKS_CACHE_TTL:
        return _jwks_cache

    async with httpx.AsyncClient() as client:
        response = await client.get(settings.cognito_jwks_url)
        response.raise_for_status()
        _jwks_cache = response.json()
        _jwks_cache_time = now
        return _jwks_cache


def get_signing_key(token: str, jwks: dict[str, Any]) -> dict[str, Any] | None:
    """Get the signing key for a token from JWKS."""
    try:
        headers = jwt.get_unverified_headers(token)
        kid = headers.get("kid")
        if not kid:
            return None

        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None
    except JWTError:
        return None


async def validate_cognito_token(token: str) -> dict[str, Any] | None:
    """Validate a Cognito JWT token.

    Returns the token claims if valid, None otherwise.
    """
    if not settings.cognito_user_pool_id or not settings.cognito_app_client_id:
        # Cognito not configured - for local dev, return mock claims
        if settings.environment == "development":
            return _mock_token_claims(token)
        return None

    try:
        # Get JWKS
        jwks = await get_jwks()

        # Get signing key
        signing_key = get_signing_key(token, jwks)
        if not signing_key:
            return None

        # Verify token
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=settings.cognito_app_client_id,
            issuer=settings.cognito_issuer,
        )

        # Verify token_use claim (should be "access" or "id")
        token_use = claims.get("token_use")
        if token_use not in ("access", "id"):
            return None

        return claims

    except JWTError:
        return None
    except Exception:
        return None


def _mock_token_claims(token: str) -> dict[str, Any] | None:
    """Mock token validation for local development without Cognito.

    Accepts any token in format: dev-<user_id> or just returns test user.
    """
    if token.startswith("dev-"):
        user_id = token[4:]
        return {
            "sub": user_id,
            "email": f"{user_id}@dev.local",
            "token_use": "access",
        }
    # For any other token in dev mode, return a test user
    return {
        "sub": "dev-user-123",
        "email": "dev@dev.local",
        "token_use": "access",
    }


def get_user_sub(claims: dict[str, Any]) -> str:
    """Extract user sub (unique ID) from token claims."""
    return claims.get("sub", "")


def get_user_email(claims: dict[str, Any]) -> str | None:
    """Extract user email from token claims."""
    return claims.get("email")
