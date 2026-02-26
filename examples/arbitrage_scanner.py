"""
Arbitrage Scanner — Ladder Monotonicity Violations
====================================================

Many Polymarket events spawn a *ladder* of related binary markets that share
a logical ordering constraint:

  "above $X" markets (price thresholds)
      P("cap > $1T") >= P("cap > $2T") >= P("cap > $3T")
      because "cap > $2T" ⊂ "cap > $1T"

  "by DATE" / "before DATE" markets (deadline ladders)
      P("IPO by March") <= P("IPO by June") <= P("IPO by December")
      because a later deadline is strictly easier to satisfy

When market participants update prices at different speeds (e.g. after news
breaks), a higher-threshold market can momentarily trade *above* a lower one.
That gap is a risk-free arbitrage:

  Buy YES on "above $1T" @ p_lo
  Sell YES on "above $2T" @ p_hi   (where p_hi > p_lo — the violation)
  → guaranteed profit of (p_hi − p_lo) regardless of outcome

This script:
  1. Fetches open markets matching a search term (or all open markets)
  2. Groups them by slug prefix to find ladders
  3. Detects and quantifies monotonicity violations
  4. Prints actionable opportunities, sorted by profit margin

Usage
-----
  python examples/arbitrage_scanner.py [--api-key KEY] [--search TERM]
                                       [--candidates N] [--min-profit X]

Examples
--------
  # Scan all open markets for any ladder violations
  python examples/arbitrage_scanner.py

  # Focus on SpaceX IPO markets
  python examples/arbitrage_scanner.py --search "spacex ipo"

  # Only show violations with >= 2 pp guaranteed profit
  python examples/arbitrage_scanner.py --min-profit 0.02
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from polyautomate.clients.polymarketdata import PMDClient, PMDError


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class LadderMarket(NamedTuple):
    slug: str
    question: str
    sort_key: float   # numeric value extracted from slug (threshold or date)
    yes_price: float  # latest mid-price of YES token


class Violation(NamedTuple):
    buy_slug: str      # lower threshold / earlier deadline — should be priced HIGHER
    buy_price: float
    sell_slug: str     # higher threshold / later deadline — wrongly priced HIGHER
    sell_price: float
    guaranteed_profit: float  # sell_price - buy_price (risk-free if held to resolution)
    ladder_type: str   # "above" | "by_date"


# ---------------------------------------------------------------------------
# Ladder detection helpers
# ---------------------------------------------------------------------------

# Matches things like "1pt2t" → 1.2  or "1t" → 1.0  or "3t" → 3.0
_ABOVE_RE = re.compile(
    r"above[_-](\d+)(?:pt(\d+))?t",
    re.IGNORECASE,
)

# Matches things like "march-31-2026", "june-30-2026", "december-31-2026"
_MONTH_MAP = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
_DATE_RE = re.compile(
    r"(january|february|march|april|may|june|july|august|"
    r"september|october|november|december|jan|feb|mar|apr|"
    r"jun|jul|aug|sep|oct|nov|dec)[_-](\d{1,2})[_-](\d{4})",
    re.IGNORECASE,
)


def _extract_above_threshold(slug: str) -> float | None:
    """Return the '$X trillion' threshold from an 'above-Xt' slug, or None."""
    m = _ABOVE_RE.search(slug)
    if not m:
        return None
    whole = int(m.group(1))
    frac = int(m.group(2)) if m.group(2) else 0
    return whole + frac / 10.0


def _extract_date_ordinal(slug: str) -> float | None:
    """Return a sortable float (days since epoch) from a date in the slug, or None."""
    m = _DATE_RE.search(slug)
    if not m:
        return None
    month_name, day, year = m.group(1).lower(), int(m.group(2)), int(m.group(3))
    month = _MONTH_MAP.get(month_name)
    if not month:
        return None
    try:
        d = datetime(year, month, day, tzinfo=timezone.utc)
        return d.timestamp()
    except ValueError:
        return None


def _slug_prefix(slug: str) -> str:
    """
    Return a normalised group key for the slug.

    Strips trailing numeric suffixes (e.g. "-528", "-954") added by Polymarket
    for disambiguation, then removes the variable part so that all markets in
    the same ladder share a prefix.
    """
    # Remove trailing hash-like suffix: "-123" at end
    slug = re.sub(r"-\d{3,}$", "", slug)
    # Remove the "above-Xt" or "above-Xpt-Yt" token
    slug = _ABOVE_RE.sub("ABOVE", slug)
    # Remove a date token
    slug = _DATE_RE.sub("DATE", slug)
    return slug


# ---------------------------------------------------------------------------
# Core scanning logic
# ---------------------------------------------------------------------------

def fetch_current_prices(
    client: PMDClient,
    slugs: list[str],
) -> dict[str, float]:
    """Return {slug: yes_price} for each slug, using the most recent 2h bar."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=6)
    prices: dict[str, float] = {}
    for slug in slugs:
        try:
            data = client.get_prices(slug, start, now, "1h")
            pts = data.get("Yes") or data.get("YES") or []
            if pts:
                prices[slug] = pts[-1]["p"]
        except PMDError:
            pass
    return prices


def find_ladder_violations(
    markets: list[dict],
    prices: dict[str, float],
    min_profit: float = 0.005,
) -> list[Violation]:
    """
    Group markets into ladders and return all monotonicity violations.

    For *above* ladders: price must DECREASE as threshold INCREASES.
    For *by-date* ladders: price must INCREASE as deadline extends.
    """
    # Build per-market records
    records: list[tuple[str, str, float, float, str]] = []  # (slug, question, sort_key, price, kind)
    for m in markets:
        slug = m.get("slug", "")
        question = m.get("question", slug)
        price = prices.get(slug)
        if price is None:
            continue

        above = _extract_above_threshold(slug)
        if above is not None:
            records.append((slug, question, above, price, "above"))
            continue

        date_ord = _extract_date_ordinal(slug)
        if date_ord is not None:
            records.append((slug, question, date_ord, price, "by_date"))

    # Group by normalised prefix
    groups: dict[str, list[tuple[str, str, float, float, str]]] = {}
    for rec in records:
        key = _slug_prefix(rec[0])
        groups.setdefault(key, []).append(rec)

    violations: list[Violation] = []
    for group in groups.values():
        if len(group) < 2:
            continue

        kind = group[0][4]
        # Sort by sort_key ascending
        group.sort(key=lambda r: r[2])

        # Check consecutive pairs
        for i in range(len(group) - 1):
            lo_slug, lo_q, lo_key, lo_price, _ = group[i]
            hi_slug, hi_q, hi_key, hi_price, _ = group[i + 1]

            if kind == "above":
                # lower threshold (lo_key) should have HIGHER price
                if hi_price > lo_price + min_profit:
                    violations.append(Violation(
                        buy_slug=lo_slug,
                        buy_price=lo_price,
                        sell_slug=hi_slug,
                        sell_price=hi_price,
                        guaranteed_profit=hi_price - lo_price,
                        ladder_type="above",
                    ))
            else:  # by_date
                # earlier deadline (lo_key) should have LOWER price
                if lo_price > hi_price + min_profit:
                    violations.append(Violation(
                        buy_slug=hi_slug,
                        buy_price=hi_price,
                        sell_slug=lo_slug,
                        sell_price=lo_price,
                        guaranteed_profit=lo_price - hi_price,
                        ladder_type="by_date",
                    ))

    violations.sort(key=lambda v: v.guaranteed_profit, reverse=True)
    return violations


# ---------------------------------------------------------------------------
# Also scan for flat arb: any market where YES + NO < 1.00 (platform error)
# ---------------------------------------------------------------------------

def find_book_arb(
    client: PMDClient,
    slugs: list[str],
    min_profit: float = 0.005,
) -> list[tuple[str, float, float, float]]:
    """
    Detect markets where YES ask + NO ask < 1.0 (guaranteed profit if both
    are bought and held to resolution).

    Returns list of (slug, ask_yes, ask_no, profit).
    """
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=1)
    results = []
    for slug in slugs:
        try:
            book = client.get_book(slug)
            asks_yes = [float(a[0]) for a in book.get("asks", [])]
            bids_yes = [float(b[0]) for b in book.get("bids", [])]
            if not asks_yes or not bids_yes:
                continue
            ask_yes = min(asks_yes)
            bid_yes = max(bids_yes)
            # NO ask ≈ 1 - YES bid (someone selling NO = buying YES)
            ask_no = 1.0 - bid_yes
            total = ask_yes + ask_no
            if total < 1.0 - min_profit:
                profit = 1.0 - total
                results.append((slug, ask_yes, ask_no, profit))
        except (PMDError, AttributeError):
            pass
    results.sort(key=lambda r: r[3], reverse=True)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Scan Polymarket for ladder monotonicity arbitrage opportunities"
    )
    p.add_argument("--api-key", default=os.environ.get("PMD_API_KEY"),
                   help="polymarketdata.co API key (or set PMD_API_KEY)")
    p.add_argument("--search", default=None,
                   help="Free-text filter (e.g. 'spacex ipo', 'fed rate')")
    p.add_argument("--candidates", type=int, default=300,
                   help="Max markets to fetch (default: 300)")
    p.add_argument("--min-profit", type=float, default=0.005,
                   help="Minimum guaranteed profit to report (default: 0.5 pp)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.api_key:
        print("ERROR: set --api-key or PMD_API_KEY")
        sys.exit(1)

    client = PMDClient(api_key=args.api_key)
    now = datetime.now(timezone.utc)

    print(f"Fetching up to {args.candidates} open markets"
          + (f" matching '{args.search}'" if args.search else "") + "…")

    markets = [
        m for m in client.list_markets(
            search=args.search,
            sort="updated_at",
            order="desc",
            end_date_min=now.isoformat(),
            limit=args.candidates * 3,
        )
        if m.get("status") not in ("closed", "resolved")
    ][:args.candidates]

    print(f"  {len(markets)} open markets fetched.")

    # ---- Ladder violations ----
    print(f"\nFetching current prices for ladder analysis…")
    slugs = [m["slug"] for m in markets]
    prices = fetch_current_prices(client, slugs)
    print(f"  Prices fetched for {len(prices)}/{len(slugs)} markets.")

    violations = find_ladder_violations(markets, prices, min_profit=args.min_profit)

    print(f"\n{'='*72}")
    print("Ladder Monotonicity Violations")
    print(f"{'='*72}")
    if not violations:
        print(f"  No violations found (min_profit ≥ {args.min_profit:.1%}).")
    else:
        print(f"  {'Buy (underpriced)':<45}  {'p_buy':>6}  |  {'Sell (overpriced)':<45}  {'p_sell':>6}  {'profit':>7}  type")
        print("  " + "-" * 120)
        for v in violations:
            print(
                f"  BUY  {v.buy_slug[:43]:<43}  {v.buy_price:>6.4f}  |  "
                f"SELL {v.sell_slug[:43]:<43}  {v.sell_price:>6.4f}  "
                f"{v.guaranteed_profit:>+7.4f}  {v.ladder_type}"
            )

    # ---- Book-level arb ----
    print(f"\n{'='*72}")
    print("Book-Level Arb (YES ask + NO ask < 1.00)")
    print(f"{'='*72}")
    book_arb = find_book_arb(client, slugs[:50], min_profit=args.min_profit)
    if not book_arb:
        print(f"  None found.")
    else:
        for slug, a_yes, a_no, profit in book_arb:
            print(f"  {slug[:55]:<55}  ask_YES={a_yes:.4f}  ask_NO≈{a_no:.4f}  profit={profit:+.4f}")

    # ---- Summary ----
    print(f"\n{'='*72}")
    total = len(violations) + len(book_arb)
    if total == 0:
        print("No actionable arbitrage found right now.")
        print("Re-run immediately after major news events — violations appear")
        print("transiently when related markets update at different speeds.")
    else:
        print(f"{total} opportunity/ies found.")
        if violations:
            best = violations[0]
            print(f"\nBest: BUY {best.buy_slug} @ {best.buy_price:.4f}")
            print(f"      SELL {best.sell_slug} @ {best.sell_price:.4f}")
            print(f"      Guaranteed profit: {best.guaranteed_profit:+.4f} pp per unit")


if __name__ == "__main__":
    main()
