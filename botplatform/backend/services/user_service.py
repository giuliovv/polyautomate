"""User service."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.user import User


class UserService:
    """Service for user-related operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, user_id: str) -> User | None:
        """Get user by ID (Cognito sub)."""
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """Get user by email."""
        result = await self.db.execute(
            select(User).where(User.email == email.lower())
        )
        return result.scalar_one_or_none()

    async def create_from_cognito(self, cognito_sub: str, email: str) -> User:
        """Create a new user from Cognito claims.

        Called on first login after user signs up in Cognito.
        """
        user = User(
            id=cognito_sub,
            email=email.lower(),
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def update_email(self, user: User, email: str) -> User:
        """Update user email (if changed in Cognito)."""
        user.email = email.lower()
        await self.db.flush()
        await self.db.refresh(user)
        return user
