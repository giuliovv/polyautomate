"""
Longshot Bias Backtest — Hold-to-Resolution
============================================

Standard SL/TP backtests cannot properly evaluate the longshot bias strategy:
the edge is captured at resolution (when YES token settles at $1 or $0), not
in short-term price moves.  A 24-hour hold after zone-entry almost never
reaches the resolution that defines profit or loss.

This script tests the hypothesis directly:

  * Markets priced below ~0.35 (longshots) are OVERPRICED — they resolve YES
    less often than their price implies.  Selling them has positive EV.
  * Markets priced above ~0.65 (favorites) are UNDERPRICED — they resolve YES
    more often than their price implies.  Buying them has positive EV.

Exit model
----------
Every zone-entry trade is held until market resolution.  P&L is computed
from the entry mid-price and the final resolution price (~0.0 or ~1.0):

  BUY at p, resolves YES → P&L = 1.0 − p  (win)
  BUY at p, resolves NO  → P&L = −p        (loss)
  SELL at p, resolves NO  → P&L = p         (win)
  SELL at p, resolves YES → P&L = p − 1.0  (loss)

Window
------
Uses the full 89-day API window by default, scanning resolved markets to
accumulate enough trades for meaningful statistics.  The previous universe_scan
used only 30 days per market; here every resolved market contributes its entire
available price history.

Calibration output
------------------
Beyond P&L, the script produces a calibration table: for each 10-pp price
bucket, it shows the market-implied YES probability vs. the empirically
observed YES resolution rate.  A systematic gap is evidence of the bias.

Usage
-----
  python examples/longshot_backtest.py --api-key KEY
  python examples/longshot_backtest.py --api-key KEY --days 89 --universe 300
  python examples/longshot_backtest.py --api-key KEY --longshot 0.30 --favorite 0.70
  python examples/longshot_backtest.py --api-key KEY --first-entry-only --csv trades.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from polyautomate.clients.polymarketdata import PMDClient, PMDError


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# A resolved market's final bars should be very close to 0 or 1.
# We check the average of the last RESOLUTION_LOOKBACK bars to classify.
_RES_LOOKBACK = 4
_RES_YES_FLOOR = 0.90   # avg tail price ≥ this → resolved YES
_RES_NO_CEIL   = 0.10   # avg tail price ≤ this → resolved NO


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class LongshotTrade:
    slug:             str
    question:         str
    signal:           str    # "buy" (favorite) | "sell" (longshot)
    zone:             str    # "favorite" | "longshot"
    entry_price:      float  # mid-price at zone entry
    entry_ts:         int    # Unix timestamp
    resolution:       str    # "YES" | "NO"
    resolution_price: float  # final bar mid-price (~0.0 or ~1.0)

    pnl_gross:        float  # hold-to-resolution P&L at mid-price (no spread)
    half_spread:      float  # assumed half bid-ask spread subtracted from P&L
    pnl:              float  # net P&L after spread cost (= pnl_gross - half_spread)

    @property
    def win(self) -> bool:
        return self.pnl > 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Keywords that identify live-game / match-outcome markets where intra-game
# price swings create spurious zone entries unrelated to the longshot bias.
_SPORTS_KEYWORDS = (
    "map 1", "map 2", "map 3",          # esports map winners
    "game 1", "game 2", "game 3",        # esports game winners
    "first blood",                        # live esports props
    "total kills",                        # live esports over/under
    "game handicap", "map handicap",
    "games total",
    "win on ",                            # "Will X FC win on YYYY-MM-DD"
    " vs. ",                              # e.g. "Howard Bison vs. UNCW"
    " vs ",                               # match markets without period
    "up or down",                         # crypto 5-min markets
    "o/u ",                               # over/under sports
    "both teams to score",
    "spread:",
)


def _is_sports_market(question: str) -> bool:
    """Return True if the market looks like a live-game / match-outcome market."""
    q = question.lower()
    return any(kw in q for kw in _SPORTS_KEYWORDS)


def _parse_dt(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_ts(value: object) -> int:
    """Convert ISO-8601 string or unix int to unix int."""
    if isinstance(value, (int, float)):
        return int(value)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return 0


def _fetch_resolved_markets(
    client: PMDClient,
    universe_size: int,
    resolved_since: datetime,
    now: datetime,
) -> Iterator[dict]:
    """Yield markets whose end_date falls in [resolved_since, now]."""
    seen = 0
    for mkt in client.list_markets(
        end_date_max=now.isoformat(),
        sort="updated_at",
        order="desc",
        limit=universe_size * 3,
    ):
        end_date = _parse_dt(
            mkt.get("end_date") or mkt.get("endDate") or mkt.get("resolution_date")
        )
        if end_date is None:
            continue
        if end_date < resolved_since or end_date > now:
            continue
        yield mkt
        seen += 1
        if seen >= universe_size:
            break


def _determine_resolution(prices: list[float]) -> tuple[str, float]:
    """
    Classify the market outcome from the tail of its price series.

    Returns ("YES", final_price), ("NO", final_price), or ("ambiguous", final_price).
    """
    if len(prices) < 2:
        return "ambiguous", prices[-1] if prices else 0.5
    tail = prices[-_RES_LOOKBACK:]
    final = tail[-1]
    avg_tail = sum(tail) / len(tail)
    if avg_tail >= _RES_YES_FLOOR:
        return "YES", final
    if avg_tail <= _RES_NO_CEIL:
        return "NO", final
    return "ambiguous", final


def _scan_zone_entries(
    prices: list[float],
    timestamps: list[int],
    longshot_threshold: float,
    favorite_threshold: float,
    min_price: float,
    max_price: float,
    first_entry_only: bool,
) -> list[tuple[int, int, str, str]]:
    """
    Return list of (bar_index, timestamp, zone, signal) for each zone entry.

    Replicates LongshotBiasStrategy's zone-entry state machine exactly: only
    fires on the *first bar* entering a new zone (transition from outside the zone).
    """
    entries: list[tuple[int, int, str, str]] = []
    prev_zone: str | None = None

    for i, (price, ts) in enumerate(zip(prices, timestamps)):
        if price < min_price or price > max_price:
            prev_zone = None
            continue

        if price <= longshot_threshold:
            zone = "longshot"
        elif price >= favorite_threshold:
            zone = "favorite"
        else:
            zone = "neutral"

        old_prev = prev_zone
        prev_zone = zone

        # Only fire on transitions into longshot or favorite zones
        if zone == old_prev or zone == "neutral":
            continue

        signal = "sell" if zone == "longshot" else "buy"
        entries.append((i, ts, zone, signal))

        if first_entry_only:
            break

    return entries


# ---------------------------------------------------------------------------
# Core: scan one market
# ---------------------------------------------------------------------------

def scan_market(
    client: PMDClient,
    slug: str,
    question: str,
    bt_start: datetime,
    bt_end: datetime,
    *,
    resolution: str = "1h",
    longshot_threshold: float = 0.35,
    favorite_threshold: float = 0.65,
    min_price: float = 0.02,
    max_price: float = 0.98,
    first_entry_only: bool = False,
    half_spread: float = 0.01,
) -> list[LongshotTrade]:
    """
    Fetch price data for one resolved market and return zone-entry trades.

    The final few bars determine the resolution outcome; zone-entry signals
    are only scanned in the bars *before* those tail bars so we don't enter
    on the resolution spike itself.

    Spread model: attempts to fetch per-bar spread from /metrics.  Each
    trade uses the actual half-spread at its entry bar.  Falls back to the
    ``half_spread`` parameter if metrics are unavailable.
    """
    try:
        data = client.get_prices(slug, bt_start.isoformat(), bt_end.isoformat(), resolution)
    except PMDError:
        return []

    # Accept "Yes", "YES", or whatever label the API returns first
    pts = data.get("Yes") or data.get("YES") or next(iter(data.values()), [])
    if not pts:
        return []

    pts_sorted = sorted(pts, key=lambda x: _parse_ts(x.get("t", 0)))
    prices     = [float(p["p"]) for p in pts_sorted]
    timestamps = [_parse_ts(p.get("t", 0)) for p in pts_sorted]

    if len(prices) < _RES_LOOKBACK + 2:
        return []

    # Fetch actual bid-ask spread from /metrics; build ts → half_spread lookup.
    # Each metric bar's "spread" is the full bid-ask spread; we use half for
    # the one-way execution cost (mid → bid for SELL, mid → ask for BUY).
    spread_lookup: dict[int, float] = {}
    try:
        metrics = client.get_metrics(slug, bt_start.isoformat(), bt_end.isoformat(), resolution)
        for m in metrics:
            ts_m = _parse_ts(m.get("ts") or m.get("t", 0))
            sprd = m.get("spread")
            if sprd is not None:
                spread_lookup[ts_m] = float(sprd) / 2.0
    except PMDError:
        pass  # fall back to fixed half_spread for all bars

    # Classify the resolution outcome from the tail
    resolution_outcome, resolution_price = _determine_resolution(prices)
    if resolution_outcome == "ambiguous":
        return []

    # Only scan bars before the resolution tail (avoid entering on the spike)
    analysis_prices     = prices[:-_RES_LOOKBACK]
    analysis_timestamps = timestamps[:-_RES_LOOKBACK]

    entries = _scan_zone_entries(
        analysis_prices,
        analysis_timestamps,
        longshot_threshold,
        favorite_threshold,
        min_price,
        max_price,
        first_entry_only,
    )

    trades: list[LongshotTrade] = []
    for _idx, ts, zone, signal in entries:
        entry_price = analysis_prices[_idx]

        # Actual half-spread at this bar, or fall back to the fixed assumption.
        hs = spread_lookup.get(ts, half_spread)

        # Hold-to-resolution P&L.
        # Gross: computed at mid-price (no spread).
        # Net: execution hits the bid (SELL) or ask (BUY), costing hs.
        #   SELL at bid = mid - hs → pnl_net = pnl_gross - hs
        #   BUY  at ask = mid + hs → pnl_net = pnl_gross - hs
        if signal == "buy":
            pnl_gross = resolution_price - entry_price
        else:  # sell
            pnl_gross = -(resolution_price - entry_price)
        pnl_net = pnl_gross - hs

        trades.append(LongshotTrade(
            slug=slug,
            question=question,
            signal=signal,
            zone=zone,
            entry_price=entry_price,
            entry_ts=ts,
            resolution=resolution_outcome,
            resolution_price=resolution_price,
            pnl_gross=pnl_gross,
            half_spread=hs,
            pnl=pnl_net,
        ))

    return trades


# ---------------------------------------------------------------------------
# Calibration table
# ---------------------------------------------------------------------------

# (lo, hi, expected_action)  — "sell" if longshot zone, "buy" if favorite zone
_CALIBRATION_BUCKETS = [
    (0.02, 0.10, "sell"),
    (0.10, 0.20, "sell"),
    (0.20, 0.35, "sell"),
    (0.35, 0.50, "—"),
    (0.50, 0.65, "—"),
    (0.65, 0.80, "buy"),
    (0.80, 0.90, "buy"),
    (0.90, 0.98, "buy"),
]


def print_calibration(trades: list[LongshotTrade]) -> None:
    """
    For each price bucket, compare the market-implied YES probability with the
    observed YES resolution rate.

    Longshot bias predicts:
      - Buckets < 0.35 → observed YES% < implied% (markets overpriced → edge to SELL)
      - Buckets > 0.65 → observed YES% > implied% (markets underpriced → edge to BUY)
    """
    print(f"\n{'='*76}")
    print("Calibration Table: Market-Implied vs. Observed Resolution Rate")
    print(f"{'='*76}")
    print(
        f"  {'Bucket':>10}  {'N':>4}  {'Implied YES':>11}  "
        f"{'Observed YES':>12}  {'Edge':>8}  Signal"
    )
    print("  " + "-" * 66)

    for lo, hi, expected_action in _CALIBRATION_BUCKETS:
        bucket = [t for t in trades if lo <= t.entry_price < hi]
        if not bucket:
            continue

        n         = len(bucket)
        implied   = (lo + hi) / 2.0   # bucket midpoint
        n_yes     = sum(1 for t in bucket if t.resolution == "YES")
        observed  = n_yes / n
        edge      = observed - implied

        if edge > 0.05:
            flag = "★ BUY has edge"
        elif edge < -0.05:
            flag = "★ SELL has edge"
        else:
            flag = ""

        print(
            f"  {lo:.2f}–{hi:.2f}     {n:>4}  {implied:>11.1%}  "
            f"{observed:>12.1%}  {edge:>+8.1%}  {flag}"
        )

    print()
    print("  Theory: negative edge below 0.35 (longshots overpriced → SELL)")
    print("          positive edge above 0.65 (favorites underpriced → BUY)")


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _sharpe(pnls: list[float]) -> float:
    if len(pnls) < 2:
        return 0.0
    mean = sum(pnls) / len(pnls)
    var  = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
    std  = var ** 0.5
    return mean / std if std > 0 else 0.0


def print_aggregate(trades: list[LongshotTrade]) -> None:
    if not trades:
        print("  No trades generated.")
        return

    wins         = sum(1 for t in trades if t.win)
    total_gross  = sum(t.pnl_gross for t in trades)
    total_net    = sum(t.pnl for t in trades)
    total_spread = sum(t.half_spread for t in trades)
    avg_hs       = total_spread / len(trades)
    avg_net      = total_net / len(trades)
    sharpe       = _sharpe([t.pnl for t in trades])

    print(f"\n{'='*76}")
    print("Aggregate Results  (hold-to-resolution exits)")
    print(f"{'='*76}")
    print(f"  Total trades       : {len(trades)}")
    print(f"  Win rate           : {wins/len(trades):.1%}  ({wins}/{len(trades)})")
    print(f"  Gross P&L (mid)    : {total_gross:+.4f} probability pts")
    print(f"  Spread cost        : {-total_spread:+.4f}  (avg {avg_hs:.3f} half-spread × {len(trades)} trades)")
    print(f"  Net P&L            : {total_net:+.4f} probability pts")
    print(f"  Avg net P&L/trade  : {avg_net:+.4f}")
    print(f"  Sharpe ratio       : {sharpe:.3f}  (on net P&L)")

    # Breakdown by zone
    for label, subset in [
        ("Longshot SELL", [t for t in trades if t.zone == "longshot"]),
        ("Favorite  BUY", [t for t in trades if t.zone == "favorite"]),
    ]:
        if not subset:
            continue
        w = sum(1 for t in subset if t.win)
        p = sum(t.pnl for t in subset)
        print(
            f"  {label:<20}: {len(subset):>4} trades  "
            f"win={w/len(subset):.1%}  net_pnl={p:+.4f}  "
            f"sharpe={_sharpe([t.pnl for t in subset]):.3f}"
        )


def print_kelly(trades: list[LongshotTrade], longshot_threshold: float = 0.40) -> None:
    """
    Print Kelly-optimal position sizing recommendations.

    For a SELL at execution bid b = entry_price - half_spread:
      Win (NO resolution):  gain = b
      Loss (YES resolution): loss = 1 - b

    Kelly fraction of bankroll to commit as collateral per trade:
      f* = (p·b − q·(1−b)) / (b·(1−b))

    where p = empirical win rate, q = 1 − p, b = actual bid at entry.

    The ¼-Kelly column is the practical recommendation: it reduces variance
    by 75% while giving up only a modest fraction of expected growth.
    """
    sell_trades = [t for t in trades if t.zone == "longshot"]
    if not sell_trades:
        return

    n_total  = len(sell_trades)
    n_win    = sum(1 for t in sell_trades if t.win)
    p_win    = n_win / n_total
    q_lose   = 1.0 - p_win
    avg_hs   = sum(t.half_spread for t in sell_trades) / n_total
    using_real = any(t.half_spread != sell_trades[0].half_spread for t in sell_trades)
    spread_src = "actual from /metrics" if using_real else f"fixed {avg_hs:.3f}"

    print(f"\n{'='*76}")
    print("Kelly Position Sizing  (Longshot SELL signals)")
    print(f"{'='*76}")
    print(f"  Empirical win rate : {p_win:.1%}  ({n_win}/{n_total} trades)")
    print(f"  Half-spread source : {spread_src}  (avg {avg_hs:.3f})")
    print(f"  Formula            : f* = (p·b − q·(1−b)) / (b·(1−b))")
    print(f"                       b  = entry_price − half_spread (actual)")
    print()
    print(
        f"  {'Bucket':>10}  {'N':>4}  {'Win%':>6}  "
        f"{'Avg bid':>7}  {'Full Kelly':>10}  {'¼ Kelly':>8}  Note"
    )
    print("  " + "-" * 68)

    # Build Kelly buckets aligned to _CALIBRATION_BUCKETS but capped at the
    # actual longshot_threshold so no trades fall through the cracks.
    # e.g. with threshold=0.40 the (0.35, 0.50) calibration bucket is split
    # into (0.35, 0.40) and the rest is ignored.
    for lo, hi, _ in _CALIBRATION_BUCKETS:
        # Skip buckets entirely above the longshot threshold
        if lo >= longshot_threshold:
            continue
        # Cap the upper bound at the threshold (handles the partial bucket)
        hi_eff = min(hi, longshot_threshold)

        bucket = [t for t in sell_trades if lo <= t.entry_price < hi_eff]
        if not bucket:
            continue

        # Use per-trade actual bid for the Kelly formula
        avg_bid = sum(t.entry_price - t.half_spread for t in bucket) / len(bucket)
        if avg_bid <= 0:
            continue

        # Use bucket win rate if N ≥ 10, else overall
        if len(bucket) >= 10:
            p = sum(1 for t in bucket if t.win) / len(bucket)
            q = 1 - p
            src = "bucket"
        else:
            p = p_win
            q = q_lose
            src = "overall"

        denom = avg_bid * (1 - avg_bid)
        kelly = (p * avg_bid - q * (1 - avg_bid)) / denom if denom > 0 else 0.0
        kelly = max(0.0, kelly)
        quarter_kelly = kelly / 4.0

        label = f"{lo:.2f}–{hi_eff:.2f}"
        note  = f"({src} p={p:.0%})"
        print(
            f"  {label:>10}  {len(bucket):>4}  {p:.0%}     "
            f"{avg_bid:>7.3f}  {kelly:>10.1%}  {quarter_kelly:>8.1%}  {note}"
        )

    # Overall Kelly using per-trade actual bid
    avg_entry = sum(t.entry_price for t in sell_trades) / n_total
    avg_bid_all = sum(t.entry_price - t.half_spread for t in sell_trades) / n_total
    if avg_bid_all > 0:
        denom = avg_bid_all * (1 - avg_bid_all)
        k_all = max(0.0, (p_win * avg_bid_all - q_lose * (1 - avg_bid_all)) / denom)
        print()
        print(f"  Overall (avg entry={avg_entry:.3f}, avg bid={avg_bid_all:.3f})")
        print(f"    Full Kelly : {k_all:.1%} of bankroll per trade")
        print(f"    ¼ Kelly    : {k_all/4:.1%} of bankroll per trade  ← recommended")
        print()
        print("  Interpretation:")
        print("    Full Kelly maximises long-run growth but has extreme swings.")
        print("    ¼ Kelly is the practical standard: ~56% of full Kelly growth,")
        print("    ~75% reduction in variance.  Cap individual trades at 5% of")
        print("    bankroll regardless of formula output (single-event tail risk).")


def print_top_trades(trades: list[LongshotTrade], n: int = 15) -> None:
    if not trades:
        return
    print(f"\n{'='*76}")
    print(f"Top {n} Trades by |P&L|")
    print(f"{'='*76}")
    print(
        f"  {'#':>3}  {'Zone':>9}  {'Sig':>4}  "
        f"{'Entry':>6}  {'Res':>4}  {'P&L':>8}  Question"
    )
    print("  " + "-" * 74)
    for i, t in enumerate(
        sorted(trades, key=lambda x: abs(x.pnl), reverse=True)[:n], 1
    ):
        print(
            f"  {i:>3}  {t.zone:>9}  {t.signal:>4}  "
            f"{t.entry_price:>6.3f}  {t.resolution:>4}  "
            f"{t.pnl:>+8.4f}  {t.question[:40]}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Backtest longshot bias using hold-to-resolution exits"
    )
    p.add_argument("--api-key",  default=os.environ.get("PMD_API_KEY"),
                   help="polymarketdata.co API key (or set PMD_API_KEY)")
    p.add_argument("--days",     type=int,   default=89,
                   help="Scan markets resolved in the last N days (default: 89)")
    p.add_argument("--universe", type=int,   default=200,
                   help="Max resolved markets to scan (default: 200)")
    p.add_argument("--window",   type=int,   default=89,
                   help="Price history window per market in days (default: 89)")
    p.add_argument("--res",      default="1h",
                   choices=["10m", "1h", "6h"],
                   help="Price bar resolution (default: 1h)")
    p.add_argument("--longshot", type=float, default=0.35,
                   help="Longshot threshold: SELL when price ≤ this (default: 0.35)")
    p.add_argument("--favorite", type=float, default=0.65,
                   help="Favorite threshold: BUY when price ≥ this (default: 0.65)")
    p.add_argument("--first-entry-only", action="store_true",
                   help="Only take the first zone entry per market (avoids correlation)")
    p.add_argument("--sell-only", action="store_true",
                   help="Only take SELL (longshot) signals; skip favorite BUY signals")
    p.add_argument("--no-sports", action="store_true",
                   help="Skip live-game markets (esports, football, basketball match winners) "
                        "where intra-game price swings generate misleading zone entries")
    p.add_argument("--half-spread", type=float, default=0.01,
                   help="Half bid-ask spread subtracted from each trade's P&L to model "
                        "execution cost (default: 0.01 = 1 pp). SELL signals execute at "
                        "bid = mid − half_spread.")
    p.add_argument("--verbose",  action="store_true",
                   help="Print per-market progress")
    p.add_argument("--csv",      default=None,
                   help="Save all trades to a CSV file")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.api_key:
        print("ERROR: set --api-key or PMD_API_KEY")
        sys.exit(1)

    client = PMDClient(api_key=args.api_key)
    now    = datetime.now(timezone.utc)
    resolved_since = now - timedelta(days=args.days)

    print(f"Longshot Bias Backtest — Hold-to-Resolution")
    print(f"Resolved window  : {resolved_since.date()} → {now.date()} ({args.days}d)")
    print(f"Price history    : up to {args.window}d per market  @ {args.res}")
    print(f"Universe size    : {args.universe} markets")
    print(f"Thresholds       : longshot ≤ {args.longshot}  |  favorite ≥ {args.favorite}")
    entry_mode = "first entry per market" if args.first_entry_only else "all zone entries"
    signal_mode = "SELL only" if args.sell_only else "SELL + BUY"
    print(f"Entry mode       : {entry_mode}  |  signals: {signal_mode}")
    print(f"Sports filter    : {'on (skip live-game markets)' if args.no_sports else 'off'}")
    print(f"Half-spread      : {args.half_spread:.3f}  (execution cost per trade)")
    print()

    # ── Step 1: fetch resolved market list ──────────────────────────────────
    print("Fetching resolved market list…")
    markets = list(_fetch_resolved_markets(client, args.universe, resolved_since, now))
    print(f"  {len(markets)} resolved markets found.\n")

    if not markets:
        print("No resolved markets in window.  Try --days 89 or a wider universe.")
        return

    # ── Step 2: scan each market ─────────────────────────────────────────────
    all_trades: list[LongshotTrade] = []
    n_403 = n_ambiguous = n_no_data = 0

    for i, mkt in enumerate(markets, 1):
        slug     = mkt.get("slug") or mkt.get("id", "")
        question = mkt.get("question", slug)[:72]
        end_date = _parse_dt(
            mkt.get("end_date") or mkt.get("endDate") or mkt.get("resolution_date")
        )

        if not slug or end_date is None:
            continue

        # Optional: skip live-game markets whose intra-game price swings
        # create spurious zone entries not related to the longshot bias.
        full_question = mkt.get("question", slug)
        if args.no_sports and _is_sports_market(full_question):
            if args.verbose:
                print(f"  [{i:>3}/{len(markets)}]  {question[:52]:<52}  SKIP (sports/esports)")
            continue

        # Use now as bt_end so we see the final resolution price.
        # Markets often trade past their scheduled end_date before settling
        # to 0/1 on-chain; cutting at end_date misses that final movement.
        bt_end   = now
        bt_start = now - timedelta(days=args.window)

        if args.verbose:
            print(f"  [{i:>3}/{len(markets)}]  {question[:52]:<52}  ", end="", flush=True)

        try:
            trades = scan_market(
                client, slug, question,
                bt_start, bt_end,
                resolution=args.res,
                longshot_threshold=args.longshot,
                favorite_threshold=args.favorite,
                first_entry_only=args.first_entry_only,
                half_spread=args.half_spread,
            )
        except PMDError as e:
            if e.status_code == 403:
                n_403 += 1
                if args.verbose:
                    print("403 (plan limit)")
            else:
                if args.verbose:
                    print(f"ERROR {e}")
            continue
        except Exception as e:
            if args.verbose:
                print(f"ERROR {e}")
            continue

        # Optional: keep only SELL (longshot) signals
        if args.sell_only:
            trades = [t for t in trades if t.signal == "sell"]

        # scan_market returns [] for ambiguous or no-data markets
        if not trades:
            n_no_data += 1
            if args.verbose:
                print("—  (no zone entries or ambiguous resolution)")
            continue

        all_trades.extend(trades)

        if args.verbose:
            n_win   = sum(1 for t in trades if t.win)
            tot_pnl = sum(t.pnl for t in trades)
            zones   = ",".join(sorted({t.zone[0] for t in trades}))
            print(
                f"{len(trades)} trade(s)  win={n_win/len(trades):.0%}  "
                f"pnl={tot_pnl:+.4f}  [{zones}]"
            )

    print(f"\n  {len(all_trades)} total trades collected.")
    if n_403:
        print(f"  {n_403} markets skipped (HTTP 403 — outside plan data window).")

    # ── Step 3: results ──────────────────────────────────────────────────────
    print_aggregate(all_trades)
    print_calibration(all_trades)
    print_kelly(all_trades, longshot_threshold=args.longshot)
    print_top_trades(all_trades)

    # ── Step 4: optional CSV export ──────────────────────────────────────────
    if args.csv and all_trades:
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "slug", "question", "signal", "zone",
                "entry_price", "half_spread", "resolution", "resolution_price",
                "pnl_gross", "pnl_net", "win",
            ])
            for t in all_trades:
                w.writerow([
                    t.slug, t.question, t.signal, t.zone,
                    f"{t.entry_price:.4f}",
                    f"{t.half_spread:.4f}",
                    t.resolution,
                    f"{t.resolution_price:.4f}",
                    f"{t.pnl_gross:.6f}",
                    f"{t.pnl:.6f}",
                    int(t.win),
                ])
        print(f"\nTrades saved → {args.csv}")


if __name__ == "__main__":
    main()
