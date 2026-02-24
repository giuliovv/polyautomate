"""
Whale / Insider Watcher Strategy
=================================

Theory
------
Sophisticated "whale" traders — whether institutional, well-informed, or simply
very large — tend to enter positions *against* the prevailing short-term price
trend when they have strong conviction.  If the market has been steadily
pricing an outcome higher and a large sell order suddenly dominates the book,
that could indicate a whale expects the price to fall.  Conversely, a large
buy-side order appearing while the price has been falling could signal an
informed bottom-pick.

Detection approach (order book based)
--------------------------------------
For every bar we compute, for both the bid and ask sides:

1. **Best-level notional** – the dollar size of the single largest resting
   level in the book (``best_bid_notional`` / ``best_ask_notional``).  A level
   suddenly orders-of-magnitude larger than its rolling mean is a whale.
2. **Total side notional** – sum of all levels on that side.  We also track the
   **book imbalance** = bids_total / (bids_total + asks_total) and its *change*
   between consecutive bars.

Signal rules
------------
* **BUY signal** (expect price to rise):
  - A statistically large *bid* level appears (Z-score ≥ ``whale_z_threshold``),
    AND the recent price trend is *down* (price moved down over
    ``trend_lookback`` bars).
  - Interpretation: whale buying into weakness → we follow.

* **SELL signal** (expect price to fall):
  - A statistically large *ask* level appears (Z-score ≥ ``whale_z_threshold``),
    AND the recent price trend is *up*.
  - Interpretation: whale selling into strength → we follow.

The Z-score is computed from a rolling window of ``stat_window`` bars of the
best-level notional.  Minimum ``min_whale_notional`` guards against firing on
thin-book markets where even a small order looks like an outlier.

A minimum ``min_trend_move`` prevents the strategy from firing when there is no
clear directional trend to be contrarian to.
"""

from __future__ import annotations

import math
from typing import Any

from ..models import Signal, TradeSignal
from ..strategy import BaseStrategy


def _best_notional(levels: list[list[float]]) -> float:
    """Return the largest price*size product across all book levels."""
    if not levels:
        return 0.0
    return max(price * size for price, size in levels)


def _total_notional(levels: list[list[float]]) -> float:
    """Return the sum of price*size across all book levels."""
    return sum(price * size for price, size in levels)


def _rolling_mean_std(values: list[float]) -> tuple[float, float]:
    """Compute mean and sample std-dev of a list."""
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return mean, math.sqrt(variance)


class WhaleWatcherStrategy(BaseStrategy):
    """
    Detects large order-book entries that oppose the recent price trend.

    Parameters
    ----------
    whale_z_threshold:
        Minimum Z-score of the best-level notional to classify an order as a
        "whale".  Default 3.0 (roughly the 99.9th percentile of a normal
        distribution).
    trend_lookback:
        Number of past bars used to determine the recent price trend.
        The trend is calculated as ``price[-1] - price[-trend_lookback]``.
        Default 24.
    min_trend_move:
        Minimum absolute price change (in probability points) required to
        consider the trend meaningful.  Prevents firing in flat markets.
        Default 0.02 (2 pp).
    min_whale_notional:
        Minimum best-level notional (in USD) for a whale detection.
        Guards against thin markets.  Default 500.
    stat_window:
        Number of recent bars used to compute the rolling mean/std for
        Z-score normalisation.  Default 48.
    imbalance_confirm:
        If True, require the book-imbalance *change* to also point in the
        signal direction (additional confirmation filter).  Default True.
    """

    def __init__(
        self,
        *,
        whale_z_threshold: float = 3.0,
        trend_lookback: int = 24,
        min_trend_move: float = 0.02,
        min_whale_notional: float = 500.0,
        stat_window: int = 48,
        imbalance_confirm: bool = True,
    ) -> None:
        self.whale_z_threshold = whale_z_threshold
        self.trend_lookback = trend_lookback
        self.min_trend_move = min_trend_move
        self.min_whale_notional = min_whale_notional
        self.stat_window = stat_window
        self.imbalance_confirm = imbalance_confirm

        # Rolling history for normalisation (populated during on_step calls)
        self._bid_notionals: list[float] = []
        self._ask_notionals: list[float] = []
        self._prev_imbalance: float | None = None

    # ------------------------------------------------------------------
    # BaseStrategy interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "WhaleWatcher"

    @property
    def params(self) -> dict[str, Any]:
        return {
            "whale_z_threshold": self.whale_z_threshold,
            "trend_lookback": self.trend_lookback,
            "min_trend_move": self.min_trend_move,
            "min_whale_notional": self.min_whale_notional,
            "stat_window": self.stat_window,
            "imbalance_confirm": self.imbalance_confirm,
        }

    def on_step(
        self,
        *,
        timestamp: int,
        price: float,
        book: dict,
        price_history: list[float],
        book_history: list[dict],
    ) -> TradeSignal | None:
        bids: list[list[float]] = book.get("bids", [])
        asks: list[list[float]] = book.get("asks", [])

        bid_notional = _best_notional(bids)
        ask_notional = _best_notional(asks)

        # Maintain rolling notional history
        self._bid_notionals.append(bid_notional)
        self._ask_notionals.append(ask_notional)
        if len(self._bid_notionals) > self.stat_window:
            self._bid_notionals.pop(0)
            self._ask_notionals.pop(0)

        # Need enough history for stats
        if len(self._bid_notionals) < max(self.stat_window // 2, 5):
            return None

        # ---- Trend detection ----
        if len(price_history) < self.trend_lookback + 1:
            return None
        trend_move = price_history[-1] - price_history[-self.trend_lookback - 1]
        if abs(trend_move) < self.min_trend_move:
            return None  # Flat market – skip
        trend_is_up = trend_move > 0

        # ---- Z-scores for whale detection ----
        bid_mean, bid_std = _rolling_mean_std(self._bid_notionals[:-1])  # exclude current
        ask_mean, ask_std = _rolling_mean_std(self._ask_notionals[:-1])

        bid_z = (bid_notional - bid_mean) / bid_std if bid_std > 0 else 0.0
        ask_z = (ask_notional - ask_mean) / ask_std if ask_std > 0 else 0.0

        whale_on_bid = bid_z >= self.whale_z_threshold and bid_notional >= self.min_whale_notional
        whale_on_ask = ask_z >= self.whale_z_threshold and ask_notional >= self.min_whale_notional

        # ---- Book imbalance confirmation ----
        total_bids = _total_notional(bids)
        total_asks = _total_notional(asks)
        denom = total_bids + total_asks
        imbalance = total_bids / denom if denom > 0 else 0.5
        imbalance_delta = (imbalance - self._prev_imbalance) if self._prev_imbalance is not None else 0.0
        self._prev_imbalance = imbalance

        # ---- Signal rules ----
        # BUY: whale buyer appears while price has been falling
        if whale_on_bid and not trend_is_up:
            if self.imbalance_confirm and imbalance_delta <= 0:
                # Imbalance did not swing toward bids – skip
                pass
            else:
                confidence = min(1.0, bid_z / (self.whale_z_threshold * 2))
                return TradeSignal(
                    timestamp=timestamp,
                    market_id="",          # filled by engine if needed
                    token_label="",        # filled by engine if needed
                    signal=Signal.BUY,
                    price_at_signal=price,
                    confidence=confidence,
                    metadata={
                        "bid_z": round(bid_z, 2),
                        "bid_notional": round(bid_notional, 2),
                        "trend_move": round(trend_move, 4),
                        "imbalance": round(imbalance, 4),
                        "imbalance_delta": round(imbalance_delta, 4),
                    },
                )

        # SELL: whale seller appears while price has been rising
        if whale_on_ask and trend_is_up:
            if self.imbalance_confirm and imbalance_delta >= 0:
                # Imbalance did not swing toward asks – skip
                pass
            else:
                confidence = min(1.0, ask_z / (self.whale_z_threshold * 2))
                return TradeSignal(
                    timestamp=timestamp,
                    market_id="",
                    token_label="",
                    signal=Signal.SELL,
                    price_at_signal=price,
                    confidence=confidence,
                    metadata={
                        "ask_z": round(ask_z, 2),
                        "ask_notional": round(ask_notional, 2),
                        "trend_move": round(trend_move, 4),
                        "imbalance": round(imbalance, 4),
                        "imbalance_delta": round(imbalance_delta, 4),
                    },
                )

        return None
