"""
Multi-Strategy Backtest Comparison
===================================

Runs three strategies side-by-side on the same market and prints a comparison
table.  Designed to address the low-signal-count problem of the pure
WhaleWatcherStrategy: RSI Mean Reversion and MACD Momentum typically generate
10-50× more trades over the same 90-day window.

Usage
-----
    export PMD_API_KEY="pk_live_..."
    python examples/multi_strategy_backtest.py

Or with explicit flags:
    python examples/multi_strategy_backtest.py --api-key pk_live_... \\
        --market us-recession-in-2025 --token YES --res 1h

Flags
-----
    --api-key   polymarketdata.co key (or set PMD_API_KEY env var)
    --market    Market slug or UUID (auto-discovers if omitted)
    --token     YES or NO (default: YES)
    --start     ISO-8601 start date (default: 90 days ago)
    --end       ISO-8601 end date   (default: now)
    --res       Resolution: 1m 10m 1h 6h 1d (default: 1h)
    --sl        Stop loss in probability points (default: 0.05)
    --tp        Take profit in probability points (default: 0.10)
    --hold      Max hold periods (default: 24)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from polyautomate.clients.polymarketdata import PMDClient, PMDError
from polyautomate.analytics import BacktestEngine, BacktestResult
from polyautomate.analytics.strategies.whale_watcher import WhaleWatcherStrategy
from polyautomate.analytics.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from polyautomate.analytics.strategies.macd_momentum import MACDMomentumStrategy


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Multi-strategy backtest comparison")
    p.add_argument("--api-key", default=os.getenv("PMD_API_KEY", ""))
    p.add_argument("--market", default=None)
    p.add_argument("--token", default="YES")
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    p.add_argument("--res", default="1h", choices=["1m", "10m", "1h", "6h", "1d"])
    p.add_argument("--sl", type=float, default=0.05, help="Stop loss (prob pts)")
    p.add_argument("--tp", type=float, default=0.10, help="Take profit (prob pts)")
    p.add_argument("--hold", type=int, default=24, help="Max hold periods")
    return p.parse_args()


def find_market(client: PMDClient) -> str:
    print("No --market specified; searching for a recently-updated market...")
    for market in client.list_markets(sort="updated_at", order="desc", limit=50):
        if market.get("status") in ("resolved", "closed"):
            slug = market.get("slug") or market.get("id")
            print(f"  Found: {market.get('question', slug)!r}  [{slug}]")
            return slug
    for market in client.list_markets(limit=1):
        return market.get("slug") or market["id"]
    raise RuntimeError("No markets found via API.")


def print_trades(result: BacktestResult) -> None:
    if not result.trades:
        print("  (no trades)")
        return
    header = f"  {'#':>3}  {'Dir':4}  {'Entry':>7}  {'Exit':>7}  {'P&L':>8}  {'Reason'}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for i, t in enumerate(result.trades, 1):
        print(
            f"  {i:>3}  {t.signal.signal.value:4}  "
            f"{t.entry_price:>7.4f}  {t.exit_price:>7.4f}  "
            f"{t.pnl:>+8.4f}  {t.exit_reason}"
        )


def main() -> None:
    args = parse_args()

    if not args.api_key:
        print("ERROR: API key required.  Set PMD_API_KEY or use --api-key.")
        sys.exit(1)

    client = PMDClient(api_key=args.api_key)

    try:
        health = client.health()
        print(f"API status : {health.get('status', 'ok')}")
        usage = client.usage()
        print(f"Plan       : {usage.get('plan')}  |  org: {usage.get('organization')}")
    except PMDError as exc:
        print(f"WARNING: Could not reach API ({exc})")

    market_id = args.market or find_market(client)

    now = datetime.now(timezone.utc)
    end_ts = args.end or now.isoformat()
    start_ts = args.start or (now - timedelta(days=90)).isoformat()

    print(f"\nMarket   : {market_id}")
    print(f"Token    : {args.token}")
    print(f"Range    : {start_ts[:10]} → {end_ts[:10]}")
    print(f"Interval : {args.res}")
    print(f"SL / TP  : {args.sl} / {args.tp}  |  hold: {args.hold} bars\n")

    engine = BacktestEngine(client, history_window=60)

    common = dict(
        market_id=market_id,
        token_label=args.token,
        start_ts=start_ts,
        end_ts=end_ts,
        resolution=args.res,
        stop_loss=args.sl,
        take_profit=args.tp,
        hold_periods=args.hold,
    )

    strategies = [
        # Whale: needs rare high-Z book events — few signals over 90 days
        WhaleWatcherStrategy(
            whale_z_threshold=3.0,
            trend_lookback=24,
            min_trend_move=0.02,
            min_whale_notional=500.0,
            stat_window=48,
            imbalance_confirm=True,
        ),
        # RSI base: fires whenever RSI crosses 30 / 70
        RSIMeanReversionStrategy(
            rsi_period=14,
            oversold_threshold=30.0,
            overbought_threshold=70.0,
        ),
        # RSI + Bollinger confirmation: fewer but higher-conviction signals
        RSIMeanReversionStrategy(
            rsi_period=14,
            oversold_threshold=35.0,
            overbought_threshold=65.0,
            bb_confirm=True,
            bb_z_min=1.0,
        ),
        # MACD base: every EMA crossover
        MACDMomentumStrategy(
            macd_fast=12,
            macd_slow=26,
            macd_signal_period=9,
        ),
        # MACD + momentum confirmation: only strong crossovers
        MACDMomentumStrategy(
            macd_fast=12,
            macd_slow=26,
            macd_signal_period=9,
            min_histogram=0.001,
            momentum_confirm=True,
            momentum_period=10,
        ),
        # RSI + trend filter: skip mean-reversion signals against the trend
        RSIMeanReversionStrategy(
            rsi_period=14,
            oversold_threshold=30.0,
            overbought_threshold=70.0,
            trend_filter=True,
            trend_lookback=24,
            trend_threshold=0.05,
        ),
        # MACD + trend filter: skip crossovers that contradict a strong trend
        MACDMomentumStrategy(
            macd_fast=12,
            macd_slow=26,
            macd_signal_period=9,
            trend_filter=True,
            trend_lookback=24,
            trend_threshold=0.05,
        ),
    ]

    results: list[BacktestResult] = []
    for strat in strategies:
        print(f"Running {strat.name} ({strat.params}) ...")
        try:
            r = engine.run(strategy=strat, **common)
            results.append(r)
        except (PMDError, ValueError) as exc:
            print(f"  ERROR: {exc}")

    # ---- Comparison table ----
    print("\n" + "=" * 78)
    print("Strategy Comparison")
    print("=" * 78)
    header = (
        f"  {'Strategy':<28}  {'Trades':>6}  {'Win%':>6}  "
        f"{'TotalP&L':>9}  {'AvgP&L':>8}  {'Sharpe':>7}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for r in results:
        label = r.strategy_name
        # Append a short param summary
        p = r.strategy_params
        if r.strategy_name == "RSIMeanReversion":
            tf = ",tf" if p.get("trend_filter") else ""
            label += f"(rsi={p.get('rsi_period')},bb={p.get('bb_confirm')}{tf})"
        elif r.strategy_name == "MACDMomentum":
            tf = ",tf" if p.get("trend_filter") else ""
            label += f"(mom={p.get('momentum_confirm')}{tf})"
        print(
            f"  {label:<28}  {r.n_trades:>6}  {r.win_rate:>6.1%}  "
            f"{r.total_pnl:>+9.4f}  {r.avg_pnl:>+8.4f}  {r.sharpe_ratio:>7.3f}"
        )

    # ---- Detailed trade logs ----
    print("\n" + "=" * 78)
    print("Detailed trade logs")
    print("=" * 78)
    for r in results:
        print(f"\n--- {r.strategy_name} ---")
        print_trades(r)

    # ---- RSI sensitivity scan ----
    print("\n" + "=" * 78)
    print("RSI sensitivity – varying oversold/overbought thresholds")
    print("=" * 78)
    print(f"  {'OS/OB':>7}  {'Trades':>6}  {'Win%':>6}  {'TotalP&L':>9}  {'Sharpe':>7}")
    print("  " + "-" * 44)
    for threshold in [20, 25, 30, 35, 40]:
        strat = RSIMeanReversionStrategy(
            rsi_period=14,
            oversold_threshold=float(threshold),
            overbought_threshold=float(100 - threshold),
        )
        try:
            r = engine.run(strategy=strat, **common)
            print(
                f"  {threshold:>3}/{100-threshold:<3}  {r.n_trades:>6}  {r.win_rate:>6.1%}  "
                f"{r.total_pnl:>+9.4f}  {r.sharpe_ratio:>7.3f}"
            )
        except (PMDError, ValueError) as exc:
            print(f"  {threshold}/{100-threshold}: ERROR – {exc}")

    # ---- MACD sensitivity scan ----
    print("\n" + "=" * 78)
    print("MACD sensitivity – varying fast/slow EMA periods")
    print("=" * 78)
    print(f"  {'Fast/Slow':>9}  {'Trades':>6}  {'Win%':>6}  {'TotalP&L':>9}  {'Sharpe':>7}")
    print("  " + "-" * 46)
    for fast, slow in [(8, 21), (12, 26), (5, 13), (10, 30)]:
        strat = MACDMomentumStrategy(macd_fast=fast, macd_slow=slow)
        try:
            r = engine.run(strategy=strat, **common)
            print(
                f"  {fast:>4}/{slow:<4}  {r.n_trades:>6}  {r.win_rate:>6.1%}  "
                f"{r.total_pnl:>+9.4f}  {r.sharpe_ratio:>7.3f}"
            )
        except (PMDError, ValueError) as exc:
            print(f"  {fast}/{slow}: ERROR – {exc}")


    # ---- Trend threshold sensitivity scan (RSI + trend filter) ----
    print("\n" + "=" * 78)
    print("Trend filter sensitivity – varying trend_threshold (RSI, 30/70)")
    print("=" * 78)
    print(f"  {'Threshold':>9}  {'Trades':>6}  {'Win%':>6}  {'TotalP&L':>9}  {'Sharpe':>7}")
    print("  " + "-" * 48)
    for thr in [0.02, 0.03, 0.05, 0.07, 0.10]:
        strat = RSIMeanReversionStrategy(
            rsi_period=14,
            oversold_threshold=30.0,
            overbought_threshold=70.0,
            trend_filter=True,
            trend_lookback=24,
            trend_threshold=thr,
        )
        try:
            r = engine.run(strategy=strat, **common)
            print(
                f"  {thr:>9.2f}  {r.n_trades:>6}  {r.win_rate:>6.1%}  "
                f"{r.total_pnl:>+9.4f}  {r.sharpe_ratio:>7.3f}"
            )
        except (PMDError, ValueError) as exc:
            print(f"  {thr}: ERROR – {exc}")


if __name__ == "__main__":
    main()
