"""
Technical and microstructure indicators.

All functions operate on plain Python lists so they work directly with the
``price_history`` / ``book_history`` that :class:`BacktestEngine` passes to
``on_step()``.  Every function returns ``None`` when insufficient data is
available rather than raising.
"""

from __future__ import annotations

import math
from typing import NamedTuple


# ── Price indicators ──────────────────────────────────────────────────────────

def rsi(prices: list[float], period: int = 14) -> float | None:
    """Relative Strength Index (0–100). Returns None if len(prices) < period+1."""
    if len(prices) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period, 0):
        delta = prices[i] - prices[i - 1]
        if delta > 0:
            gains.append(delta)
        else:
            losses.append(-delta)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


class BollingerBands(NamedTuple):
    upper: float
    mid: float
    lower: float
    z: float  # (price[-1] - mid) / std


def bollinger(
    prices: list[float], period: int = 20, n_std: float = 2.0
) -> BollingerBands | None:
    """Bollinger Bands + z-score of the last price. Returns None if len < period."""
    if len(prices) < period:
        return None
    window = prices[-period:]
    mid = sum(window) / period
    std = math.sqrt(sum((p - mid) ** 2 for p in window) / period)
    if std == 0.0:
        return BollingerBands(mid, mid, mid, 0.0)
    return BollingerBands(
        upper=mid + n_std * std,
        mid=mid,
        lower=mid - n_std * std,
        z=(prices[-1] - mid) / std,
    )


class MACDResult(NamedTuple):
    macd: float
    signal: float
    histogram: float


def _ema(values: list[float], period: int) -> float:
    k = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1.0 - k)
    return ema


def macd(
    prices: list[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> MACDResult | None:
    """MACD line, signal line, and histogram. Returns None if insufficient data."""
    min_len = slow + signal_period
    if len(prices) < min_len:
        return None
    macd_series = [
        _ema(prices[: i + 1], fast) - _ema(prices[: i + 1], slow)
        for i in range(slow - 1, len(prices))
    ]
    if len(macd_series) < signal_period:
        return None
    sig = _ema(macd_series, signal_period)
    m = macd_series[-1]
    return MACDResult(macd=m, signal=sig, histogram=m - sig)


def momentum(prices: list[float], period: int = 10) -> float | None:
    """Rate of change: (price[-1] - price[-period-1]) / price[-period-1]."""
    if len(prices) < period + 1:
        return None
    base = prices[-(period + 1)]
    if base == 0.0:
        return None
    return (prices[-1] - base) / base


def realized_vol(prices: list[float], period: int = 24) -> float | None:
    """Sample std-dev of log-returns over the last ``period`` bars."""
    if len(prices) < period + 1:
        return None
    window = prices[-(period + 1) :]
    log_ret = []
    for i in range(1, len(window)):
        if window[i - 1] > 0.0 and window[i] > 0.0:
            log_ret.append(math.log(window[i] / window[i - 1]))
    if len(log_ret) < 2:
        return None
    mean = sum(log_ret) / len(log_ret)
    var = sum((r - mean) ** 2 for r in log_ret) / (len(log_ret) - 1)
    return math.sqrt(var)


# ── Order book indicators ─────────────────────────────────────────────────────

def book_spread(book: dict) -> float | None:
    """Best ask − best bid. Returns None if either side is empty."""
    bids = book.get("bids", [])
    asks = book.get("asks", [])
    if not bids or not asks:
        return None
    best_bid = max(float(b[0]) for b in bids)
    best_ask = min(float(a[0]) for a in asks)
    return best_ask - best_bid


def book_imbalance(book: dict) -> float:
    """Notional bid weight: bid_vol / (bid_vol + ask_vol). Range 0–1; 0.5 = balanced."""
    bid_vol = sum(float(b[0]) * float(b[1]) for b in book.get("bids", []))
    ask_vol = sum(float(a[0]) * float(a[1]) for a in book.get("asks", []))
    total = bid_vol + ask_vol
    return bid_vol / total if total > 0.0 else 0.5


def book_pressure(book: dict, depth: int = 5) -> float:
    """
    log(top-``depth`` bid notional / top-``depth`` ask notional).

    Positive values indicate buy-side pressure; negative = sell-side pressure.
    Returns 0.0 when either side is empty.
    """
    bids = sorted(book.get("bids", []), key=lambda x: -float(x[0]))[:depth]
    asks = sorted(book.get("asks", []), key=lambda x: float(x[0]))[:depth]
    bid_p = sum(float(b[0]) * float(b[1]) for b in bids)
    ask_p = sum(float(a[0]) * float(a[1]) for a in asks)
    if bid_p <= 0.0 or ask_p <= 0.0:
        return 0.0
    return math.log(bid_p / ask_p)


# ── Composite feature vector ──────────────────────────────────────────────────

FEATURE_NAMES = [
    "rsi",
    "bb_z",
    "macd_hist",
    "momentum",
    "realized_vol",
    "book_imbalance",
    "book_pressure",
    "book_spread",
]


def compute_features(
    price_history: list[float],
    book: dict,
    *,
    rsi_period: int = 14,
    bb_period: int = 20,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    mom_period: int = 10,
    vol_period: int = 24,
    book_depth: int = 5,
) -> list[float | None]:
    """
    Compute the full composite feature vector for one bar.

    Returns a list aligned with :data:`FEATURE_NAMES`.  Individual entries
    may be ``None`` when insufficient history is available.
    """
    bb = bollinger(price_history, bb_period)
    mc = macd(price_history, macd_fast, macd_slow, macd_signal)
    return [
        rsi(price_history, rsi_period),
        bb.z if bb else None,
        mc.histogram if mc else None,
        momentum(price_history, mom_period),
        realized_vol(price_history, vol_period),
        book_imbalance(book),
        book_pressure(book, book_depth),
        book_spread(book),
    ]
