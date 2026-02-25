"""
Universe Scan — WhaleWatcher across all recently resolved markets
=================================================================

Fetches every market that resolved in the past N days, runs the
WhaleWatcher backtest on the 30 days *before* resolution for each one,
and aggregates results.  The goal is two-fold:

1. **Volume**: get enough trades across diverse markets to draw
   statistically meaningful conclusions about the strategy.

2. **Correlation check**: group results by market category/tags.
   If all triggered trades cluster in one category (e.g. "US politics")
   the edge might not be real — it's just one correlated theme.

⚠  Parameter note
------------------
The screener weights and whale-strategy parameters were NOT determined
through any systematic search.  They are hand-picked priors.  This scan
is the first step toward an evidence-based view of what actually works.

Usage
-----
    # Scan markets resolved in the last 90 days (default)
    python examples/universe_scan.py --api-key pk_live_...

    # Faster: fewer candidates, shorter look-back per market
    python examples/universe_scan.py --api-key pk_live_... \\
        --universe 150 --window 14

    # Only show markets that actually generated trades
    python examples/universe_scan.py --api-key pk_live_... --triggered-only

    # Save a CSV of all results for offline analysis
    python examples/universe_scan.py --api-key pk_live_... --csv results.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from polyautomate.analytics import BacktestEngine
from polyautomate.analytics.strategies.whale_watcher import WhaleWatcherStrategy
from polyautomate.clients.polymarketdata import PMDClient, PMDError


# ── Strategy config (same as the 89-day sweep) ────────────────────────────────

STRATEGY_PARAMS = dict(
    whale_z_threshold=2.5,
    trend_lookback=12,      # 1h resolution: 12 bars = 12 hours
    min_trend_move=0.02,
    min_whale_notional=500.0,
    stat_window=48,         # 48 bars = 48 hours
    imbalance_confirm=True,
)
STOP_LOSS    = 0.04
TAKE_PROFIT  = 0.08
HOLD_PERIODS = 24           # max 24 bars = 24 hours

RESOLUTION   = "1h"


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class ScanResult:
    slug:        str
    question:    str
    tags:        list[str]
    end_date:    datetime | None

    n_trades:    int   = 0
    win_rate:    float = 0.0
    total_pnl:   float = 0.0
    sharpe:      float = 0.0
    exit_reasons: dict = field(default_factory=dict)

    error:       str   = ""
    skipped:     str   = ""   # reason if skipped before backtest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_dt(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _market_tags(mkt: dict) -> list[str]:
    tags = mkt.get("tags") or []
    if isinstance(tags, list):
        return [str(t) for t in tags]
    return []


def _discover_market_info(client: PMDClient, slug: str) -> tuple[str, datetime | None]:
    """Return (token_label, closed_at) for the market.

    closed_at is the actual resolution timestamp (more accurate than end_date
    for markets that resolve early, e.g. eSports games or news events).
    """
    try:
        info = client.get_market(slug)
        tokens = info.get("tokens", [])
        labels = [t.get("outcome") or t.get("label", "") for t in tokens]
        token = next((c for c in ("Yes", "YES") if c in labels),
                     labels[0] if labels else "Yes")
        closed_at = _parse_dt(info.get("closed_at"))
        return token, closed_at
    except PMDError:
        return "Yes", None


def _fetch_resolved_markets(
    client: PMDClient,
    universe_size: int,
    resolved_since: datetime,
    now: datetime,
) -> Iterator[dict]:
    """
    Yield active+resolved markets that ended between resolved_since and now.

    Strategy: fetch recently-updated markets with end_date_max=now, then
    filter in Python to those whose end_date falls in our window.
    We overfetch (3× the requested size) to compensate for markets outside
    the window being filtered out.
    """
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


# ── Core scan ──────────────────────────────────────────────────────────────────

def run_scan(
    client: PMDClient,
    *,
    universe_size: int = 200,
    resolved_days: int = 90,
    window_days: int = 30,
    cache_dir: str = ".cache/backtest",
    verbose: bool = True,
    stop_loss: float = STOP_LOSS,
    take_profit: float = TAKE_PROFIT,
    fee_rate: float = 0.0,
) -> list[ScanResult]:
    """
    Run WhaleWatcher on every resolved market from the last *resolved_days* days.

    For each market, the backtest window is *window_days* before the
    market's end_date (capped at start_date if available), ending 2 hours
    before resolution to avoid trading into the binary resolution spike.

    Parameters
    ----------
    stop_loss:   Exit threshold in probability points. Default: STOP_LOSS constant.
    take_profit: Exit threshold in probability points. Default: TAKE_PROFIT constant.
    fee_rate:    Round-trip fee per leg (e.g. 0.02 = 2% per side). Default: 0.0.
    """
    now           = datetime.now(timezone.utc)
    resolved_since = now - timedelta(days=resolved_days)

    engine = BacktestEngine(client, cache_dir=cache_dir)

    if verbose:
        fee_str = f"  fee={fee_rate:.1%}" if fee_rate else ""
        print(f"Scanning resolved markets: {resolved_since.date()} → {now.date()}")
        print(f"Backtest window per market: {window_days}d @ {RESOLUTION}")
        print(f"Strategy: WhaleWatcher  z={STRATEGY_PARAMS['whale_z_threshold']}  "
              f"sl={stop_loss}  tp={take_profit}  hold={HOLD_PERIODS}h{fee_str}\n")

    markets = list(_fetch_resolved_markets(client, universe_size, resolved_since, now))

    if verbose:
        print(f"Found {len(markets)} resolved markets in window.  Running backtests…\n")

    results: list[ScanResult] = []

    for i, mkt in enumerate(markets, 1):
        slug     = mkt.get("slug") or mkt.get("id", "")
        question = mkt.get("question", slug)[:80]
        tags     = _market_tags(mkt)
        end_date = _parse_dt(
            mkt.get("end_date") or mkt.get("endDate") or mkt.get("resolution_date")
        )

        sr = ScanResult(slug=slug, question=question, tags=tags, end_date=end_date)

        if not slug:
            sr.skipped = "no slug"
            results.append(sr)
            continue

        if end_date is None:
            sr.skipped = "no end_date"
            results.append(sr)
            continue

        token, _ = _discover_market_info(client, slug)

        # Use end_date (the scheduled close) as the backtest cutoff — this is
        # the only information available in live trading; closed_at is only
        # known after the fact and would introduce look-ahead bias.
        bt_end   = end_date - timedelta(hours=2)
        bt_start = bt_end - timedelta(days=window_days)
        if bt_end > now:
            bt_end = now
        if bt_start >= bt_end:
            sr.skipped = "window too short"
            results.append(sr)
            continue

        strat = WhaleWatcherStrategy(**STRATEGY_PARAMS)

        try:
            r = engine.run(
                strategy=strat,
                market_id=slug,
                token_label=token,
                start_ts=bt_start.isoformat(),
                end_ts=bt_end.isoformat(),
                resolution=RESOLUTION,
                stop_loss=stop_loss,
                take_profit=take_profit,
                hold_periods=HOLD_PERIODS,
                fee_rate=fee_rate,
            )
            sr.n_trades    = r.n_trades
            sr.win_rate    = r.win_rate
            sr.total_pnl   = r.total_pnl
            sr.sharpe      = r.sharpe_ratio
            sr.exit_reasons = r.exit_reason_breakdown()

        except PMDError as e:
            sr.error = str(e)
        except ValueError as e:
            sr.error = str(e)

        results.append(sr)

        if verbose:
            tag_str = ",".join(tags[:3]) or "—"
            if sr.error:
                status = f"ERROR: {sr.error[:40]}"
            elif sr.skipped:
                status = f"SKIP: {sr.skipped}"
            elif sr.n_trades == 0:
                status = "0 trades"
            else:
                status = (f"{sr.n_trades} trades  win={sr.win_rate:.0%}  "
                          f"pnl={sr.total_pnl:+.4f}  ★")
            end_str = end_date.strftime("%Y-%m-%d") if end_date else "?"
            print(f"  [{i:>3}/{len(markets)}]  {status:<40}  "
                  f"{question[:45]:<45}  [{tag_str}]  end={end_str}")

    return results


# ── Aggregation & reporting ────────────────────────────────────────────────────

def aggregate(results: list[ScanResult]) -> None:
    """Print summary statistics and the correlation diagnostic."""
    traded    = [r for r in results if r.n_trades > 0]
    errored   = [r for r in results if r.error]
    skipped   = [r for r in results if r.skipped]
    zero      = [r for r in results if not r.error and not r.skipped and r.n_trades == 0]

    total_trades = sum(r.n_trades for r in traded)
    all_pnl      = [r.total_pnl for r in traded]

    print("\n" + "=" * 80)
    print("UNIVERSE SCAN — SUMMARY")
    print("=" * 80)
    print(f"Markets attempted : {len(results)}")
    print(f"  Skipped (pre-bt): {len(skipped)}")
    print(f"  Errors          : {len(errored)}")
    print(f"  0-trade markets : {len(zero)}")
    print(f"  Triggered (≥1 ★): {len(traded)}")
    print(f"  Trigger rate    : {len(traded)/max(1,len(results)-len(skipped)-len(errored)):.1%}")
    print()

    if not traded:
        print("No trades generated across the entire universe.")
        return

    all_trade_pnls: list[float] = []
    all_wins = 0
    for r in traded:
        # We don't have per-trade data here, only aggregates — use win_rate × n as proxy
        all_wins += round(r.win_rate * r.n_trades)
        all_trade_pnls.append(r.total_pnl)

    print(f"Total trades      : {total_trades}")
    approx_win_rate = all_wins / total_trades if total_trades else 0
    print(f"Approx win rate   : {approx_win_rate:.1%}  ({all_wins}/{total_trades})")
    print(f"Sum P&L           : {sum(all_pnl):+.4f}")
    print(f"Avg P&L / market  : {sum(all_pnl)/len(traded):+.4f}")
    profitable = sum(1 for p in all_pnl if p > 0)
    print(f"Profitable markets: {profitable}/{len(traded)}")

    # ── Correlation diagnostic: breakdown by tag ───────────────────────────
    print()
    print("─" * 60)
    print("CORRELATION CHECK — triggered markets by tag")
    print("─" * 60)
    tag_counts: dict[str, int]   = defaultdict(int)
    tag_pnl:    dict[str, float] = defaultdict(float)
    untagged = 0
    for r in traded:
        if not r.tags:
            untagged += 1
            tag_counts["(untagged)"] += 1
            tag_pnl["(untagged)"]    += r.total_pnl
        for tag in r.tags:
            tag_counts[tag] += 1
            tag_pnl[tag]    += r.total_pnl

    for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1]):
        share = count / len(traded)
        print(f"  {tag:<35} {count:>3} markets  {share:>5.0%}  pnl={tag_pnl[tag]:+.4f}")

    concentration = max(tag_counts.values()) / len(traded) if traded else 0
    print()
    if concentration > 0.6:
        print(f"⚠  HIGH CORRELATION: top tag accounts for {concentration:.0%} of triggered markets.")
        print("   Results may reflect a single correlated theme, not a general edge.")
    elif concentration > 0.35:
        print(f"⚡ MODERATE CONCENTRATION: top tag is {concentration:.0%} of triggered markets.")
        print("   Worth checking whether all wins occurred on the same dates.")
    else:
        print(f"✓  Reasonable diversity: top tag is only {concentration:.0%} of triggered markets.")

    # ── Top triggered markets ──────────────────────────────────────────────
    print()
    print("─" * 60)
    print("TOP TRIGGERED MARKETS (by P&L)")
    print("─" * 60)
    hdr = f"  {'Rank':>4}  {'P&L':>8}  {'Win%':>5}  {'N':>3}  {'Sharpe':>6}  Question"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for rank, r in enumerate(sorted(traded, key=lambda x: -x.total_pnl)[:20], 1):
        tags_str = ",".join(r.tags[:2]) or "—"
        print(f"  {rank:>4}  {r.total_pnl:>+8.4f}  {r.win_rate:>5.1%}  "
              f"{r.n_trades:>3}  {r.sharpe:>6.3f}  "
              f"{r.question[:45]}  [{tags_str}]")


def save_csv(results: list[ScanResult], path: str) -> None:
    fields = [
        "slug", "question", "tags", "end_date",
        "n_trades", "win_rate", "total_pnl", "sharpe",
        "exit_reasons", "error", "skipped",
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow({
                "slug":         r.slug,
                "question":     r.question,
                "tags":         "|".join(r.tags),
                "end_date":     r.end_date.isoformat() if r.end_date else "",
                "n_trades":     r.n_trades,
                "win_rate":     f"{r.win_rate:.4f}",
                "total_pnl":    f"{r.total_pnl:.6f}",
                "sharpe":       f"{r.sharpe:.4f}",
                "exit_reasons": str(r.exit_reasons),
                "error":        r.error,
                "skipped":      r.skipped,
            })
    print(f"\nResults saved → {path}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Backtest WhaleWatcher on every recently-resolved Polymarket market"
    )
    p.add_argument("--api-key",       default=os.getenv("PMD_API_KEY", ""))
    p.add_argument("--universe",      type=int, default=200,
                   help="Max resolved markets to scan (default: 200)")
    p.add_argument("--resolved-days", type=int, default=90,
                   help="How far back to look for resolved markets (default: 90)")
    p.add_argument("--window",        type=int, default=30,
                   help="Backtest window in days before each market's resolution (default: 30)")
    p.add_argument("--cache-dir",     default=".cache/backtest")
    p.add_argument("--triggered-only", action="store_true",
                   help="Only print markets that generated ≥1 trade")
    p.add_argument("--csv",           default=None,
                   help="Save full results to a CSV file")
    p.add_argument("--quiet",         action="store_true",
                   help="Suppress per-market progress lines")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.api_key:
        print("ERROR: set --api-key or PMD_API_KEY")
        sys.exit(1)

    client = PMDClient(api_key=args.api_key)

    results = run_scan(
        client,
        universe_size=args.universe,
        resolved_days=args.resolved_days,
        window_days=args.window,
        cache_dir=args.cache_dir,
        verbose=not args.quiet,
    )

    if args.triggered_only:
        results = [r for r in results if r.n_trades > 0]

    aggregate(results)

    if args.csv:
        save_csv(results, args.csv)


if __name__ == "__main__":
    main()
