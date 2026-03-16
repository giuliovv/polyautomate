"""Shared dependencies for dependency injection."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_db
from backend.models.user import User
from backend.services.cognito_auth import validate_cognito_token, get_user_sub, get_user_email
from backend.services.user_service import UserService

security = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Get the current authenticated user from Cognito JWT token.

    If the user doesn't exist in our database yet, create them.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = credentials.credentials
    claims = await validate_cognito_token(token)

    if claims is None:
        raise credentials_exception

    cognito_sub = get_user_sub(claims)
    if not cognito_sub:
        raise credentials_exception

    user_service = UserService(db)
    user = await user_service.get_by_id(cognito_sub)

    # If user doesn't exist, create them (first login)
    if user is None:
        email = get_user_email(claims)
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email not found in token",
            )
        user = await user_service.create_from_cognito(cognito_sub, email)

    return user


# Type alias for dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
