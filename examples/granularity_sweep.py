"""
Granularity sweep — compare WhaleWatcher across resolutions
============================================================

Runs the WhaleWatcher strategy at every supported resolution (1m, 10m, 1h, 6h)
on one or more markets, **scaling all time-based parameters proportionally** so
that the strategy always "looks back" the same wall-clock duration regardless of
bar width.

The key insight: at 1m resolution, ``trend_lookback=12`` means 12 *minutes*,
which is far too short for macro prediction markets.  This script normalises all
lookbacks to wall-clock hours (base at 1h) and scales accordingly:

    trend_lookback (bars) = BASE_TREND_HOURS × bars_per_hour
    stat_window    (bars) = BASE_STAT_HOURS  × bars_per_hour
    hold_periods   (bars) = BASE_HOLD_HOURS  × bars_per_hour

First run: fetches and caches each (market, resolution) pair — the cache
persists in ``.cache/backtest/`` so every subsequent run is instant.

Usage
-----
    # Basic: run on the Fed June rate-cut market
    python examples/granularity_sweep.py --api-key pk_live_...

    # Custom markets and Z threshold
    python examples/granularity_sweep.py \\
        --api-key pk_live_... \\
        --markets fed-rate-cut-by-june-2026-meeting ukraine-signs-peace-deal-with-russia-by-june-30 \\
        --days 89 --z 2.5

    # Pre-fetch data only (no backtest), useful before a long analysis session
    python examples/granularity_sweep.py --api-key pk_live_... --prefetch-only
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from polyautomate.analytics import BacktestEngine
from polyautomate.analytics.strategies.whale_watcher import WhaleWatcherStrategy
from polyautomate.clients.polymarketdata import PMDClient, PMDError

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_MARKETS = [
    "fed-rate-cut-by-june-2026-meeting",
    "fed-rate-cut-by-april-2026-meeting",
]

RESOLUTIONS = ["1m", "10m", "1h", "6h"]

# Wall-clock durations for parameter scaling (all in hours)
BASE_TREND_HOURS = 12   # trend_lookback window
BASE_STAT_HOURS  = 48   # rolling stat window for whale Z-score
BASE_HOLD_HOURS  = 24   # max hold before forced exit

# Bars-per-hour for each resolution
BARS_PER_HOUR: dict[str, float] = {
    "1m":  60.0,
    "10m":  6.0,
    "1h":   1.0,
    "6h":   1 / 6,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def scaled_params(resolution: str) -> tuple[int, int, int]:
    """Return (trend_lookback, stat_window, hold_periods) scaled to wall-clock."""
    bph = BARS_PER_HOUR[resolution]
    return (
        max(4,  int(BASE_TREND_HOURS * bph)),
        max(8,  int(BASE_STAT_HOURS  * bph)),
        max(4,  int(BASE_HOLD_HOURS  * bph)),
    )


def discover_token(client: PMDClient, slug: str) -> str:
    """Return 'Yes' or the first available token label for a market."""
    try:
        info = client.get_market(slug)
        tokens = info.get("tokens", [])
        labels = [t.get("outcome") or t.get("label", "") for t in tokens]
        return next((c for c in ("Yes", "YES") if c in labels), labels[0] if labels else "Yes")
    except PMDError:
        return "Yes"


def print_result_row(label: str, resolution: str, trend_lb: int, stat_win: int,
                     hold: int, r, *, show_ci: bool = True) -> None:
    ci = r.win_rate_ci
    ci_str = f"[{ci.lower:.0%},{ci.upper:.0%}]" if show_ci else ""
    print(
        f"  {label:<42} {resolution:<5} {trend_lb:>7} {stat_win:>8} {hold:>6}  "
        f"{r.n_trades:>4} {r.win_rate:>6.1%} {ci_str:<14} "
        f"{r.total_pnl:>+8.4f} {r.sharpe_ratio:>7.3f}"
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Compare WhaleWatcher across resolutions with proportional parameter scaling"
    )
    p.add_argument("--api-key", default=os.getenv("PMD_API_KEY", ""))
    p.add_argument("--markets", nargs="+", default=DEFAULT_MARKETS,
                   help="One or more market slugs")
    p.add_argument("--days", type=int, default=89,
                   help="Look-back window in days (default: 89, max 90)")
    p.add_argument("--resolutions", nargs="+", default=RESOLUTIONS,
                   choices=RESOLUTIONS, help="Resolutions to test")
    p.add_argument("--z", type=float, default=2.5,
                   help="Whale Z-score threshold (default: 2.5)")
    p.add_argument("--sl", type=float, default=0.04,
                   help="Stop-loss in probability points")
    p.add_argument("--tp", type=float, default=0.08,
                   help="Take-profit in probability points")
    p.add_argument("--prefetch-only", action="store_true",
                   help="Only pre-download and cache data, then exit")
    p.add_argument("--cache-dir", default=".cache/backtest")
    return p.parse_args()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    if not args.api_key:
        print("ERROR: set --api-key or PMD_API_KEY")
        sys.exit(1)

    client = PMDClient(api_key=args.api_key)
    engine = BacktestEngine(client, cache_dir=args.cache_dir)

    now      = datetime.now(timezone.utc)
    end_ts   = now.isoformat()
    days     = min(args.days, 89)   # API enforces 90-day cap
    start_ts = (now - timedelta(days=days)).isoformat()

    print(f"Window : {start_ts[:10]} → {end_ts[:10]}  ({days} days)")
    print(f"Markets: {', '.join(args.markets)}")
    print(f"Res    : {', '.join(args.resolutions)}")
    print()

    # ── Pre-fetch phase ────────────────────────────────────────────────────
    print("Pre-fetching data (cache misses only):")
    for slug in args.markets:
        for res in args.resolutions:
            try:
                engine.prefetch_data(slug, start_ts, end_ts, res)
            except PMDError as e:
                print(f"  [error]      {slug} @ {res}: {e}")

    if args.prefetch_only:
        print("\nPre-fetch complete.")
        return

    # ── Backtest phase ─────────────────────────────────────────────────────
    print()
    hdr = (f"  {'Market+Resolution':<48} {'Trend':>7} {'Stat':>8} {'Hold':>6}  "
           f"{'N':>4} {'Win%':>6} {'95% CI':<14} {'P&L':>8} {'Sharpe':>7}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    summary: list[tuple] = []

    for slug in args.markets:
        token = discover_token(client, slug)
        for res in args.resolutions:
            trend_lb, stat_win, hold = scaled_params(res)
            strat = WhaleWatcherStrategy(
                whale_z_threshold=args.z,
                trend_lookback=trend_lb,
                min_trend_move=0.02,
                min_whale_notional=500.0,
                stat_window=stat_win,
                imbalance_confirm=True,
            )
            label = f"{slug[:35]} [{token}]"
            try:
                r = engine.run(
                    strategy=strat,
                    market_id=slug,
                    token_label=token,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    resolution=res,
                    stop_loss=args.sl,
                    take_profit=args.tp,
                    hold_periods=hold,
                )
                print_result_row(label, res, trend_lb, stat_win, hold, r)
                summary.append((slug, res, r))
            except (PMDError, ValueError) as e:
                print(f"  {label:<42} {res:<5}  ERROR: {e}")

        print()   # blank line between markets

    # ── Best resolution per market ─────────────────────────────────────────
    print("=" * 100)
    print("Best resolution per market (by total P&L among runs with ≥1 trade):")
    print()
    for slug in args.markets:
        candidates = [(res, r) for (s, res, r) in summary if s == slug and r.n_trades > 0]
        if not candidates:
            print(f"  {slug}: no trades at any resolution")
            continue
        best_res, best_r = max(candidates, key=lambda x: x[1].total_pnl)
        print(f"  {slug}")
        print(f"    Best: {best_res}  —  {best_r.n_trades} trades, "
              f"{best_r.win_rate:.0%} win rate, P&L {best_r.total_pnl:+.4f}, "
              f"Sharpe {best_r.sharpe_ratio:.3f}")
    print()


if __name__ == "__main__":
    main()
