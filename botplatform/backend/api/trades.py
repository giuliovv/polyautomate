"""Trades API endpoints."""

from datetime import datetime
from decimal import Decimal
from typing import Sequence

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.dependencies import CurrentUser, DbSession
from backend.models.trade import Trade
from backend.models.bot import Bot

router = APIRouter()


class TradeResponse(BaseModel):
    """Trade response."""

    id: str
    bot_id: str
    market_slug: str
    market_question: str | None
    token_id: str
    side: str
    entry_price: Decimal
    entry_size: Decimal
    entry_notional_usd: Decimal
    entry_timestamp: datetime
    exit_price: Decimal | None
    exit_timestamp: datetime | None
    exit_reason: str | None
    pnl_usd: Decimal | None
    status: str

    class Config:
        from_attributes = True


class TradeSummary(BaseModel):
    """Trade summary statistics."""

    total_trades: int
    open_trades: int
    closed_trades: int
    total_pnl_usd: Decimal
    win_count: int
    loss_count: int
    win_rate: float


async def _get_user_trades(db: AsyncSession, user_id: str) -> Sequence[Trade]:
    """Get all trades for a user."""
    result = await db.execute(
        select(Trade)
        .join(Bot)
        .where(Bot.user_id == user_id)
        .order_by(Trade.entry_timestamp.desc())
    )
    return result.scalars().all()


async def _get_bot_trades(db: AsyncSession, bot_id: str) -> Sequence[Trade]:
    """Get all trades for a bot."""
    result = await db.execute(
        select(Trade)
        .where(Trade.bot_id == bot_id)
        .order_by(Trade.entry_timestamp.desc())
    )
    return result.scalars().all()


@router.get("", response_model=list[TradeResponse])
async def list_all_trades(user: CurrentUser, db: DbSession) -> list[TradeResponse]:
    """List all trades for the current user."""
    trades = await _get_user_trades(db, user.id)
    return [TradeResponse.model_validate(t) for t in trades]


@router.get("/summary", response_model=TradeSummary)
async def get_trade_summary(user: CurrentUser, db: DbSession) -> TradeSummary:
    """Get trade summary statistics."""
    trades = await _get_user_trades(db, user.id)

    total_trades = len(trades)
    open_trades = sum(1 for t in trades if t.status == "open")
    closed_trades = sum(1 for t in trades if t.status == "closed")

    closed_with_pnl = [t for t in trades if t.status == "closed" and t.pnl_usd is not None]
    total_pnl = sum(t.pnl_usd for t in closed_with_pnl)
    win_count = sum(1 for t in closed_with_pnl if t.pnl_usd > 0)
    loss_count = sum(1 for t in closed_with_pnl if t.pnl_usd <= 0)

    win_rate = win_count / len(closed_with_pnl) if closed_with_pnl else 0.0

    return TradeSummary(
        total_trades=total_trades,
        open_trades=open_trades,
        closed_trades=closed_trades,
        total_pnl_usd=total_pnl or Decimal(0),
        win_count=win_count,
        loss_count=loss_count,
        win_rate=round(win_rate, 4),
    )


@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade(
    trade_id: str,
    user: CurrentUser,
    db: DbSession,
) -> TradeResponse:
    """Get trade details."""
    result = await db.execute(
        select(Trade)
        .join(Bot)
        .where(Trade.id == trade_id, Bot.user_id == user.id)
    )
    trade = result.scalar_one_or_none()

    if trade is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trade not found",
        )

    return TradeResponse.model_validate(trade)
