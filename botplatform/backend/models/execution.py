"""Execution and log models."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.session import Base

if TYPE_CHECKING:
    from backend.models.bot import Bot
    from backend.models.trade import Trade


class Execution(Base):
    """Bot execution record model."""

    __tablename__ = "executions"

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

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="running"
    )  # running, completed, failed
    trigger: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled, manual, api

    actions_taken: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    # Relationships
    bot: Mapped["Bot"] = relationship("Bot", back_populates="executions")
    trades: Mapped[list["Trade"]] = relationship("Trade", back_populates="execution")
    logs: Mapped[list["ExecutionLog"]] = relationship("ExecutionLog", back_populates="execution")


class ExecutionLog(Base):
    """Execution log entry model."""

    __tablename__ = "execution_logs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    execution_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    level: Mapped[str] = mapped_column(String(10), default="info")  # debug, info, warn, error
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    # Relationships
    execution: Mapped["Execution"] = relationship("Execution", back_populates="logs")
