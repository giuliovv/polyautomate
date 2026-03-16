"""User model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.session import Base

if TYPE_CHECKING:
    from backend.models.wallet import Wallet
    from backend.models.bot import Bot


class User(Base):
    """User account model.

    Users are identified by their Cognito 'sub' claim.
    Authentication is handled entirely by AWS Cognito.
    """

    __tablename__ = "users"

    # Cognito sub (unique user identifier from Cognito)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)

    # Email from Cognito (synced on login)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    # Optional display name
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    wallets: Mapped[list["Wallet"]] = relationship("Wallet", back_populates="user")
    bots: Mapped[list["Bot"]] = relationship("Bot", back_populates="user")
