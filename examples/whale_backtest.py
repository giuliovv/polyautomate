"""
Whale / Insider Watcher — example backtest
==========================================

Runs the WhaleWatcherStrategy over a resolved Polymarket market using
historical order book + price data from polymarketdata.co.

Usage
-----
    export PMD_API_KEY="pk_live_..."
    python examples/whale_backtest.py

Or pass the key directly:
    python examples/whale_backtest.py --api-key pk_live_...

Optional flags
--------------
    --market   Market slug or UUID (default: searches for a US politics market)
    --token    Token label to trade, e.g. YES or NO (default: YES)
    --start    ISO-8601 start date  (default: 90 days ago)
    --end      ISO-8601 end date    (default: now)
    --res      Resolution: 1m 10m 1h 6h 1d  (default: 1h)
    --z        Whale Z-score threshold       (default: 3.0)
    --lookback Trend lookback in bars        (default: 24)
    --hold     Max hold periods              (default: 24)
    --sl       Stop loss in pp               (default: 0.05)
    --tp       Take profit in pp             (default: 0.10)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

# Allow running from repo root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from polyautomate.clients.polymarketdata import PMDClient, PMDError
from polyautomate.analytics import BacktestEngine
from polyautomate.analytics.strategies.whale_watcher import WhaleWatcherStrategy


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Whale watcher backtest")
    p.add_argument("--api-key", default=os.getenv("PMD_API_KEY", ""), help="polymarketdata.co API key")
    p.add_argument("--market", default=None, help="Market slug or UUID")
    p.add_argument("--token", default="YES", help="Token label (default: YES)")
    p.add_argument("--start", default=None, help="Start timestamp (ISO-8601)")
    p.add_argument("--end", default=None, help="End timestamp (ISO-8601)")
    p.add_argument("--res", default="1h", choices=["1m", "10m", "1h", "6h", "1d"], help="Resolution")
    p.add_argument("--z", type=float, default=3.0, help="Whale Z-score threshold")
    p.add_argument("--lookback", type=int, default=24, help="Trend lookback in bars")
    p.add_argument("--hold", type=int, default=24, help="Max hold periods")
    p.add_argument("--sl", type=float, default=0.05, help="Stop loss (probability pts)")
    p.add_argument("--tp", type=float, default=0.10, help="Take profit (probability pts)")
    return p.parse_args()


def find_example_market(client: PMDClient) -> str:
    """Return the slug of the first resolved market we can find."""
    print("No --market specified; searching for a resolved market...")
    for market in client.list_markets(sort="updated_at", order="desc", limit=50):
        if market.get("status") in ("resolved", "closed"):
            slug = market.get("slug") or market.get("id")
            print(f"  Found: {market.get('question', slug)!r}  [{slug}]")
            return slug
    # Fall back to first market regardless of status
    for market in client.list_markets(limit=1):
        return market.get("slug") or market["id"]
    raise RuntimeError("No markets found via API.")


def print_trade_table(result) -> None:
    if not result.trades:
        print("  (no trades)\n")
        return
    header = f"  {'#':>3}  {'Signal':6}  {'Entry':>7}  {'Exit':>7}  {'P&L':>8}  {'Reason'}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for i, t in enumerate(result.trades, 1):
        print(
            f"  {i:>3}  {t.signal.signal.value:6}  "
            f"{t.entry_price:>7.4f}  {t.exit_price:>7.4f}  "
            f"{t.pnl:>+8.4f}  {t.exit_reason}"
        )
    print()


def main() -> None:
    args = parse_args()

    if not args.api_key:
        print("ERROR: API key is required.  Set PMD_API_KEY or use --api-key.")
        sys.exit(1)

    client = PMDClient(api_key=args.api_key)

    # ---- Check API health ----
    try:
        health = client.health()
        print(f"API status: {health.get('status', 'ok')}")
        usage = client.usage()
        print(f"Plan: {usage.get('plan')}  |  organisation: {usage.get('organization')}")
    except PMDError as exc:
        print(f"WARNING: Could not reach API ({exc})")

    # ---- Resolve market ----
    market_id = args.market or find_example_market(client)

    # ---- Time range defaults: last 90 days ----
    now = datetime.now(timezone.utc)
    end_ts = args.end or now.isoformat()
    start_ts = args.start or (now - timedelta(days=29)).isoformat()

    print(f"\nMarket  : {market_id}")
    print(f"Token   : {args.token}")
    print(f"Range   : {start_ts} → {end_ts}")
    print(f"Interval: {args.res}\n")

    # ---- Build strategy ----
    strategy = WhaleWatcherStrategy(
        whale_z_threshold=args.z,
        trend_lookback=args.lookback,
        min_trend_move=0.02,
        min_whale_notional=500.0,
        stat_window=max(args.lookback * 2, 20),
        imbalance_confirm=True,
    )

    # ---- Run backtest ----
    engine = BacktestEngine(client, history_window=max(args.lookback * 2, 48))

    try:
        result = engine.run(
            strategy=strategy,
            market_id=market_id,
            token_label=args.token,
            start_ts=start_ts,
            end_ts=end_ts,
            resolution=args.res,
            stop_loss=args.sl,
            take_profit=args.tp,
            hold_periods=args.hold,
        )
    except PMDError as exc:
        print(f"ERROR fetching data: {exc}")
        sys.exit(1)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    # ---- Print results ----
    print(result.summary())
    print()
    print("Trade log:")
    print_trade_table(result)

    # ---- Parameter sensitivity scan ----
    print("=" * 60)
    print("Parameter sensitivity – varying Z-score threshold:")
    print(f"  {'Z':>5}  {'Trades':>6}  {'Win%':>6}  {'Total P&L':>10}  {'Sharpe':>7}")
    print("  " + "-" * 44)
    for z in [2.0, 2.5, 3.0, 3.5, 4.0]:
        strat = WhaleWatcherStrategy(
            whale_z_threshold=z,
            trend_lookback=args.lookback,
            min_trend_move=0.02,
            min_whale_notional=500.0,
            stat_window=max(args.lookback * 2, 20),
            imbalance_confirm=True,
        )
        r = engine.run(
            strategy=strat,
            market_id=market_id,
            token_label=args.token,
            start_ts=start_ts,
            end_ts=end_ts,
            resolution=args.res,
            stop_loss=args.sl,
            take_profit=args.tp,
            hold_periods=args.hold,
        )
        print(
            f"  {z:>5.1f}  {r.n_trades:>6}  {r.win_rate:>6.1%}  "
            f"{r.total_pnl:>+10.4f}  {r.sharpe_ratio:>7.3f}"
        )


if __name__ == "__main__":
    main()
