"""
MACD Crossover Momentum Strategy
=================================

Theory
------
The Moving Average Convergence Divergence (MACD) indicator captures momentum
shifts by measuring the gap between a fast and slow exponential moving average
of price.  A *crossover* — when the MACD line crosses the signal line — marks
a change in the direction of momentum.

In prediction markets, momentum shifts often occur when a steady flow of
information gradually changes the consensus probability.  A bullish MACD
crossover (MACD histogram turns from negative to positive) suggests that
short-term momentum is now outpacing the longer-term trend, signalling a
potential upward move.  A bearish crossover signals the opposite.

Unlike the WhaleWatcherStrategy (which needs a rare high-Z book event), MACD
crossovers happen every time the two EMAs change their relative ordering, so
signal frequency scales naturally with the chosen EMA periods and the data
resolution.

Signal rules
------------
* **BUY signal**: MACD histogram crosses from negative → positive
  (bullish crossover; short EMA accelerating above long EMA).

* **SELL signal**: MACD histogram crosses from positive → negative
  (bearish crossover; short EMA falling below long EMA).

Only the *crossover bar* generates a signal; bars where the histogram is
already in the same sign territory as the previous bar are skipped.

Optional filters
----------------
* ``min_histogram``: Minimum absolute value of the histogram at the crossover
  bar.  Filters out very weak crossovers in flat markets.  Default 0.0
  (disabled).

* ``momentum_confirm``: When True, also require the rate-of-change momentum
  indicator to align with the crossover direction.  Default False.

* ``book_pressure_confirm``: When True, require order-book pressure to lean in
  the signal direction.  Default False.

* ``min_price`` / ``max_price``: Skip near-resolution extreme prices where
  momentum assumptions break down.  Defaults 0.03 / 0.97.

* ``trend_filter``: When True, suppress crossover signals that contradict a
  strong prevailing trend.  A bearish crossover (SELL) inside a strong
  uptrend is suppressed; a bullish crossover (BUY) inside a strong downtrend
  is suppressed.  Prevents early counter-trend entries on the first
  retracement during a sustained directional move.  Default False.
"""

from __future__ import annotations

from typing import Any

from ..indicators import book_pressure, macd, momentum, trend_slope
from ..models import Signal, TradeSignal
from ..strategy import BaseStrategy


class MACDMomentumStrategy(BaseStrategy):
    """
    Momentum strategy that fires on MACD histogram sign crossovers.

    Parameters
    ----------
    macd_fast:
        Fast EMA period.  Default 12.
    macd_slow:
        Slow EMA period.  Default 26.
    macd_signal_period:
        Signal-line EMA period.  Default 9.
    min_histogram:
        Minimum |histogram| at the crossover bar to emit a signal.
        Default 0.0 (every crossover counts).
    momentum_confirm:
        If True, require the rate-of-change momentum to agree with the
        crossover direction.  Default False.
    momentum_period:
        Lookback period for the momentum indicator.  Default 10.
    book_pressure_confirm:
        If True, require order-book pressure to align with the signal.
        Default False.
    book_depth:
        Number of levels used to compute book pressure.  Default 5.
    min_price:
        Skip bars where price < min_price.  Default 0.03.
    max_price:
        Skip bars where price > max_price.  Default 0.97.
    trend_filter:
        If True, block crossover signals that contradict a strong trend.
        Default False.
    trend_lookback:
        Number of bars over which to measure the trend.  Default 24.
    trend_threshold:
        Minimum net price change (probability points) to consider the trend
        strong enough to block a counter-trend signal.  Default 0.05.
    """

    def __init__(
        self,
        *,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal_period: int = 9,
        min_histogram: float = 0.0,
        momentum_confirm: bool = False,
        momentum_period: int = 10,
        book_pressure_confirm: bool = False,
        book_depth: int = 5,
        min_price: float = 0.03,
        max_price: float = 0.97,
        trend_filter: bool = False,
        trend_lookback: int = 24,
        trend_threshold: float = 0.05,
    ) -> None:
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal_period = macd_signal_period
        self.min_histogram = min_histogram
        self.momentum_confirm = momentum_confirm
        self.momentum_period = momentum_period
        self.book_pressure_confirm = book_pressure_confirm
        self.book_depth = book_depth
        self.min_price = min_price
        self.max_price = max_price
        self.trend_filter = trend_filter
        self.trend_lookback = trend_lookback
        self.trend_threshold = trend_threshold

        # Tracks the histogram sign from the previous bar to detect crossovers
        self._prev_histogram: float | None = None

    # ------------------------------------------------------------------
    # BaseStrategy interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "MACDMomentum"

    @property
    def params(self) -> dict[str, Any]:
        return {
            "macd_fast": self.macd_fast,
            "macd_slow": self.macd_slow,
            "macd_signal_period": self.macd_signal_period,
            "min_histogram": self.min_histogram,
            "momentum_confirm": self.momentum_confirm,
            "momentum_period": self.momentum_period,
            "book_pressure_confirm": self.book_pressure_confirm,
            "book_depth": self.book_depth,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "trend_filter": self.trend_filter,
            "trend_lookback": self.trend_lookback,
            "trend_threshold": self.trend_threshold,
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
        # Skip near-extreme prices
        if price < self.min_price or price > self.max_price:
            self._prev_histogram = None
            return None

        mc = macd(price_history, self.macd_fast, self.macd_slow, self.macd_signal_period)
        if mc is None:
            return None

        hist = mc.histogram
        prev = self._prev_histogram
        self._prev_histogram = hist

        # Need a previous value to detect a crossover
        if prev is None:
            return None

        # Detect sign crossover
        bullish_cross = prev <= 0 and hist > 0
        bearish_cross = prev >= 0 and hist < 0

        if not bullish_cross and not bearish_cross:
            return None

        # ---- Minimum histogram magnitude filter ----
        if abs(hist) < self.min_histogram:
            return None

        # ---- Optional trend filter ----
        # Suppress crossovers that fire against a strong prevailing trend.
        # A bearish crossover (sell) during a strong uptrend is usually a
        # brief pause, not a reversal — taking the trade leads to stop-outs.
        if self.trend_filter:
            slope = trend_slope(price_history, self.trend_lookback)
            if slope is not None:
                if bearish_cross and slope >= self.trend_threshold:
                    return None  # bearish cross inside uptrend — skip SELL
                if bullish_cross and slope <= -self.trend_threshold:
                    return None  # bullish cross inside downtrend — skip BUY

        # ---- Optional momentum confirmation ----
        mom: float | None = None
        if self.momentum_confirm:
            mom = momentum(price_history, self.momentum_period)
            if mom is None:
                return None
            if bullish_cross and mom <= 0:
                return None
            if bearish_cross and mom >= 0:
                return None

        # ---- Optional book pressure confirmation ----
        bp: float | None = None
        if self.book_pressure_confirm:
            bp = book_pressure(book, self.book_depth)
            if bullish_cross and bp <= 0:
                return None
            if bearish_cross and bp >= 0:
                return None

        # ---- Emit signal ----
        # Confidence: normalise histogram magnitude by the swing from prev to
        # current.  Larger swings → higher confidence.
        swing = abs(hist - prev)
        confidence = min(1.0, swing / 0.01) if swing > 0 else 0.5

        if bullish_cross:
            signal = Signal.BUY
        else:
            signal = Signal.SELL

        metadata: dict[str, Any] = {
            "macd": round(mc.macd, 5),
            "signal_line": round(mc.signal, 5),
            "histogram": round(hist, 5),
            "prev_histogram": round(prev, 5),
        }
        if mom is not None:
            metadata["momentum"] = round(mom, 4)
        if bp is not None:
            metadata["book_pressure"] = round(bp, 3)

        return TradeSignal(
            timestamp=timestamp,
            market_id="",
            token_label="",
            signal=signal,
            price_at_signal=price,
            confidence=confidence,
            metadata=metadata,
        )
