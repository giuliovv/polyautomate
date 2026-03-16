"""Signing audit log model."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.session import Base


class SigningAudit(Base):
    """Audit log for all signing operations."""

    __tablename__ = "signing_audit"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    request_id: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )  # Idempotency key
    wallet_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("wallets.id"),
        nullable=False,
        index=True,
    )
    bot_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("bots.id"),
        nullable=True,
        index=True,
    )

    order_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)  # token_id, side, price, size

    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, success, failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    requester_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
