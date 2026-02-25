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
import time
from datetime import datetime, timezone
from typing import Any

from ..clients.polymarketdata import PMDClient
from .models import BacktestResult, Signal, Trade, TradeSignal
from .strategy import BaseStrategy

logger = logging.getLogger(__name__)


def _normalise_ts(value: Any) -> str:
    """
    Floor a timestamp to the nearest minute so cache keys are stable even
    when the caller uses datetime.now(), while still being correct for
    sub-hourly resolutions like "1m" and "10m".
    """
    if isinstance(value, (int, float)):
        # Unix: floor to minute boundary
        return str(int(value) // 60 * 60)
    s = str(value)
    # ISO-8601: chop to "YYYY-MM-DDTHH:MM" (drop seconds/tz)
    return s[:16]


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
        fee_rate: float = 0.0,
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
        fee_rate:
            Explicit taker fee charged on each leg of the trade (entry + exit),
            as a fraction of notional. Default 0.0.

            Bid-ask spread friction is now modelled directly: entries execute at
            the best ask (BUY) or best bid (SELL), and exits at the opposite side.
            This parameter covers only explicit platform fees on top of the spread.

            Polymarket fee reality (see docs.polymarket.com/trading/fees):
            - Macro / political / general markets: **no fee** → leave at 0.0
            - 5/15-min crypto markets: fee = shares × 0.25 × (p×(1-p))² → max ~1.56% at p=0.50
            - NCAAB / Serie A sports: fee = shares × 0.0175 × (p×(1-p)) → max ~0.44% at p=0.50

            The simplified flat model (fee_rate × notional per leg) is an approximation
            because the real formula is price-dependent.

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
                    exec_exit = _exit_exec_price(open_trade.signal.signal, book, price)
                    trade = Trade(
                        signal=open_trade.signal,
                        entry_price=open_trade.entry_price,
                        exit_price=exec_exit,
                        exit_timestamp=ts,
                        exit_reason=exit_reason,
                        fee_rate=fee_rate,
                    )
                    result.trades.append(trade)
                    logger.debug(
                        "Exit  %s mid=%.4f exec=%.4f  [%s]  pnl=%.4f",
                        open_trade.signal.signal.value,
                        price,
                        exec_exit,
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
                    exec_entry = _entry_exec_price(signal.signal, book, price)
                    open_trade = _OpenPosition(
                        signal=signal,
                        entry_price=exec_entry,
                        entry_mid=price,
                        bars_held=0,
                    )
                    logger.debug(
                        "Entry %s mid=%.4f exec=%.4f  conf=%.2f",
                        signal.signal.value,
                        price,
                        exec_entry,
                        signal.confidence,
                    )

            if open_trade is not None:
                open_trade.bars_held += 1

        # Close any position still open at end of data (price_series already normalised)
        if open_trade is not None and price_series:
            last_bar = price_series[-1]
            last_price = last_bar["price"]
            last_ts = last_bar["ts"]
            last_book = book_by_ts.get(last_ts, {"ts": last_ts, "bids": [], "asks": []})
            exec_exit = _exit_exec_price(open_trade.signal.signal, last_book, last_price)
            trade = Trade(
                signal=open_trade.signal,
                entry_price=open_trade.entry_price,
                exit_price=exec_exit,
                exit_timestamp=last_ts,
                exit_reason="end_of_data",
                fee_rate=fee_rate,
            )
            result.trades.append(trade)

        return result


    def prefetch_data(
        self,
        market_id: str,
        start_ts: Any,
        end_ts: Any,
        resolution: str,
        *,
        verbose: bool = True,
    ) -> bool:
        """
        Pre-download and cache price + book data for one market/resolution window.

        Returns True if data was fetched from the API (cache miss), False if
        already cached.  Prints a progress line when *verbose* is True so long
        fetches (e.g. 89 days at 1m) are visible.
        """
        if not self._cache_dir:
            raise RuntimeError("prefetch_data requires cache_dir to be set")

        key = _cache_key(market_id, start_ts, end_ts, resolution)
        if _cache_load(self._cache_dir, key) is not None:
            if verbose:
                print(f"  [cache hit]  {market_id} @ {resolution}")
            return False

        if verbose:
            print(f"  [fetching]   {market_id} @ {resolution} … ", end="", flush=True)
        t0 = time.monotonic()

        prices = self._client.get_prices(market_id, start_ts, end_ts, resolution)
        books  = self._client.get_books(market_id, start_ts, end_ts, resolution)

        _cache_save(self._cache_dir, key, {"prices": prices, "books": books})
        elapsed = time.monotonic() - t0
        n_bars = sum(len(v) for v in prices.values())
        if verbose:
            print(f"done  ({n_bars:,} bars, {elapsed:.0f}s)")
        return True

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


def _best_bid(book: dict) -> float | None:
    """Return the highest bid price from a book snapshot, or None if empty."""
    bids = book.get("bids", [])
    return float(bids[0][0]) if bids else None


def _best_ask(book: dict) -> float | None:
    """Return the lowest ask price from a book snapshot, or None if empty."""
    asks = book.get("asks", [])
    return float(asks[0][0]) if asks else None


def _entry_exec_price(signal: Signal, book: dict, mid: float) -> float:
    """
    Realistic entry execution price:
    - BUY  → pay the ask (taker lifting the offer)
    - SELL → receive the bid (taker hitting the bid)
    Falls back to mid-price when the relevant side of the book is empty.
    """
    if signal == Signal.BUY:
        return _best_ask(book) or mid
    return _best_bid(book) or mid


def _exit_exec_price(signal: Signal, book: dict, mid: float) -> float:
    """
    Realistic exit execution price (opposite side to entry):
    - BUY exit  → sell at the bid
    - SELL exit → buy back at the ask
    Falls back to mid-price when the relevant side of the book is empty.
    """
    if signal == Signal.BUY:
        return _best_bid(book) or mid
    return _best_ask(book) or mid


class _OpenPosition:
    __slots__ = ("signal", "entry_price", "entry_mid", "bars_held")

    def __init__(
        self,
        signal: TradeSignal,
        entry_price: float,
        entry_mid: float,
        bars_held: int,
    ) -> None:
        self.signal = signal
        self.entry_price = entry_price  # actual execution price (ask or bid)
        self.entry_mid = entry_mid      # mid-price at entry — used for exit triggers
        self.bars_held = bars_held


def _check_exit(
    pos: _OpenPosition,
    current_price: float,
    stop_loss: float,
    take_profit: float,
    hold_periods: int,
) -> str | None:
    """Return the exit reason string if the position should be closed, else None.

    Triggers are compared against the mid-price at entry (``pos.entry_mid``) so
    that stop/take-profit levels are defined in clean probability-point terms,
    independent of the bid-ask spread captured in the execution prices.
    """
    is_buy = pos.signal.signal == Signal.BUY
    price_move = current_price - pos.entry_mid
    directional_move = price_move if is_buy else -price_move

    if directional_move >= take_profit:
        return "take_profit"
    if directional_move <= -stop_loss:
        return "stop_loss"
    if pos.bars_held >= hold_periods:
        return "timeout"
    return None
