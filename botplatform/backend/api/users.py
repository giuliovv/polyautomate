"""User API endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

from backend.dependencies import CurrentUser

router = APIRouter()


class UserResponse(BaseModel):
    """User response."""

    id: str
    email: EmailStr
    auth_provider: str
    web3_address: str | None

    class Config:
        from_attributes = True


@router.get("/me", response_model=UserResponse)
async def get_current_user(user: CurrentUser) -> UserResponse:
    """Get current user profile."""
    return UserResponse(
        id=user.id,
        email=user.email,
        auth_provider=user.auth_provider,
        web3_address=user.web3_address,
    )
