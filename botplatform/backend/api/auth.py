"""Authentication API endpoints.

Authentication is handled by AWS Cognito. This module provides:
- A health check endpoint for the auth flow
- Session validation (implicitly via the CurrentUser dependency)

Users authenticate directly with Cognito (via Hosted UI or Amplify SDK).
The frontend sends the Cognito JWT token to our API, which validates it.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from backend.dependencies import CurrentUser
from backend.config import get_settings

router = APIRouter()
settings = get_settings()


class AuthConfigResponse(BaseModel):
    """Cognito configuration for frontend."""

    region: str
    user_pool_id: str
    app_client_id: str


class SessionResponse(BaseModel):
    """Current session info."""

    user_id: str
    email: str


@router.get("/config", response_model=AuthConfigResponse)
async def get_auth_config() -> AuthConfigResponse:
    """Get Cognito configuration for frontend.

    The frontend uses this to initialize the Amplify SDK.
    """
    return AuthConfigResponse(
        region=settings.aws_region,
        user_pool_id=settings.cognito_user_pool_id,
        app_client_id=settings.cognito_app_client_id,
    )


@router.get("/session", response_model=SessionResponse)
async def get_session(user: CurrentUser) -> SessionResponse:
    """Validate current session and return user info.

    This endpoint validates the Cognito JWT token and returns
    the current user's info. If the token is invalid, returns 401.
    """
    return SessionResponse(
        user_id=user.id,
        email=user.email,
    )
