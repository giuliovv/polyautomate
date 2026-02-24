"""
Backtesting engine.

Fetches historical price and order book data from polymarketdata.co,
then simulates a strategy's performance by replaying bars in order.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from ..clients.polymarketdata import PMDClient
from .models import BacktestResult, Signal, Trade, TradeSignal
from .strategy import BaseStrategy

logger = logging.getLogger(__name__)


def _normalise_ts(value: Any) -> str:
    """
    Floor a timestamp to the nearest hour so cache keys are stable within
    a single hour window even when the caller uses datetime.now().
    """
    if isinstance(value, (int, float)):
        # Unix: floor to hour boundary
        return str(int(value) // 3600 * 3600)
    s = str(value)
    # ISO-8601: chop to "YYYY-MM-DDTHH" (drop minutes/seconds/tz)
    return s[:13]


def _cache_key(market_id: str, start_ts: Any, end_ts: Any, resolution: str) -> str:
    raw = f"{market_id}|{_normalise_ts(start_ts)}|{_normalise_ts(end_ts)}|{resolution}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _cache_load(cache_dir: str, key: str) -> dict | None:
    path = os.path.join(cache_dir, f"{key}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def _cache_save(cache_dir: str, key: str, data: dict) -> None:
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{key}.json")
    with open(path, "w") as f:
        json.dump(data, f)


def _parse_ts(value: str | int | float) -> int:
    """
    Convert a polymarketdata.co timestamp to a Unix int.

    The prices endpoint returns ISO-8601 strings in the ``t`` field;
    the books endpoint may return integers.  Both are normalised here.
    """
    if isinstance(value, (int, float)):
        return int(value)
    # ISO-8601 string e.g. "2024-10-01T06:00:00" or "2024-10-01T06:00:00+00:00"
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return 0


def _extract_price_series(raw: list[dict]) -> list[dict]:
    """
    Normalise a raw price list to ``[{ts: int, price: float}, ...]``.

    The API returns ``{t: ISO-str, p: float}`` but future API versions or
    the books endpoint may use ``{ts: int, price: float}``.
    """
    out = []
    for pt in raw:
        ts = _parse_ts(pt.get("t") or pt.get("ts", 0))
        price = float(pt.get("p") or pt.get("price", 0))
        out.append({"ts": ts, "price": price})
    return out


def _extract_book_series(raw: list[dict]) -> list[dict]:
    """
    Normalise a raw book snapshot list.

    The API uses ``{ts: int, bids: [[p,s],...], asks: [[p,s],...]}``
    (or ``t`` for the timestamp, mirroring the prices format).
    """
    out = []
    for snap in raw:
        ts = _parse_ts(snap.get("t") or snap.get("ts", 0))
        out.append({
            "ts": ts,
            "bids": snap.get("bids", []),
            "asks": snap.get("asks", []),
        })
    return out


class BacktestEngine:
    """
    Drives a strategy against historical Polymarket data.

    Parameters
    ----------
    client:
        A configured :class:`~polyautomate.api.polymarketdata.PMDClient`.
    history_window:
        Number of past bars to pass as ``price_history`` / ``book_history``
        to :meth:`~polyautomate.backtest.strategy.BaseStrategy.on_step`.
        Defaults to 48.
    """

    def __init__(
        self,
        client: PMDClient,
        *,
        history_window: int = 48,
        cache_dir: str | None = ".cache/backtest",
    ) -> None:
        self._client = client
        self._history_window = history_window
        self._cache_dir = cache_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        strategy: BaseStrategy,
        market_id: str,
        token_label: str,
        start_ts: Any,
        end_ts: Any,
        resolution: str = "1h",
        *,
        stop_loss: float = 0.05,
        take_profit: float = 0.10,
        hold_periods: int = 24,
        position_size: float = 100.0,
    ) -> BacktestResult:
        """
        Run a strategy over a historical window and return trade statistics.

        Parameters
        ----------
        strategy:
            Instantiated strategy object.
        market_id:
            Market UUID or slug.
        token_label:
            Which outcome token to trade, e.g. ``"YES"`` or ``"NO"``.
        start_ts, end_ts:
            Time range (ISO-8601 string, Unix int, or :class:`datetime`).
        resolution:
            Bar interval: ``"1m"``, ``"10m"``, ``"1h"``, ``"6h"``, ``"1d"``.
        stop_loss:
            Exit if price moves this many probability points against the
            position. Default 0.05 (5 pp).
        take_profit:
            Exit if price moves this many probability points in favour.
            Default 0.10 (10 pp).
        hold_periods:
            Maximum number of bars to hold a position before forcing exit.
        position_size:
            Notional size per trade (used only for dollar P&L reporting).

        Returns
        -------
        BacktestResult
        """
        logger.info(
            "Fetching data for %s [%s] %s → %s @ %s",
            market_id,
            token_label,
            start_ts,
            end_ts,
            resolution,
        )

        prices_by_label, books_by_label = self._fetch_data(
            market_id, start_ts, end_ts, resolution
        )

        raw_prices = prices_by_label.get(token_label, [])
        raw_books = books_by_label.get(token_label, [])

        if not raw_prices:
            raise ValueError(
                f"No price data for token label '{token_label}' in market '{market_id}'. "
                f"Available labels: {list(prices_by_label.keys())}"
            )

        # Normalise and align by timestamp
        price_series = sorted(_extract_price_series(raw_prices), key=lambda x: x["ts"])
        book_series = _extract_book_series(raw_books)
        book_by_ts = {snap["ts"]: snap for snap in book_series}

        result = BacktestResult(
            market_id=market_id,
            token_label=token_label,
            resolution=resolution,
            strategy_name=strategy.name,
            strategy_params=strategy.params,
        )

        # ------------------------------------------------------------------
        # Simulation loop
        # ------------------------------------------------------------------
        open_trade: _OpenPosition | None = None
        price_window: list[float] = []
        book_window: list[dict] = []

        for bar in price_series:
            ts = bar["ts"]
            price = bar["price"]
            book = book_by_ts.get(ts, {"ts": ts, "bids": [], "asks": []})

            price_window.append(price)
            book_window.append(book)
            if len(price_window) > self._history_window:
                price_window.pop(0)
                book_window.pop(0)

            # ---- Manage open position ----
            if open_trade is not None:
                exit_reason = _check_exit(
                    open_trade, price, stop_loss, take_profit, hold_periods
                )
                if exit_reason:
                    trade = Trade(
                        signal=open_trade.signal,
                        entry_price=open_trade.entry_price,
                        exit_price=price,
                        exit_timestamp=ts,
                        exit_reason=exit_reason,
                    )
                    result.trades.append(trade)
                    logger.debug(
                        "Exit  %s @ %.4f  [%s]  pnl=%.4f",
                        open_trade.signal.signal.value,
                        price,
                        exit_reason,
                        trade.pnl,
                    )
                    open_trade = None

            # ---- Strategy evaluation (only enter if no open position) ----
            if open_trade is None and len(price_window) >= self._history_window:
                signal = strategy.on_step(
                    timestamp=ts,
                    price=price,
                    book=book,
                    price_history=list(price_window),
                    book_history=list(book_window),
                )
                if signal is not None and signal.signal != Signal.HOLD:
                    open_trade = _OpenPosition(signal=signal, entry_price=price, bars_held=0)
                    logger.debug(
                        "Entry %s @ %.4f  conf=%.2f",
                        signal.signal.value,
                        price,
                        signal.confidence,
                    )

            if open_trade is not None:
                open_trade.bars_held += 1

        # Close any position still open at end of data (price_series already normalised)
        if open_trade is not None and price_series:
            last_price = price_series[-1]["price"]
            last_ts = price_series[-1]["ts"]
            trade = Trade(
                signal=open_trade.signal,
                entry_price=open_trade.entry_price,
                exit_price=last_price,
                exit_timestamp=last_ts,
                exit_reason="end_of_data",
            )
            result.trades.append(trade)

        return result


    def _fetch_data(
        self,
        market_id: str,
        start_ts: Any,
        end_ts: Any,
        resolution: str,
    ) -> tuple[dict, dict]:
        """Return (prices_by_label, books_by_label), reading from disk cache when available."""
        if self._cache_dir:
            key = _cache_key(market_id, start_ts, end_ts, resolution)
            cached = _cache_load(self._cache_dir, key)
            if cached:
                logger.info("Cache hit for %s @ %s", market_id, resolution)
                return cached["prices"], cached["books"]

        prices = self._client.get_prices(market_id, start_ts, end_ts, resolution)
        books = self._client.get_books(market_id, start_ts, end_ts, resolution)

        if self._cache_dir:
            _cache_save(self._cache_dir, key, {"prices": prices, "books": books})

        return prices, books


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

class _OpenPosition:
    __slots__ = ("signal", "entry_price", "bars_held")

    def __init__(self, signal: TradeSignal, entry_price: float, bars_held: int) -> None:
        self.signal = signal
        self.entry_price = entry_price
        self.bars_held = bars_held


def _check_exit(
    pos: _OpenPosition,
    current_price: float,
    stop_loss: float,
    take_profit: float,
    hold_periods: int,
) -> str | None:
    """Return the exit reason string if the position should be closed, else None."""
    is_buy = pos.signal.signal == Signal.BUY
    price_move = current_price - pos.entry_price
    directional_move = price_move if is_buy else -price_move

    if directional_move >= take_profit:
        return "take_profit"
    if directional_move <= -stop_loss:
        return "stop_loss"
    if pos.bars_held >= hold_periods:
        return "timeout"
    return None
