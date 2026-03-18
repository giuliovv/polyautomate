"""Analytics API endpoints for dashboard visualizations."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.dependencies import CurrentUser, DbSession
from backend.models.trade import Trade
from backend.models.bot import Bot

router = APIRouter()


class PnlDataPoint(BaseModel):
    """Single data point for P&L time series."""

    date: str
    pnl: Decimal
    cumulative_pnl: Decimal
    trade_count: int


class PnlTimeSeriesResponse(BaseModel):
    """Response for P&L time series endpoint."""

    data: list[PnlDataPoint]
    period: str
    total_pnl: Decimal


class TradeActivityDataPoint(BaseModel):
    """Single data point for trade activity."""

    date: str
    trade_count: int


class TradeActivityResponse(BaseModel):
    """Response for trade activity endpoint."""

    data: list[TradeActivityDataPoint]
    period: str


class BotMetricsResponse(BaseModel):
    """Detailed metrics for a specific bot."""

    bot_id: str
    bot_name: str
    total_trades: int
    open_trades: int
    closed_trades: int
    total_pnl_usd: Decimal
    win_rate: float
    win_count: int
    loss_count: int
    avg_trade_pnl: Decimal
    best_trade_pnl: Decimal | None
    worst_trade_pnl: Decimal | None
    avg_hold_time_hours: float | None
    exit_reason_breakdown: dict[str, int]


@router.get("/pnl-timeseries", response_model=PnlTimeSeriesResponse)
async def get_pnl_timeseries(
    user: CurrentUser,
    db: DbSession,
    bot_id: str | None = Query(None, description="Filter by bot ID"),
    period: Literal["daily", "weekly"] = Query("daily", description="Aggregation period"),
    start_date: date | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: date | None = Query(None, description="End date (YYYY-MM-DD)"),
) -> PnlTimeSeriesResponse:
    """Get P&L time series for equity curve visualization."""

    # Default to last 30 days if no dates specified
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=30)

    # Build base query for closed trades with P&L
    query = (
        select(Trade)
        .join(Bot)
        .where(
            Bot.user_id == user.id,
            Trade.status == "closed",
            Trade.pnl_usd.isnot(None),
            Trade.exit_timestamp.isnot(None),
        )
    )

    if bot_id:
        query = query.where(Trade.bot_id == bot_id)

    # Add date filters
    start_datetime = datetime.combine(start_date, datetime.min.time())
    end_datetime = datetime.combine(end_date, datetime.max.time())
    query = query.where(
        Trade.exit_timestamp >= start_datetime,
        Trade.exit_timestamp <= end_datetime,
    )

    result = await db.execute(query.order_by(Trade.exit_timestamp))
    trades = result.scalars().all()

    # Aggregate by period
    data_points: dict[str, PnlDataPoint] = {}

    for trade in trades:
        if trade.exit_timestamp and trade.pnl_usd is not None:
            if period == "weekly":
                # Start of week (Monday)
                trade_date = trade.exit_timestamp.date()
                week_start = trade_date - timedelta(days=trade_date.weekday())
                date_key = week_start.isoformat()
            else:
                date_key = trade.exit_timestamp.date().isoformat()

            if date_key not in data_points:
                data_points[date_key] = PnlDataPoint(
                    date=date_key,
                    pnl=Decimal(0),
                    cumulative_pnl=Decimal(0),
                    trade_count=0,
                )

            data_points[date_key].pnl += trade.pnl_usd
            data_points[date_key].trade_count += 1

    # Sort by date and compute cumulative P&L
    sorted_points = sorted(data_points.values(), key=lambda x: x.date)
    cumulative = Decimal(0)
    for point in sorted_points:
        cumulative += point.pnl
        point.cumulative_pnl = cumulative

    total_pnl = cumulative if sorted_points else Decimal(0)

    return PnlTimeSeriesResponse(
        data=sorted_points,
        period=period,
        total_pnl=total_pnl,
    )


@router.get("/trade-activity", response_model=TradeActivityResponse)
async def get_trade_activity(
    user: CurrentUser,
    db: DbSession,
    bot_id: str | None = Query(None, description="Filter by bot ID"),
    period: Literal["daily", "weekly"] = Query("daily", description="Aggregation period"),
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
) -> TradeActivityResponse:
    """Get trade activity for bar chart visualization."""

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # Query all trades (entries) in the period
    query = (
        select(Trade)
        .join(Bot)
        .where(
            Bot.user_id == user.id,
            Trade.entry_timestamp >= datetime.combine(start_date, datetime.min.time()),
            Trade.entry_timestamp <= datetime.combine(end_date, datetime.max.time()),
        )
    )

    if bot_id:
        query = query.where(Trade.bot_id == bot_id)

    result = await db.execute(query)
    trades = result.scalars().all()

    # Aggregate by period
    activity: dict[str, int] = {}

    for trade in trades:
        if period == "weekly":
            trade_date = trade.entry_timestamp.date()
            week_start = trade_date - timedelta(days=trade_date.weekday())
            date_key = week_start.isoformat()
        else:
            date_key = trade.entry_timestamp.date().isoformat()

        activity[date_key] = activity.get(date_key, 0) + 1

    # Fill in missing dates with zero
    current = start_date
    while current <= end_date:
        if period == "weekly":
            week_start = current - timedelta(days=current.weekday())
            date_key = week_start.isoformat()
            current += timedelta(days=7)
        else:
            date_key = current.isoformat()
            current += timedelta(days=1)

        if date_key not in activity:
            activity[date_key] = 0

    # Sort and convert to response format
    sorted_activity = sorted(activity.items(), key=lambda x: x[0])
    data_points = [
        TradeActivityDataPoint(date=d, trade_count=c) for d, c in sorted_activity
    ]

    return TradeActivityResponse(
        data=data_points,
        period=period,
    )


@router.get("/bots/{bot_id}/metrics", response_model=BotMetricsResponse)
async def get_bot_metrics(
    bot_id: str,
    user: CurrentUser,
    db: DbSession,
) -> BotMetricsResponse:
    """Get detailed performance metrics for a specific bot."""

    # Verify bot belongs to user
    bot_result = await db.execute(
        select(Bot).where(Bot.id == bot_id, Bot.user_id == user.id)
    )
    bot = bot_result.scalar_one_or_none()

    if bot is None:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bot not found",
        )

    # Get all trades for this bot
    trades_result = await db.execute(
        select(Trade).where(Trade.bot_id == bot_id)
    )
    trades = list(trades_result.scalars().all())

    total_trades = len(trades)
    open_trades = sum(1 for t in trades if t.status == "open")
    closed_trades = sum(1 for t in trades if t.status == "closed")

    # Calculate P&L metrics for closed trades
    closed_with_pnl = [t for t in trades if t.status == "closed" and t.pnl_usd is not None]
    total_pnl = sum(t.pnl_usd for t in closed_with_pnl) if closed_with_pnl else Decimal(0)
    win_count = sum(1 for t in closed_with_pnl if t.pnl_usd > 0)
    loss_count = sum(1 for t in closed_with_pnl if t.pnl_usd <= 0)
    win_rate = win_count / len(closed_with_pnl) if closed_with_pnl else 0.0
    avg_pnl = total_pnl / len(closed_with_pnl) if closed_with_pnl else Decimal(0)

    # Best and worst trades
    pnl_values = [t.pnl_usd for t in closed_with_pnl]
    best_trade = max(pnl_values) if pnl_values else None
    worst_trade = min(pnl_values) if pnl_values else None

    # Average hold time
    hold_times = []
    for t in closed_with_pnl:
        if t.entry_timestamp and t.exit_timestamp:
            delta = t.exit_timestamp - t.entry_timestamp
            hold_times.append(delta.total_seconds() / 3600)  # Convert to hours

    avg_hold_time = sum(hold_times) / len(hold_times) if hold_times else None

    # Exit reason breakdown
    exit_reasons: dict[str, int] = {}
    for t in closed_with_pnl:
        reason = t.exit_reason or "unknown"
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

    return BotMetricsResponse(
        bot_id=bot_id,
        bot_name=bot.name,
        total_trades=total_trades,
        open_trades=open_trades,
        closed_trades=closed_trades,
        total_pnl_usd=total_pnl,
        win_rate=round(win_rate, 4),
        win_count=win_count,
        loss_count=loss_count,
        avg_trade_pnl=avg_pnl,
        best_trade_pnl=best_trade,
        worst_trade_pnl=worst_trade,
        avg_hold_time_hours=round(avg_hold_time, 2) if avg_hold_time else None,
        exit_reason_breakdown=exit_reasons,
    )
