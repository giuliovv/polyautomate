"""
RSI Mean Reversion Strategy
===========================

Theory
------
The Relative Strength Index (RSI) identifies overbought and oversold market
conditions based on the magnitude of recent price changes.  In prediction
markets, probabilities that deviate sharply from the recent consensus tend to
revert once the short-term buying or selling pressure exhausts itself.

A reading below ``oversold_threshold`` (typically 30) suggests the market has
sold off too aggressively relative to its own recent history — a potential buy
opportunity.  A reading above ``overbought_threshold`` (typically 70) suggests
the opposite.

Signal rules
------------
* **BUY signal**: RSI < ``oversold_threshold``
  — market is oversold; expect mean reversion upward.

* **SELL signal**: RSI > ``overbought_threshold``
  — market is overbought; expect mean reversion downward.

Because RSI fires at every bar where the threshold is exceeded, it generates
far more signals than the WhaleWatcherStrategy, making it better suited to
markets where large block orders are rare.

Optional filters
----------------
* ``bb_confirm``: When True, also require the Bollinger z-score to be in the
  signal direction (< ``-bb_z_min`` for BUY, > ``+bb_z_min`` for SELL).
  This suppresses signals in flat, low-volatility periods.

* ``book_pressure_confirm``: When True, require the order book log-bid/ask
  pressure to lean in the signal direction (positive for BUY, negative for
  SELL).  Adds a microstructure filter but reduces signal count.

* ``min_price`` / ``max_price``: Ignore bars where the token price is
  outside this range.  Useful to skip near-resolution extreme prices
  (e.g. > 0.95 or < 0.05) where reversion assumptions break down.

* ``trend_filter``: When True, suppress signals that trade *against* a
  strong prevailing trend.  Specifically:

  - If the market has risen by more than ``trend_threshold`` probability
    points over the last ``trend_lookback`` bars, SELL signals are blocked
    (do not short into an uptrend).
  - If it has fallen by more than ``trend_threshold`` pp, BUY signals are
    blocked (do not buy into a downtrend).

  This prevents the strategy from being stopped out on news-driven moves
  where RSI goes overbought/oversold *because* of a genuine trend, not a
  transient deviation.  Default False.
"""

from __future__ import annotations

from typing import Any

from ..indicators import bollinger, book_pressure, rsi, trend_slope
from ..models import Signal, TradeSignal
from ..strategy import BaseStrategy


class RSIMeanReversionStrategy(BaseStrategy):
    """
    Mean-reversion strategy driven by RSI overbought/oversold levels.

    Parameters
    ----------
    rsi_period:
        RSI lookback period.  Default 14.
    oversold_threshold:
        RSI level below which a BUY signal is emitted.  Default 30.
    overbought_threshold:
        RSI level above which a SELL signal is emitted.  Default 70.
    bb_confirm:
        If True, require the Bollinger z-score to agree with the RSI signal
        direction.  Default False.
    bb_period:
        Bollinger Bands lookback period (only used when ``bb_confirm=True``).
        Default 20.
    bb_z_min:
        Minimum absolute Bollinger z-score required when ``bb_confirm=True``.
        Default 1.0.
    book_pressure_confirm:
        If True, require order-book pressure to align with the signal direction.
        Default False.
    book_depth:
        Number of levels used to compute book pressure.  Default 5.
    min_price:
        Skip bars where price < min_price (near-zero prices).  Default 0.03.
    max_price:
        Skip bars where price > max_price (near-resolution prices).  Default 0.97.
    trend_filter:
        If True, block signals that trade against a strong prevailing trend.
        Default False.
    trend_lookback:
        Number of bars over which to measure the trend.  Default 24 (one day
        at 1-hour resolution).
    trend_threshold:
        Minimum net price change (probability points) over ``trend_lookback``
        bars to consider the trend "strong".  Default 0.05 (5 pp).
    """

    def __init__(
        self,
        *,
        rsi_period: int = 14,
        oversold_threshold: float = 30.0,
        overbought_threshold: float = 70.0,
        bb_confirm: bool = False,
        bb_period: int = 20,
        bb_z_min: float = 1.0,
        book_pressure_confirm: bool = False,
        book_depth: int = 5,
        min_price: float = 0.03,
        max_price: float = 0.97,
        trend_filter: bool = False,
        trend_lookback: int = 24,
        trend_threshold: float = 0.05,
    ) -> None:
        self.rsi_period = rsi_period
        self.oversold_threshold = oversold_threshold
        self.overbought_threshold = overbought_threshold
        self.bb_confirm = bb_confirm
        self.bb_period = bb_period
        self.bb_z_min = bb_z_min
        self.book_pressure_confirm = book_pressure_confirm
        self.book_depth = book_depth
        self.min_price = min_price
        self.max_price = max_price
        self.trend_filter = trend_filter
        self.trend_lookback = trend_lookback
        self.trend_threshold = trend_threshold

    # ------------------------------------------------------------------
    # BaseStrategy interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "RSIMeanReversion"

    @property
    def params(self) -> dict[str, Any]:
        return {
            "rsi_period": self.rsi_period,
            "oversold_threshold": self.oversold_threshold,
            "overbought_threshold": self.overbought_threshold,
            "bb_confirm": self.bb_confirm,
            "bb_period": self.bb_period,
            "bb_z_min": self.bb_z_min,
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
        # Skip near-extreme prices where mean reversion is less reliable
        if price < self.min_price or price > self.max_price:
            return None

        rsi_val = rsi(price_history, self.rsi_period)
        if rsi_val is None:
            return None

        is_oversold = rsi_val < self.oversold_threshold
        is_overbought = rsi_val > self.overbought_threshold

        if not is_oversold and not is_overbought:
            return None

        # ---- Optional trend filter ----
        # Suppress mean-reversion signals that trade against a strong trend.
        # RSI goes overbought/oversold both in genuine reversions AND during
        # news-driven momentum moves; without this filter the strategy takes
        # heavy stop-losses on the latter.
        if self.trend_filter:
            slope = trend_slope(price_history, self.trend_lookback)
            if slope is not None:
                if is_overbought and slope >= self.trend_threshold:
                    return None  # RSI overbought inside an uptrend — skip SELL
                if is_oversold and slope <= -self.trend_threshold:
                    return None  # RSI oversold inside a downtrend — skip BUY

        # ---- Optional Bollinger Band confirmation ----
        bb_z: float | None = None
        if self.bb_confirm:
            bb = bollinger(price_history, self.bb_period)
            if bb is None:
                return None
            bb_z = bb.z
            if is_oversold and bb_z > -self.bb_z_min:
                return None
            if is_overbought and bb_z < self.bb_z_min:
                return None

        # ---- Optional book pressure confirmation ----
        bp: float | None = None
        if self.book_pressure_confirm:
            bp = book_pressure(book, self.book_depth)
            if is_oversold and bp <= 0:
                return None
            if is_overbought and bp >= 0:
                return None

        # ---- Emit signal ----
        # Confidence: how extreme is the RSI reading?
        # RSI=30 → confidence=0.0, RSI=0 → confidence=1.0  (for BUY)
        # RSI=70 → confidence=0.0, RSI=100 → confidence=1.0 (for SELL)
        if is_oversold:
            signal = Signal.BUY
            confidence = min(1.0, (self.oversold_threshold - rsi_val) / self.oversold_threshold)
        else:
            signal = Signal.SELL
            confidence = min(1.0, (rsi_val - self.overbought_threshold) / (100.0 - self.overbought_threshold))

        metadata: dict[str, Any] = {"rsi": round(rsi_val, 2)}
        if bb_z is not None:
            metadata["bb_z"] = round(bb_z, 3)
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
