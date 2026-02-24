"""
Optimal-entry pattern mining and cross-market profile strategy.

Workflow
--------
1. **Scan** a historical market to find every bar that, in hindsight, was an
   optimal buy (or sell) point — i.e. the price moved at least ``min_gain``
   in the desired direction within the next ``forward_window`` bars.

2. At each optimal bar, record the full indicator vector (RSI, Bollinger z,
   MACD histogram, momentum, realised vol, book imbalance, book pressure,
   book spread).

3. Average those vectors into an ``EntryProfile`` (mean + std per feature).

4. Drop the ``ProfileStrategy`` into any ``BacktestEngine.run()`` call: it
   computes the same indicator vector live and fires a signal whenever the
   current bar is within ``max_distance`` standardised-Euclidean units of
   the learned profile.

This lets you train on one market and test the generalised pattern on another.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..indicators import FEATURE_NAMES, compute_features
from ..models import Signal, TradeSignal
from ..strategy import BaseStrategy


# ── Learned profile ───────────────────────────────────────────────────────────

@dataclass
class EntryProfile:
    """
    Statistical fingerprint of optimal entry conditions.

    Attributes
    ----------
    signal:
        Whether this profile describes BUY or SELL entries.
    feature_names:
        Ordered list of feature names (mirrors :data:`~indicators.FEATURE_NAMES`).
    mean:
        Per-feature mean at optimal entry bars.
    std:
        Per-feature sample std-dev at optimal entry bars.
    n_samples:
        Number of optimal entry bars used to build the profile.
    training_market:
        Human-readable label for the market this was trained on.
    """

    signal: Signal
    feature_names: list[str]
    mean: list[float]
    std: list[float]
    n_samples: int
    training_market: str = ""

    def distance(self, features: list[float | None]) -> float:
        """
        Standardised Euclidean distance from this profile.

        Features with ``None`` value or zero std are skipped.
        Returns ``inf`` when no valid features remain.
        """
        total = 0.0
        count = 0
        for x, mu, sigma in zip(features, self.mean, self.std):
            if x is None or sigma == 0.0:
                continue
            total += ((x - mu) / sigma) ** 2
            count += 1
        return math.sqrt(total / count) if count > 0 else float("inf")

    def summary(self) -> str:
        lines = [
            f"EntryProfile: {self.signal.value.upper()} on '{self.training_market}'",
            f"Trained on {self.n_samples} optimal entry bars",
            "",
            f"{'Feature':<18}  {'Mean':>8}  {'Std':>8}",
            "-" * 38,
        ]
        for name, mu, sigma in zip(self.feature_names, self.mean, self.std):
            lines.append(f"{name:<18}  {mu:>8.4f}  {sigma:>8.4f}")
        return "\n".join(lines)


# ── Scanner ───────────────────────────────────────────────────────────────────

def scan_optimal_entries(
    price_series: list[dict],  # [{ts, price}, ...]
    book_series: list[dict],   # [{ts, bids, asks}, ...]
    signal: Signal,
    *,
    min_gain: float = 0.04,
    forward_window: int = 24,
    indicator_window: int = 48,
    training_market: str = "",
    # Indicator hyper-params
    rsi_period: int = 14,
    bb_period: int = 20,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal_period: int = 9,
    mom_period: int = 10,
    vol_period: int = 24,
    book_depth: int = 5,
) -> EntryProfile:
    """
    Mine a historical price+book series for optimal entry points and return
    their indicator fingerprint.

    An "optimal BUY entry" at bar *i* means the price at some bar in
    ``[i+1, i+forward_window]`` exceeds ``price[i] + min_gain``.
    An "optimal SELL entry" is the mirror condition.

    Parameters
    ----------
    price_series, book_series:
        Raw series as returned by the API / disk cache (dicts with ``ts``
        and ``price`` / ``bids`` / ``asks``).
    signal:
        ``Signal.BUY`` or ``Signal.SELL`` — which direction to mine.
    min_gain:
        Minimum price move in probability points that qualifies an entry.
    forward_window:
        How many bars ahead to look for the qualifying move.
    indicator_window:
        Minimum price history length needed to compute indicators; bars
        before this are skipped.
    training_market:
        Label embedded in the returned ``EntryProfile`` for bookkeeping.
    """
    if signal not in (Signal.BUY, Signal.SELL):
        raise ValueError("signal must be Signal.BUY or Signal.SELL")

    prices = [b["price"] for b in price_series]
    book_by_ts = {snap["ts"]: snap for snap in book_series}

    feature_matrix: list[list[float | None]] = []

    for i in range(indicator_window, len(prices) - forward_window):
        entry_price = prices[i]
        future_prices = prices[i + 1 : i + 1 + forward_window]

        if signal == Signal.BUY:
            triggered = any(p >= entry_price + min_gain for p in future_prices)
        else:
            triggered = any(p <= entry_price - min_gain for p in future_prices)

        if not triggered:
            continue

        ts = price_series[i]["ts"]
        book = book_by_ts.get(ts, {"ts": ts, "bids": [], "asks": []})
        price_hist = prices[max(0, i - indicator_window) : i + 1]

        feats = compute_features(
            price_hist,
            book,
            rsi_period=rsi_period,
            bb_period=bb_period,
            macd_fast=macd_fast,
            macd_slow=macd_slow,
            macd_signal=macd_signal_period,
            mom_period=mom_period,
            vol_period=vol_period,
            book_depth=book_depth,
        )
        feature_matrix.append(feats)

    if not feature_matrix:
        raise ValueError(
            f"No optimal {signal.value} entries found (min_gain={min_gain}, "
            f"forward_window={forward_window}).  Try relaxing the thresholds."
        )

    n = len(feature_matrix)
    n_feats = len(FEATURE_NAMES)

    # Per-column mean, ignoring None
    means: list[float] = []
    stds: list[float] = []
    for col in range(n_feats):
        vals = [row[col] for row in feature_matrix if row[col] is not None]
        if not vals:
            means.append(0.0)
            stds.append(0.0)
            continue
        mu = sum(vals) / len(vals)
        means.append(mu)
        if len(vals) < 2:
            stds.append(0.0)
        else:
            var = sum((v - mu) ** 2 for v in vals) / (len(vals) - 1)
            stds.append(math.sqrt(var))

    return EntryProfile(
        signal=signal,
        feature_names=list(FEATURE_NAMES),
        mean=means,
        std=stds,
        n_samples=n,
        training_market=training_market,
    )


# ── Strategy ──────────────────────────────────────────────────────────────────

class ProfileStrategy(BaseStrategy):
    """
    Signal based on similarity to a learned :class:`EntryProfile`.

    At each bar the strategy computes the full indicator vector and fires a
    signal when the standardised Euclidean distance to the profile falls
    below ``max_distance``.

    Parameters
    ----------
    profile:
        An :class:`EntryProfile` produced by :func:`scan_optimal_entries`.
    max_distance:
        Distance threshold (lower = more restrictive).  Default 1.5 means
        "within 1.5 std-devs on average across all features".
    min_confidence:
        Minimum confidence score to emit a signal.  Confidence is computed
        as ``1 / (1 + distance)``.
    """

    def __init__(
        self,
        profile: EntryProfile,
        *,
        max_distance: float = 1.5,
        min_confidence: float = 0.35,
        # Indicator hyper-params (should match those used during scan)
        rsi_period: int = 14,
        bb_period: int = 20,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal_period: int = 9,
        mom_period: int = 10,
        vol_period: int = 24,
        book_depth: int = 5,
    ) -> None:
        self._profile = profile
        self._max_distance = max_distance
        self._min_confidence = min_confidence
        self._indicator_kwargs: dict[str, Any] = dict(
            rsi_period=rsi_period,
            bb_period=bb_period,
            macd_fast=macd_fast,
            macd_slow=macd_slow,
            macd_signal=macd_signal_period,
            mom_period=mom_period,
            vol_period=vol_period,
            book_depth=book_depth,
        )

    @property
    def name(self) -> str:
        return "ProfileStrategy"

    @property
    def params(self) -> dict[str, Any]:
        return {
            "training_market": self._profile.training_market,
            "profile_signal": self._profile.signal.value,
            "n_samples": self._profile.n_samples,
            "max_distance": self._max_distance,
            "min_confidence": self._min_confidence,
            **self._indicator_kwargs,
        }

    def on_step(
        self,
        timestamp: int,
        price: float,
        book: dict,
        price_history: list[float],
        book_history: list[dict],
    ) -> TradeSignal | None:
        feats = compute_features(price_history, book, **self._indicator_kwargs)
        dist = self._profile.distance(feats)

        if dist > self._max_distance:
            return None

        confidence = 1.0 / (1.0 + dist)
        if confidence < self._min_confidence:
            return None

        return TradeSignal(
            timestamp=timestamp,
            market_id="",
            token_label="",
            signal=self._profile.signal,
            price_at_signal=price,
            confidence=confidence,
            metadata={"distance": dist},
        )
