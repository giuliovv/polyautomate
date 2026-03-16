"""Bot model."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import String, DateTime, Integer, Numeric, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.session import Base

if TYPE_CHECKING:
    from backend.models.user import User
    from backend.models.wallet import Wallet
    from backend.models.trade import Trade
    from backend.models.execution import Execution


class Bot(Base):
    """Trading bot configuration model."""

    __tablename__ = "bots"

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
    wallet_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)  # longshot, macd, custom
    config: Mapped[dict] = mapped_column(JSONB, default=dict)  # Strategy-specific params
    schedule: Mapped[str | None] = mapped_column(String(50), nullable=True)  # Cron expression

    # Risk limits
    max_position_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    daily_loss_limit_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    max_actions_per_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="stopped")  # running, stopped, paused
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0)

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
    user: Mapped["User"] = relationship("User", back_populates="bots")
    wallet: Mapped["Wallet"] = relationship("Wallet", back_populates="bots")
    trades: Mapped[list["Trade"]] = relationship("Trade", back_populates="bot")
    executions: Mapped[list["Execution"]] = relationship("Execution", back_populates="bot")
