"""Wallet model."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import String, DateTime, Integer, ForeignKey, LargeBinary, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.session import Base

if TYPE_CHECKING:
    from backend.models.user import User
    from backend.models.bot import Bot


class Wallet(Base):
    """Wallet model for platform-managed or delegated wallets."""

    __tablename__ = "wallets"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(100),  # Cognito sub ID
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[str] = mapped_column(String(42), nullable=False)  # Funder/proxy address
    signer_address: Mapped[str] = mapped_column(String(42), nullable=False)  # EOA signer
    wallet_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # platform_managed, delegated
    signature_type: Mapped[int] = mapped_column(Integer, default=1)  # 0=EOA, 1=Magic, 2=browser

    # Encrypted credentials (for platform-managed wallets)
    encrypted_private_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encrypted_dek: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    key_version: Mapped[int] = mapped_column(Integer, default=1)

    # Encrypted CLOB API credentials
    encrypted_api_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encrypted_api_secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encrypted_api_passphrase: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # For delegated wallets
    delegation_tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    delegation_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # HD wallet derivation path index (for platform-managed)
    derivation_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="active")  # active, suspended, revoked

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
    user: Mapped["User"] = relationship("User", back_populates="wallets")
    bots: Mapped[list["Bot"]] = relationship("Bot", back_populates="wallet")
