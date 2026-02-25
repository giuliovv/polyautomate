"""
Data models for the backtesting framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .stats import ConfidenceInterval, wilson_ci


class Signal(str, Enum):
    """Direction of a trade signal."""

    BUY = "buy"   # Expect the token price (probability) to rise.
    SELL = "sell"  # Expect the token price (probability) to fall.
    HOLD = "hold"  # No action.


@dataclass
class TradeSignal:
    """A signal emitted by a strategy at a specific point in time."""

    timestamp: int          # Unix timestamp
    market_id: str
    token_label: str        # e.g. "YES" or "NO"
    signal: Signal
    price_at_signal: float  # Current mid-price when signal fires
    confidence: float       # Strategy-assigned score in [0, 1]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trade:
    """A completed round-trip trade (entry + exit)."""

    signal: TradeSignal
    entry_price: float
    exit_price: float
    exit_timestamp: int
    exit_reason: str        # "take_profit" | "stop_loss" | "timeout" | "end_of_data"
    fee_rate: float = 0.0   # Fraction charged on each leg (e.g. 0.02 = 2% per side)

    @property
    def gross_pnl(self) -> float:
        """Raw price-move P&L before fees."""
        raw = self.exit_price - self.entry_price
        return raw if self.signal.signal == Signal.BUY else -raw

    @property
    def pnl(self) -> float:
        """
        Profit / loss in probability-point terms, net of trading fees.

        Polymarket charges a fee on each leg of the trade (entry + exit).
        Round-trip cost = fee_rate × (entry_price + exit_price).

        For a BUY signal: positive when exit_price > entry_price by more than costs.
        For a SELL signal: positive when exit_price < entry_price by more than costs.
        """
        round_trip_cost = self.fee_rate * (self.entry_price + self.exit_price)
        return self.gross_pnl - round_trip_cost

    @property
    def pnl_pct(self) -> float:
        """Return on investment as a fraction of entry price."""
        if self.entry_price == 0:
            return 0.0
        return self.pnl / self.entry_price


@dataclass
class BacktestResult:
    """Aggregated results from a single backtest run."""

    market_id: str
    token_label: str
    resolution: str
    strategy_name: str
    strategy_params: dict[str, Any]
    trades: list[Trade] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Computed statistics
    # ------------------------------------------------------------------

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wins / len(self.trades)

    @property
    def win_rate_ci(self) -> ConfidenceInterval:
        """Wilson 95 % confidence interval for the win rate."""
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wilson_ci(wins, self.n_trades)

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def avg_pnl(self) -> float:
        if not self.trades:
            return 0.0
        return self.total_pnl / len(self.trades)

    @property
    def max_drawdown(self) -> float:
        """Maximum peak-to-trough drawdown in cumulative P&L."""
        if not self.trades:
            return 0.0
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in self.trades:
            cumulative += t.pnl
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @property
    def sharpe_ratio(self) -> float:
        """Simplified Sharpe ratio (mean / std of per-trade P&L, risk-free = 0)."""
        if len(self.trades) < 2:
            return 0.0
        pnls = [t.pnl for t in self.trades]
        mean = sum(pnls) / len(pnls)
        variance = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
        std = variance ** 0.5
        if std == 0:
            return 0.0
        return mean / std

    def exit_reason_breakdown(self) -> dict[str, int]:
        breakdown: dict[str, int] = {}
        for t in self.trades:
            breakdown[t.exit_reason] = breakdown.get(t.exit_reason, 0) + 1
        return breakdown

    def summary(self) -> str:
        lines = [
            f"=== Backtest: {self.strategy_name} on {self.market_id} ({self.token_label}) ===",
            f"Resolution  : {self.resolution}",
            f"Trades      : {self.n_trades}",
            f"Win rate    : {self.win_rate:.1%}  95% CI {self.win_rate_ci}",
            f"Total P&L   : {self.total_pnl:+.4f} probability pts",
            f"Avg P&L     : {self.avg_pnl:+.4f}",
            f"Max drawdown: {self.max_drawdown:.4f}",
            f"Sharpe ratio: {self.sharpe_ratio:.3f}",
            f"Exit reasons: {self.exit_reason_breakdown()}",
        ]
        return "\n".join(lines)
