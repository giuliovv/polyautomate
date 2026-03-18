"""Backtest service that bridges to the polyautomate backtest engine."""

import asyncio
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

# Try to import polyautomate backtest components (optional dependency)
try:
    from polyautomate.analytics.engine import BacktestEngine
    from polyautomate.analytics.strategies.longshot_bias import LongshotBiasStrategy
    from polyautomate.analytics.strategies.macd_momentum import MACDMomentumStrategy
    from polyautomate.analytics.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
    from polyautomate.analytics.strategies.whale_watcher import WhaleWatcherStrategy
    from polyautomate.clients.polymarketdata import PMDClient
    POLYAUTOMATE_AVAILABLE = True
except ImportError:
    POLYAUTOMATE_AVAILABLE = False
    BacktestEngine = None
    LongshotBiasStrategy = None
    MACDMomentumStrategy = None
    RSIMeanReversionStrategy = None
    WhaleWatcherStrategy = None
    PMDClient = None


class BacktestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class BacktestRequest:
    """Request to run a backtest."""
    strategy: str
    market_id: str
    token_label: str
    start_date: str
    end_date: str
    resolution: str = "1h"
    stop_loss: float = 0.05
    take_profit: float = 0.10
    hold_periods: int = 24
    position_size: float = 100.0
    strategy_params: dict | None = None


@dataclass
class BacktestTradeResult:
    """Single trade from backtest."""
    entry_timestamp: str
    exit_timestamp: str | None
    direction: str
    entry_price: float
    exit_price: float | None
    pnl: float | None
    exit_reason: str | None


@dataclass
class BacktestResultData:
    """Complete backtest result."""
    backtest_id: str
    status: BacktestStatus
    strategy_name: str
    market_id: str
    token_label: str
    resolution: str

    # Results
    n_trades: int | None = None
    win_rate: float | None = None
    win_rate_ci_low: float | None = None
    win_rate_ci_high: float | None = None
    total_pnl: float | None = None
    avg_pnl: float | None = None
    max_drawdown: float | None = None
    sharpe_ratio: float | None = None
    exit_reason_breakdown: dict[str, int] | None = None
    trades: list[BacktestTradeResult] | None = None
    equity_curve: list[dict] | None = None

    error_message: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


# Strategy registry (only available if polyautomate is installed)
STRATEGY_MAP = {}
if POLYAUTOMATE_AVAILABLE:
    STRATEGY_MAP = {
        "longshot": LongshotBiasStrategy,
        "macd": MACDMomentumStrategy,
        "rsi": RSIMeanReversionStrategy,
        "whale": WhaleWatcherStrategy,
    }

# In-memory storage for backtest results (use Redis/DB for production)
_backtest_store: dict[str, BacktestResultData] = {}


class BacktestService:
    """Service for running backtests."""

    def __init__(self):
        self._pmd_client = None
        self._engine = None
        self._engine_available = False

        if not POLYAUTOMATE_AVAILABLE:
            return

        # Get PMD API key from environment
        pmd_api_key = os.environ.get("PMD_API_KEY")
        if not pmd_api_key:
            # Engine not available without API key, but strategies list still works
            return

        self._pmd_client = PMDClient(api_key=pmd_api_key)
        self._engine = BacktestEngine(
            self._pmd_client,
            history_window=48,
            cache_dir=".cache/backtest",
        )
        self._engine_available = True

    def is_available(self) -> bool:
        """Check if backtest engine is available."""
        return POLYAUTOMATE_AVAILABLE

    def is_engine_ready(self) -> bool:
        """Check if backtest engine is fully configured with API key."""
        return self._engine_available

    def get_available_strategies(self) -> list[dict]:
        """Get list of available strategies."""
        return [
            {"id": "longshot", "name": "Longshot Bias", "description": "Identifies undervalued longshot outcomes"},
            {"id": "macd", "name": "MACD Momentum", "description": "Trend-following using MACD crossovers"},
            {"id": "rsi", "name": "RSI Mean Reversion", "description": "Mean reversion using RSI extremes"},
            {"id": "whale", "name": "Whale Watcher", "description": "Tracks large order book imbalances"},
        ]

    async def run_backtest(self, request: BacktestRequest, user_id: str) -> str:
        """
        Start a backtest and return the backtest ID.

        The backtest runs synchronously for now (can be made async with background tasks).
        """
        if not POLYAUTOMATE_AVAILABLE:
            raise RuntimeError(
                "Backtest engine not available. "
                "Install polyautomate package to enable backtesting."
            )

        if not self._engine_available:
            raise RuntimeError(
                "Backtest engine not configured. "
                "Set PMD_API_KEY environment variable to enable backtesting."
            )

        backtest_id = str(uuid.uuid4())

        # Create initial result
        result = BacktestResultData(
            backtest_id=backtest_id,
            status=BacktestStatus.RUNNING,
            strategy_name=request.strategy,
            market_id=request.market_id,
            token_label=request.token_label,
            resolution=request.resolution,
            created_at=datetime.utcnow(),
        )
        _backtest_store[backtest_id] = result

        try:
            # Get strategy class
            if request.strategy not in STRATEGY_MAP:
                raise ValueError(f"Unknown strategy: {request.strategy}")

            strategy_cls = STRATEGY_MAP[request.strategy]
            strategy_params = request.strategy_params or {}
            strategy = strategy_cls(**strategy_params)

            # Run backtest (this is CPU-bound, so run in thread pool)
            loop = asyncio.get_event_loop()
            backtest_result = await loop.run_in_executor(
                None,
                lambda: self._engine.run(
                    strategy=strategy,
                    market_id=request.market_id,
                    token_label=request.token_label,
                    start_ts=request.start_date,
                    end_ts=request.end_date,
                    resolution=request.resolution,
                    stop_loss=request.stop_loss,
                    take_profit=request.take_profit,
                    hold_periods=request.hold_periods,
                    position_size=request.position_size,
                ),
            )

            # Convert results
            trades = []
            equity_curve = []
            cumulative_pnl = 0.0

            for trade in backtest_result.trades:
                pnl = trade.pnl if hasattr(trade, 'pnl') else None
                trades.append(BacktestTradeResult(
                    entry_timestamp=str(trade.signal.timestamp) if trade.signal else "",
                    exit_timestamp=str(trade.exit_timestamp) if trade.exit_timestamp else None,
                    direction=trade.signal.direction if trade.signal else "unknown",
                    entry_price=trade.entry_price,
                    exit_price=trade.exit_price,
                    pnl=pnl,
                    exit_reason=trade.exit_reason,
                ))

                if pnl is not None:
                    cumulative_pnl += pnl
                    equity_curve.append({
                        "timestamp": str(trade.exit_timestamp) if trade.exit_timestamp else "",
                        "cumulative_pnl": cumulative_pnl,
                    })

            # Get win rate confidence interval
            win_rate_ci = backtest_result.win_rate_ci if hasattr(backtest_result, 'win_rate_ci') else None

            # Update result
            result.status = BacktestStatus.COMPLETED
            result.n_trades = backtest_result.n_trades
            result.win_rate = backtest_result.win_rate
            result.win_rate_ci_low = win_rate_ci[0] if win_rate_ci else None
            result.win_rate_ci_high = win_rate_ci[1] if win_rate_ci else None
            result.total_pnl = backtest_result.total_pnl
            result.avg_pnl = backtest_result.avg_pnl
            result.max_drawdown = backtest_result.max_drawdown if hasattr(backtest_result, 'max_drawdown') else None
            result.sharpe_ratio = backtest_result.sharpe_ratio if hasattr(backtest_result, 'sharpe_ratio') else None
            result.exit_reason_breakdown = backtest_result.exit_reason_breakdown() if hasattr(backtest_result, 'exit_reason_breakdown') else None
            result.trades = trades
            result.equity_curve = equity_curve
            result.completed_at = datetime.utcnow()

        except Exception as e:
            result.status = BacktestStatus.FAILED
            result.error_message = str(e)
            result.completed_at = datetime.utcnow()

        return backtest_id

    def get_backtest(self, backtest_id: str) -> BacktestResultData | None:
        """Get backtest result by ID."""
        return _backtest_store.get(backtest_id)

    def list_backtests(self, user_id: str, limit: int = 20) -> list[BacktestResultData]:
        """List recent backtests (simplified - returns all for now)."""
        results = list(_backtest_store.values())
        results.sort(key=lambda x: x.created_at or datetime.min, reverse=True)
        return results[:limit]


# Singleton instance
_service: BacktestService | None = None


def get_backtest_service() -> BacktestService:
    """Get or create the backtest service singleton."""
    global _service
    if _service is None:
        _service = BacktestService()
    return _service
