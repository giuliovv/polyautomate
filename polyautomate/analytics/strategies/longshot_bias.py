"""
Longshot Bias Strategy
======================

Theory
------
Prediction markets exhibit a well-documented systematic bias: bettors
over-weight low-probability outcomes (longshots) and under-weight
high-probability outcomes (favorites).  The result is that:

* YES tokens priced *below* ~0.35 tend to be **overpriced** relative to
  their true resolution probability — the market is too optimistic about
  unlikely events.
* YES tokens priced *above* ~0.65 tend to be **underpriced** — the market
  is too pessimistic about likely events.

This bias was documented for horse racing (Snowberg & Wolfers 2010),
sports betting (Thaler & Ziemba 1988), and has since been observed on
Polymarket (win rates of 58-62% reported for favorite-betting strategies).

Signal rules
------------
* **SELL signal** when price enters the *longshot zone* (price ≤
  ``longshot_threshold``).  The YES token is overpriced; selling it (or
  buying NO) has positive expected value.

* **BUY signal** when price enters the *favorite zone* (price ≥
  ``favorite_threshold``).  The YES token is underpriced; buying it has
  positive expected value.

Signals are emitted **only on zone entry** (the first bar the price
crosses into a zone), not on every bar while in the zone.  This avoids
flooding the engine with repeated entries.

Optional filters
----------------
* ``min_price`` / ``max_price``: Ignore bars near 0 or 1 where the
  order book is too thin and resolution risk dominates.

* ``entry_on_move``: When True, also require the price to have *moved*
  into the zone this bar (price[−1] was outside the zone).  Equivalent
  to the zone-entry logic but expressed explicitly.  Default True.
"""

from __future__ import annotations

from typing import Any

from ..models import Signal, TradeSignal
from ..strategy import BaseStrategy


class LongshotBiasStrategy(BaseStrategy):
    """
    Directional strategy exploiting the well-documented favorite/longshot bias.

    Parameters
    ----------
    longshot_threshold:
        Price below which the YES token is considered an overpriced longshot
        and a SELL signal is emitted.  Default 0.35.
    favorite_threshold:
        Price above which the YES token is considered an underpriced favorite
        and a BUY signal is emitted.  Default 0.65.
    min_price:
        Ignore bars where price < min_price.  Default 0.04.
    max_price:
        Ignore bars where price > max_price.  Default 0.96.
    """

    def __init__(
        self,
        *,
        longshot_threshold: float = 0.35,
        favorite_threshold: float = 0.65,
        min_price: float = 0.04,
        max_price: float = 0.96,
    ) -> None:
        if longshot_threshold >= favorite_threshold:
            raise ValueError(
                "longshot_threshold must be strictly less than favorite_threshold"
            )
        self.longshot_threshold = longshot_threshold
        self.favorite_threshold = favorite_threshold
        self.min_price = min_price
        self.max_price = max_price

        # Track which zone the price was in last bar to detect transitions
        self._prev_zone: str | None = None   # "longshot" | "neutral" | "favorite"

    # ------------------------------------------------------------------
    # BaseStrategy interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "LongshotBias"

    @property
    def params(self) -> dict[str, Any]:
        return {
            "longshot_threshold": self.longshot_threshold,
            "favorite_threshold": self.favorite_threshold,
            "min_price": self.min_price,
            "max_price": self.max_price,
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
        if price < self.min_price or price > self.max_price:
            self._prev_zone = None
            return None

        # Determine current zone
        if price <= self.longshot_threshold:
            zone = "longshot"
        elif price >= self.favorite_threshold:
            zone = "favorite"
        else:
            zone = "neutral"

        prev_zone = self._prev_zone
        self._prev_zone = zone

        # Only fire on zone entry (transition into longshot or favorite)
        if zone == prev_zone or zone == "neutral":
            return None

        if zone == "longshot":
            signal = Signal.SELL
            # Confidence scales with how deep into the longshot zone we are
            confidence = min(
                1.0,
                (self.longshot_threshold - price) / self.longshot_threshold,
            )
        else:  # favorite
            signal = Signal.BUY
            confidence = min(
                1.0,
                (price - self.favorite_threshold) / (1.0 - self.favorite_threshold),
            )

        return TradeSignal(
            timestamp=timestamp,
            market_id="",
            token_label="",
            signal=signal,
            price_at_signal=price,
            confidence=confidence,
            metadata={
                "zone": zone,
                "longshot_threshold": self.longshot_threshold,
                "favorite_threshold": self.favorite_threshold,
            },
        )
