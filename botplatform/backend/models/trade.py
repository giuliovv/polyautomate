"""Trade model."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import String, Text, DateTime, Numeric, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.session import Base

if TYPE_CHECKING:
    from backend.models.bot import Bot
    from backend.models.execution import Execution


class Trade(Base):
    """Trade record model."""

    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    bot_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("executions.id", ondelete="SET NULL"),
        nullable=True,
    )
    wallet_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("wallets.id"),
        nullable=False,
    )

    # Market info
    market_slug: Mapped[str] = mapped_column(String(200), nullable=False)
    market_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_id: Mapped[str] = mapped_column(String(100), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # buy, sell

    # Entry details
    entry_price: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    entry_size: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    entry_notional_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    entry_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entry_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Exit details (filled when trade closes)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    exit_size: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    exit_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exit_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # resolved, stop_loss, manual

    # P&L
    pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open, closed

    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

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
    bot: Mapped["Bot"] = relationship("Bot", back_populates="trades")
    execution: Mapped["Execution | None"] = relationship("Execution", back_populates="trades")
