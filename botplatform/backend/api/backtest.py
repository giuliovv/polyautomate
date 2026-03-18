"""Backtest API endpoints."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from backend.dependencies import CurrentUser
from backend.services.backtest_service import (
    BacktestRequest as BacktestRequestInternal,
    BacktestResultData,
    BacktestStatus,
    BacktestTradeResult,
    get_backtest_service,
)

router = APIRouter()


class BacktestRequest(BaseModel):
    """Request to run a backtest."""
    strategy: str
    market_id: str
    token_label: str = "YES"
    start_date: str
    end_date: str
    resolution: str = "1h"
    stop_loss: float = 0.05
    take_profit: float = 0.10
    hold_periods: int = 24
    position_size: float = 100.0
    strategy_params: dict[str, Any] | None = None


class BacktestInitResponse(BaseModel):
    """Response when starting a backtest."""
    backtest_id: str
    status: str


class BacktestTradeResponse(BaseModel):
    """Single trade in backtest results."""
    entry_timestamp: str
    exit_timestamp: str | None
    direction: str
    entry_price: float
    exit_price: float | None
    pnl: float | None
    exit_reason: str | None


class BacktestResultResponse(BaseModel):
    """Complete backtest result."""
    backtest_id: str
    status: str
    strategy_name: str
    market_id: str
    token_label: str
    resolution: str

    n_trades: int | None = None
    win_rate: float | None = None
    win_rate_ci_low: float | None = None
    win_rate_ci_high: float | None = None
    total_pnl: float | None = None
    avg_pnl: float | None = None
    max_drawdown: float | None = None
    sharpe_ratio: float | None = None
    exit_reason_breakdown: dict[str, int] | None = None
    trades: list[BacktestTradeResponse] | None = None
    equity_curve: list[dict] | None = None

    error_message: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None

    class Config:
        from_attributes = True


class StrategyInfo(BaseModel):
    """Strategy information."""
    id: str
    name: str
    description: str


@router.get("/strategies", response_model=list[StrategyInfo])
async def list_strategies() -> list[StrategyInfo]:
    """Get list of available backtest strategies."""
    service = get_backtest_service()
    strategies = service.get_available_strategies()
    return [StrategyInfo(**s) for s in strategies]


@router.post("/run", response_model=BacktestInitResponse)
async def run_backtest(
    request: BacktestRequest,
    user: CurrentUser,
) -> BacktestInitResponse:
    """
    Start a backtest run.

    Returns immediately with a backtest ID. Poll the result endpoint for status.
    """
    service = get_backtest_service()

    # Convert to internal request
    internal_request = BacktestRequestInternal(
        strategy=request.strategy,
        market_id=request.market_id,
        token_label=request.token_label,
        start_date=request.start_date,
        end_date=request.end_date,
        resolution=request.resolution,
        stop_loss=request.stop_loss,
        take_profit=request.take_profit,
        hold_periods=request.hold_periods,
        position_size=request.position_size,
        strategy_params=request.strategy_params,
    )

    backtest_id = await service.run_backtest(internal_request, user.id)
    result = service.get_backtest(backtest_id)

    return BacktestInitResponse(
        backtest_id=backtest_id,
        status=result.status.value if result else "unknown",
    )


@router.get("/{backtest_id}", response_model=BacktestResultResponse)
async def get_backtest(
    backtest_id: str,
    user: CurrentUser,
) -> BacktestResultResponse:
    """Get backtest result by ID."""
    service = get_backtest_service()
    result = service.get_backtest(backtest_id)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backtest not found",
        )

    trades = None
    if result.trades:
        trades = [
            BacktestTradeResponse(
                entry_timestamp=t.entry_timestamp,
                exit_timestamp=t.exit_timestamp,
                direction=t.direction,
                entry_price=t.entry_price,
                exit_price=t.exit_price,
                pnl=t.pnl,
                exit_reason=t.exit_reason,
            )
            for t in result.trades
        ]

    return BacktestResultResponse(
        backtest_id=result.backtest_id,
        status=result.status.value,
        strategy_name=result.strategy_name,
        market_id=result.market_id,
        token_label=result.token_label,
        resolution=result.resolution,
        n_trades=result.n_trades,
        win_rate=result.win_rate,
        win_rate_ci_low=result.win_rate_ci_low,
        win_rate_ci_high=result.win_rate_ci_high,
        total_pnl=result.total_pnl,
        avg_pnl=result.avg_pnl,
        max_drawdown=result.max_drawdown,
        sharpe_ratio=result.sharpe_ratio,
        exit_reason_breakdown=result.exit_reason_breakdown,
        trades=trades,
        equity_curve=result.equity_curve,
        error_message=result.error_message,
        created_at=result.created_at,
        completed_at=result.completed_at,
    )


@router.get("", response_model=list[BacktestResultResponse])
async def list_backtests(
    user: CurrentUser,
) -> list[BacktestResultResponse]:
    """List recent backtests."""
    service = get_backtest_service()
    results = service.list_backtests(user.id)

    return [
        BacktestResultResponse(
            backtest_id=r.backtest_id,
            status=r.status.value,
            strategy_name=r.strategy_name,
            market_id=r.market_id,
            token_label=r.token_label,
            resolution=r.resolution,
            n_trades=r.n_trades,
            win_rate=r.win_rate,
            total_pnl=r.total_pnl,
            created_at=r.created_at,
            completed_at=r.completed_at,
            error_message=r.error_message,
        )
        for r in results
    ]
