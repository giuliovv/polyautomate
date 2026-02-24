"""
Base class for all backtesting strategies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import TradeSignal


class BaseStrategy(ABC):
    """
    Abstract base for a trading strategy.

    Subclasses implement :meth:`on_step`, which is called for every time
    bar with the current price, order book snapshot, and recent history.
    It returns a :class:`~polyautomate.backtest.models.TradeSignal` or
    ``None`` if no trade should be opened.

    The engine tracks open positions and calls the strategy for exit
    decisions via :meth:`should_exit`.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable strategy identifier."""

    @property
    @abstractmethod
    def params(self) -> dict[str, Any]:
        """Dict of strategy hyper-parameters for result logging."""

    @abstractmethod
    def on_step(
        self,
        *,
        timestamp: int,
        price: float,
        book: dict,                    # {ts, bids: [[p,s],...], asks: [[p,s],...]}
        price_history: list[float],    # recent prices, oldest first
        book_history: list[dict],      # recent book snapshots, oldest first
    ) -> TradeSignal | None:
        """
        Evaluate current market state and optionally emit a signal.

        Parameters
        ----------
        timestamp:
            Current bar Unix timestamp.
        price:
            Current mid-price (probability in [0, 1]).
        book:
            Order book snapshot for the current bar.
        price_history:
            Prices for the last N bars (including current), oldest first.
        book_history:
            Book snapshots for the last N bars (including current), oldest first.

        Returns
        -------
        TradeSignal or None
            Return a signal to open a new position, or ``None`` to skip.
        """
