"""
TP/SL Grid Sweep — find the best stop_loss × take_profit combination
=====================================================================

Runs the WhaleWatcher universe scan over a grid of (stop_loss, take_profit)
values with Polymarket's trading fee baked in, then prints a ranked table and
a heatmap so you can see which risk parameters actually survive friction.

Fee model
---------
Polymarket charges ~2% per leg (entry + exit).  The round-trip cost on a
position entered at price *p_in* and exited at *p_out* is:

    cost = fee_rate × (p_in + p_out)

This is already built into Trade.pnl when fee_rate > 0.  At 2% per side and
a typical entry price of 0.50, the round-trip drag is ~2 pp — which wipes out
a 2pp stop-loss outright.  The sweep makes this visible.

Grid defaults
-------------
    stop_loss  : 0.02, 0.03, 0.04, 0.05, 0.06
    take_profit: 0.06, 0.08, 0.10, 0.12, 0.15
    fee_rate   : 0.02  (fixed, Polymarket taker fee)

Usage
-----
    # Scan 200 resolved markets from the last 90 days
    python examples/tp_sl_sweep.py --api-key pk_live_...

    # Faster: fewer markets, shorter window
    python examples/tp_sl_sweep.py --api-key pk_live_... \\
        --universe 100 --window 14

    # Custom grid
    python examples/tp_sl_sweep.py --api-key pk_live_... \\
        --sl 0.03 0.04 0.05 --tp 0.08 0.10 0.12

    # No fee (compare with/without to see friction impact)
    python examples/tp_sl_sweep.py --api-key pk_live_... --fee 0.0

    # Save results to CSV
    python examples/tp_sl_sweep.py --api-key pk_live_... --csv sweep.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from polyautomate.clients.polymarketdata import PMDClient

# Import the scan machinery from universe_scan (reuses all market discovery)
from universe_scan import run_scan, ScanResult   # type: ignore[import]


# ── Grid defaults ──────────────────────────────────────────────────────────────

DEFAULT_SL  = [0.02, 0.03, 0.04, 0.05, 0.06]
DEFAULT_TP  = [0.06, 0.08, 0.10, 0.12, 0.15]
DEFAULT_FEE = 0.02


# ── Result aggregation ─────────────────────────────────────────────────────────

@dataclass
class GridPoint:
    sl: float
    tp: float
    fee_rate: float
    rr_ratio: float          # take_profit / stop_loss

    n_markets_triggered: int
    total_trades: int
    approx_win_rate: float   # weighted average across markets
    total_pnl: float
    avg_pnl_per_trade: float
    avg_sharpe: float        # mean of per-market Sharpe ratios


def _aggregate(results: list[ScanResult], sl: float, tp: float, fee: float) -> GridPoint:
    traded = [r for r in results if r.n_trades > 0]
    total_trades = sum(r.n_trades for r in traded)
    wins = sum(round(r.win_rate * r.n_trades) for r in traded)
    approx_wr = wins / total_trades if total_trades else 0.0
    total_pnl = sum(r.total_pnl for r in traded)
    avg_pnl = total_pnl / total_trades if total_trades else 0.0
    avg_sharpe = (sum(r.sharpe for r in traded) / len(traded)) if traded else 0.0

    return GridPoint(
        sl=sl,
        tp=tp,
        fee_rate=fee,
        rr_ratio=round(tp / sl, 2),
        n_markets_triggered=len(traded),
        total_trades=total_trades,
        approx_win_rate=approx_wr,
        total_pnl=total_pnl,
        avg_pnl_per_trade=avg_pnl,
        avg_sharpe=avg_sharpe,
    )


# ── Display ────────────────────────────────────────────────────────────────────

def _print_table(points: list[GridPoint], fee_rate: float) -> None:
    print(f"\n{'=' * 90}")
    print(f"TP/SL SWEEP RESULTS  (fee_rate={fee_rate:.1%} per leg, ~{fee_rate * 2:.1%} round-trip)")
    print(f"{'=' * 90}")
    hdr = (
        f"  {'SL':>5}  {'TP':>5}  {'R:R':>4}  "
        f"{'Trades':>6}  {'Mkts':>4}  {'WinRate':>7}  "
        f"{'TotalPnL':>9}  {'AvgPnL':>7}  {'AvgSharpe':>9}"
    )
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    # Sort by total P&L descending
    for gp in sorted(points, key=lambda x: -x.total_pnl):
        marker = "  ◄ best" if gp == max(points, key=lambda x: x.total_pnl) else ""
        print(
            f"  {gp.sl:>5.3f}  {gp.tp:>5.3f}  {gp.rr_ratio:>4.1f}  "
            f"{gp.total_trades:>6}  {gp.n_markets_triggered:>4}  "
            f"{gp.approx_win_rate:>7.1%}  "
            f"{gp.total_pnl:>+9.4f}  {gp.avg_pnl_per_trade:>+7.4f}  "
            f"{gp.avg_sharpe:>9.3f}"
            f"{marker}"
        )

    print()


def _print_heatmap(points: list[GridPoint], metric: str = "total_pnl") -> None:
    sl_vals = sorted(set(gp.sl for gp in points))
    tp_vals = sorted(set(gp.tp for gp in points))
    lookup = {(gp.sl, gp.tp): gp for gp in points}

    label = {"total_pnl": "Total P&L", "avg_pnl_per_trade": "Avg P&L/trade",
             "avg_sharpe": "Avg Sharpe"}[metric]

    print(f"HEATMAP — {label}  (rows=SL, cols=TP)")
    print()

    # Header row
    header = f"  {'SL\\TP':>6}"
    for tp in tp_vals:
        header += f"  {tp:>7.3f}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    all_vals = [getattr(lookup.get((sl, tp), GridPoint(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)), metric)
                for sl in sl_vals for tp in tp_vals]
    best_val = max(all_vals) if all_vals else 0.0

    for sl in sl_vals:
        row = f"  {sl:>6.3f}"
        for tp in tp_vals:
            gp = lookup.get((sl, tp))
            if gp is None:
                row += f"  {'  N/A':>7}"
            else:
                val = getattr(gp, metric)
                marker = "*" if abs(val - best_val) < 1e-9 else " "
                row += f"  {val:>+6.3f}{marker}"
        print(row)
    print()


def _save_csv(points: list[GridPoint], path: str) -> None:
    fields = [
        "sl", "tp", "fee_rate", "rr_ratio",
        "n_markets_triggered", "total_trades",
        "approx_win_rate", "total_pnl", "avg_pnl_per_trade", "avg_sharpe",
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for gp in sorted(points, key=lambda x: -x.total_pnl):
            w.writerow({k: getattr(gp, k) for k in fields})
    print(f"Sweep results saved → {path}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Grid sweep over stop_loss × take_profit for WhaleWatcher"
    )
    p.add_argument("--api-key",       default=os.getenv("PMD_API_KEY", ""))
    p.add_argument("--universe",      type=int, default=200,
                   help="Max resolved markets to scan (default: 200)")
    p.add_argument("--resolved-days", type=int, default=90,
                   help="How far back to look for resolved markets (default: 90)")
    p.add_argument("--window",        type=int, default=30,
                   help="Backtest window in days before each market's resolution (default: 30)")
    p.add_argument("--cache-dir",     default=".cache/backtest")
    p.add_argument("--sl",  nargs="+", type=float, default=DEFAULT_SL,
                   help="Stop-loss values to sweep (default: 0.02 0.03 0.04 0.05 0.06)")
    p.add_argument("--tp",  nargs="+", type=float, default=DEFAULT_TP,
                   help="Take-profit values to sweep (default: 0.06 0.08 0.10 0.12 0.15)")
    p.add_argument("--fee", type=float, default=DEFAULT_FEE,
                   help="Fee rate per leg (default: 0.02)")
    p.add_argument("--csv", default=None,
                   help="Save ranked results to a CSV file")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.api_key:
        print("ERROR: set --api-key or PMD_API_KEY")
        sys.exit(1)

    sl_values = sorted(set(args.sl))
    tp_values = sorted(set(args.tp))
    n_combos  = len(sl_values) * len(tp_values)

    print(f"TP/SL sweep: {len(sl_values)} SL values × {len(tp_values)} TP values = {n_combos} combos")
    print(f"SL: {sl_values}")
    print(f"TP: {tp_values}")
    print(f"Fee rate: {args.fee:.1%} per leg  ({args.fee * 2:.1%} round-trip)\n")

    client = PMDClient(api_key=args.api_key)

    # Discover markets once; the scan will use cache for backtest data.
    # We pass verbose=False for grid iterations 2+ so the output stays clean.
    grid_results: list[GridPoint] = []
    first_run = True

    for sl in sl_values:
        for tp in tp_values:
            print(f"  Running sl={sl:.3f}  tp={tp:.3f} …", end="", flush=True)
            scan = run_scan(
                client,
                universe_size=args.universe,
                resolved_days=args.resolved_days,
                window_days=args.window,
                cache_dir=args.cache_dir,
                verbose=first_run,     # only print market-level lines on first pass
                stop_loss=sl,
                take_profit=tp,
                fee_rate=args.fee,
            )
            gp = _aggregate(scan, sl, tp, args.fee)
            grid_results.append(gp)
            first_run = False
            print(f"  trades={gp.total_trades}  pnl={gp.total_pnl:+.4f}  "
                  f"win={gp.approx_win_rate:.0%}  sharpe={gp.avg_sharpe:.3f}")

    _print_table(grid_results, args.fee)
    _print_heatmap(grid_results, "total_pnl")
    _print_heatmap(grid_results, "avg_sharpe")

    if args.csv:
        _save_csv(grid_results, args.csv)

    # Summary advice
    best = max(grid_results, key=lambda x: x.total_pnl)
    best_sharpe = max(grid_results, key=lambda x: x.avg_sharpe)
    print("─" * 60)
    print("RECOMMENDATION")
    print("─" * 60)
    print(f"  Best P&L    : sl={best.sl:.3f}  tp={best.tp:.3f}  "
          f"rr={best.rr_ratio}  pnl={best.total_pnl:+.4f}")
    print(f"  Best Sharpe : sl={best_sharpe.sl:.3f}  tp={best_sharpe.tp:.3f}  "
          f"rr={best_sharpe.rr_ratio}  sharpe={best_sharpe.avg_sharpe:.3f}")
    if best.total_pnl <= 0:
        print()
        print("  ⚠  ALL combinations are unprofitable after fees.")
        print("     The strategy does not have a demonstrable edge at these parameters.")
        print("     Consider: lower fee markets, wider TP, or higher z-threshold.")


if __name__ == "__main__":
    main()
