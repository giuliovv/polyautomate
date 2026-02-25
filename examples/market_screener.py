"""
Market Screener — find markets suited for WhaleWatcher
=======================================================

Queries active markets, scores each one across four dimensions, and
ranks them by a composite score so you know which ones are worth
running the whale-strategy backtest on.

Scoring dimensions
------------------
liquidity  (35%)  avg liquidity from /metrics over the look-back window.
                  Normalised against a reference of $5 000 (score = 1 at $5k+).
movement   (25%)  price range over the look-back window divided by a
                  reference move of 0.15 (15 pp).  Markets that never move
                  won't generate trend signals.
time       (20%)  days until resolution divided by 30.  Capped at 1.
                  Markets resolving in < 2 days are hard-filtered out.
position   (20%)  centrality of the current price: 1 at 0.50, 0 at 0.00/1.00.
                  Near-certain markets have thin books and no room for stops.

Hard filters (applied before scoring)
--------------------------------------
* status != active
* current_price < 0.04 or > 0.96  (near certainty)
* days_to_resolution < 2           (too close to resolution)
* fewer than 10 price bars in the look-back window (not enough data)
* avg bid-ask spread > max_spread  (default 3 pp).  Wide spreads make it
  structurally impossible to profit at typical TP levels (e.g. a 9 pp
  spread requires a 15 pp move to clear a 6 pp TP).

Usage
-----
    # Screen top-20 active markets
    python examples/market_screener.py --api-key pk_live_...

    # More candidates, longer look-back, custom weights
    python examples/market_screener.py --api-key pk_live_... \\
        --candidates 200 --days 14 --top 30

    # Print slug list only (pipe straight into granularity_sweep.py)
    python examples/market_screener.py --api-key pk_live_... --slugs-only

    # Filter to a topic
    python examples/market_screener.py --api-key pk_live_... --search "fed rate"
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from polyautomate.clients.polymarketdata import PMDClient, PMDError


# ── Scoring reference constants ────────────────────────────────────────────────

REF_LIQUIDITY   = 5_000.0   # USD — score = 1.0 at this avg liquidity
REF_MOVE        = 0.15      # prob points — score = 1.0 at this price range
REF_DAYS        = 30        # days — score = 1.0 at this time to resolution

# Default weight vector (must sum to 1)
W_LIQUIDITY = 0.35
W_MOVEMENT  = 0.25
W_TIME      = 0.20
W_POSITION  = 0.20

# Hard-filter thresholds
MIN_PRICE        = 0.04     # skip near-zero tokens
MAX_PRICE        = 0.96     # skip near-certain tokens
MIN_DAYS_LEFT    = 2        # skip markets resolving very soon
MIN_BARS         = 10       # skip markets with very little price history
MAX_SPREAD       = 0.03     # skip markets with avg bid-ask spread > 3 pp
MAX_REL_SPREAD   = 0.15     # skip if spread / price > 15 % (e.g. 2 pp on a
                            # 0.12 market = 17 % → structurally untradeable)


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class MarketScore:
    slug:            str
    question:        str
    end_date:        datetime | None
    current_price:   float
    price_range:     float          # max − min over look-back
    avg_liquidity:   float          # mean of /metrics liquidity values
    avg_spread:      float          # mean of /metrics spread values (probability pts)
    days_left:       float

    # Normalised sub-scores (all in [0, 1])
    s_liquidity:  float = 0.0
    s_movement:   float = 0.0
    s_time:       float = 0.0
    s_position:   float = 0.0
    composite:    float = 0.0

    # Any fetch error that occurred
    error: str = ""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_end_date(market: dict) -> datetime | None:
    """Extract and parse the market end/resolution date."""
    raw = (
        market.get("end_date")
        or market.get("endDate")
        or market.get("resolution_date")
        or market.get("resolutionDate")
    )
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _current_yes_price(prices_by_label: dict) -> float | None:
    """Return the most recent 'Yes' price from a prices dict."""
    for label in ("Yes", "YES"):
        bars = prices_by_label.get(label, [])
        if bars:
            return float(bars[-1].get("p") or bars[-1].get("price", 0))
    # Fall back to first available label
    for bars in prices_by_label.values():
        if bars:
            return float(bars[-1].get("p") or bars[-1].get("price", 0))
    return None


def _price_range(prices_by_label: dict) -> float:
    """Return the price range (max − min) across all bars and labels."""
    all_prices: list[float] = []
    for label in ("Yes", "YES"):
        bars = prices_by_label.get(label, [])
        all_prices.extend(
            float(b.get("p") or b.get("price", 0)) for b in bars
        )
    if not all_prices:
        for bars in prices_by_label.values():
            all_prices.extend(
                float(b.get("p") or b.get("price", 0)) for b in bars
            )
    if len(all_prices) < 2:
        return 0.0
    return max(all_prices) - min(all_prices)


def _bar_count(prices_by_label: dict) -> int:
    for label in ("Yes", "YES"):
        bars = prices_by_label.get(label, [])
        if bars:
            return len(bars)
    for bars in prices_by_label.values():
        return len(bars)
    return 0


def _avg_liquidity(metrics: list[dict]) -> float:
    """Average the 'liquidity' field from /metrics bars."""
    values = [float(m["liquidity"]) for m in metrics if "liquidity" in m]
    return sum(values) / len(values) if values else 0.0


def _avg_spread(metrics: list[dict]) -> float:
    """Average the 'spread' field from /metrics bars (bid-ask spread in prob pts)."""
    values = [float(m["spread"]) for m in metrics if "spread" in m]
    return sum(values) / len(values) if values else 0.0


def _score(ms: MarketScore) -> None:
    """Fill sub-scores and composite in-place."""
    ms.s_liquidity = min(1.0, ms.avg_liquidity / REF_LIQUIDITY)
    ms.s_movement  = min(1.0, ms.price_range   / REF_MOVE)
    ms.s_time      = min(1.0, ms.days_left      / REF_DAYS)
    ms.s_position  = 1.0 - abs(ms.current_price - 0.5) / 0.5
    ms.composite   = (
        W_LIQUIDITY * ms.s_liquidity
        + W_MOVEMENT  * ms.s_movement
        + W_TIME      * ms.s_time
        + W_POSITION  * ms.s_position
    )


# ── Core screening logic ───────────────────────────────────────────────────────

def screen_markets(
    client: PMDClient,
    *,
    candidates: int = 100,
    lookback_days: int = 7,
    search: str | None = None,
    tags: list[str] | None = None,
    max_spread: float = MAX_SPREAD,
    max_rel_spread: float = MAX_REL_SPREAD,
    verbose: bool = True,
) -> list[MarketScore]:
    """
    Fetch up to *candidates* active markets, score each one, and return a
    list of :class:`MarketScore` objects sorted best-first.

    Only markets that pass all hard filters are included.
    """
    now = datetime.now(timezone.utc)
    start_ts = (now - timedelta(days=lookback_days)).isoformat()
    end_ts   = now.isoformat()

    if verbose:
        print(f"Fetching up to {candidates} active markets…")

    # end_date_min=now: only return markets whose scheduled end is in the future
    # (avoids filling the list with recently-closed short-duration markets).
    # We still filter out early-resolved markets below via status check.
    market_list = [
        m for m in client.list_markets(
            search=search,
            tags=tags,
            sort="updated_at",
            order="desc",
            end_date_min=now.isoformat(),
            limit=candidates * 3,   # overfetch; many will be filtered
        )
        if m.get("status") not in ("closed", "resolved")
    ][:candidates]

    if verbose:
        print(f"Scoring {len(market_list)} open markets (look-back: {lookback_days}d @ 6h)…\n")

    results: list[MarketScore] = []

    for i, mkt in enumerate(market_list, 1):
        slug     = mkt.get("slug") or mkt.get("id", "")
        question = mkt.get("question", slug)[:80]
        end_date = _parse_end_date(mkt)

        # ── Time-to-resolution ──────────────────────────────────────────
        days_left: float
        if end_date:
            days_left = max(0.0, (end_date - now).total_seconds() / 86_400)
        else:
            days_left = 999.0   # unknown — don't penalise

        # Hard filter: resolves too soon
        if days_left < MIN_DAYS_LEFT:
            if verbose:
                print(f"  [{i:>3}] SKIP  {question[:55]}  (resolves in {days_left:.1f}d)")
            continue

        # ── Price data ──────────────────────────────────────────────────
        try:
            prices = client.get_prices(slug, start_ts, end_ts, "6h")
        except PMDError as e:
            if verbose:
                print(f"  [{i:>3}] ERROR {question[:55]}  ({e})")
            results.append(MarketScore(
                slug=slug, question=question, end_date=end_date,
                current_price=0.5, price_range=0.0,
                avg_liquidity=0.0, days_left=days_left,
                error=str(e),
            ))
            continue

        n_bars = _bar_count(prices)
        if n_bars < MIN_BARS:
            if verbose:
                print(f"  [{i:>3}] SKIP  {question[:55]}  (only {n_bars} bars)")
            continue

        current_price = _current_yes_price(prices)
        if current_price is None:
            continue

        # Hard filter: near certainty
        if current_price < MIN_PRICE or current_price > MAX_PRICE:
            if verbose:
                print(f"  [{i:>3}] SKIP  {question[:55]}  (price={current_price:.2f})")
            continue

        price_range = _price_range(prices)

        # ── Metrics (liquidity + spread) ────────────────────────────────
        try:
            metrics = client.get_metrics(slug, start_ts, end_ts, "6h")
            avg_liq = _avg_liquidity(metrics)
            avg_sprd = _avg_spread(metrics)
        except PMDError:
            avg_liq  = 0.0
            avg_sprd = 0.0

        # Hard filter: spread too wide to be tradeable at typical TP levels
        if avg_sprd > max_spread:
            if verbose:
                print(f"  [{i:>3}] SKIP  {question[:55]}  "
                      f"(spread={avg_sprd:.3f} > {max_spread:.3f})")
            continue

        # Hard filter: spread too large relative to current price.
        # A 2.7 pp spread on a 0.15 market = 18 % round-trip cost vs the
        # Yes price, which makes it structurally impossible to profit even
        # when the signal is right (e.g. TP=8 pp but spread consumes half).
        # Use min(p, 1-p) so both the Yes side and No side are checked;
        # the cheaper token is the one with the worst relative spread.
        rel_spread = avg_sprd / min(current_price, 1 - current_price)
        if rel_spread > max_rel_spread:
            if verbose:
                print(f"  [{i:>3}] SKIP  {question[:55]}  "
                      f"(rel_spread={rel_spread:.2%} > {max_rel_spread:.0%})")
            continue

        ms = MarketScore(
            slug=slug,
            question=question,
            end_date=end_date,
            current_price=current_price,
            price_range=price_range,
            avg_liquidity=avg_liq,
            avg_spread=avg_sprd,
            days_left=days_left,
        )
        _score(ms)
        results.append(ms)

        if verbose:
            end_str = end_date.strftime("%Y-%m-%d") if end_date else "unknown"
            print(
                f"  [{i:>3}]  {ms.composite:.3f}  {question[:48]:<48}  "
                f"p={current_price:.2f}  rng={price_range:.3f}  "
                f"sprd={avg_sprd:.3f}  liq=${avg_liq:>8,.0f}  end={end_str}"
            )

    # Sort by composite score descending; errors go last
    results.sort(key=lambda x: (not x.error, x.composite), reverse=True)
    return results


# ── Output helpers ─────────────────────────────────────────────────────────────

def print_table(scores: list[MarketScore], top: int) -> None:
    shown = [s for s in scores if not s.error][:top]
    if not shown:
        print("No markets passed all filters.")
        return

    hdr = (
        f"  {'#':>3}  {'Score':>5}  {'Liq':>4}  {'Mov':>4}  {'Time':>4}  {'Pos':>4}  "
        f"{'Price':>5}  {'Range':>5}  {'Spread':>6}  {'DaysLeft':>8}  Question"
    )
    print("\n" + "=" * len(hdr))
    print("Top markets for WhaleWatcher")
    print("=" * len(hdr))
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    for rank, ms in enumerate(shown, 1):
        end_str = ms.end_date.strftime("%Y-%m-%d") if ms.end_date else "  unknown"
        print(
            f"  {rank:>3}  {ms.composite:.3f}  "
            f"{ms.s_liquidity:.2f}  {ms.s_movement:.2f}  "
            f"{ms.s_time:.2f}  {ms.s_position:.2f}  "
            f"{ms.current_price:>5.2f}  {ms.price_range:>5.3f}  "
            f"{ms.avg_spread:>6.3f}  {ms.days_left:>8.1f}  {ms.question[:55]}"
        )

    print()
    print("Columns: Score=composite  Liq/Mov/Time/Pos=sub-scores (0–1)  Spread=avg bid-ask (pp)")
    print(f"Weights: liquidity={W_LIQUIDITY}  movement={W_MOVEMENT}  "
          f"time={W_TIME}  position={W_POSITION}  |  "
          f"hard filters: spread≤{MAX_SPREAD:.2f}  rel_spread≤{MAX_REL_SPREAD:.0%}")


def print_slugs(scores: list[MarketScore], top: int) -> None:
    for ms in [s for s in scores if not s.error][:top]:
        print(ms.slug)


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Score and rank Polymarket markets for WhaleWatcher suitability"
    )
    p.add_argument("--api-key",    default=os.getenv("PMD_API_KEY", ""))
    p.add_argument("--candidates", type=int, default=100,
                   help="Number of markets to fetch from the API (default: 100)")
    p.add_argument("--days",       type=int, default=7,
                   help="Look-back window in days for price/liquidity data (default: 7)")
    p.add_argument("--top",        type=int, default=20,
                   help="Number of top markets to show in the final table (default: 20)")
    p.add_argument("--search",     default=None,
                   help="Free-text filter applied when listing markets")
    p.add_argument("--tags",       nargs="+", default=None,
                   help="Tag filter(s) e.g. --tags politics economics")
    p.add_argument("--max-spread", type=float, default=MAX_SPREAD,
                   help=f"Hard filter: skip markets with avg bid-ask spread > this "
                        f"(probability pts, default: {MAX_SPREAD})")
    p.add_argument("--max-rel-spread", type=float, default=MAX_REL_SPREAD,
                   help=f"Hard filter: skip if spread / price > this fraction "
                        f"(default: {MAX_REL_SPREAD:.0%})")
    p.add_argument("--slugs-only", action="store_true",
                   help="Print only the top market slugs (one per line) — "
                        "useful for piping into granularity_sweep.py")
    p.add_argument("--quiet",      action="store_true",
                   help="Suppress per-market progress lines")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.api_key:
        print("ERROR: set --api-key or PMD_API_KEY")
        sys.exit(1)

    client = PMDClient(api_key=args.api_key)

    scores = screen_markets(
        client,
        candidates=args.candidates,
        lookback_days=args.days,
        search=args.search,
        tags=args.tags,
        max_spread=args.max_spread,
        max_rel_spread=args.max_rel_spread,
        verbose=not args.quiet and not args.slugs_only,
    )

    if args.slugs_only:
        print_slugs(scores, args.top)
    else:
        print_table(scores, args.top)


if __name__ == "__main__":
    main()
