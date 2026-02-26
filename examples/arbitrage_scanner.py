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

This script runs in two efficient steps:
  1. Fetch up to N market slugs (no per-market price calls yet).
  2. Group slugs into ladder families; only fetch prices for markets
     that belong to a group with ≥ 2 members.
     This reduces API calls from N → (ladder members only), making a
     2,000-market sweep practical.

Usage
-----
  python examples/arbitrage_scanner.py [--api-key KEY] [--search TERM]
                                       [--candidates N] [--min-profit X]

Examples
--------
  # Full sweep — all open markets
  python examples/arbitrage_scanner.py

  # Focus on SpaceX IPO markets
  python examples/arbitrage_scanner.py --search "spacex ipo"

  # Lower threshold to see near-violations
  python examples/arbitrage_scanner.py --min-profit 0.002
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from polyautomate.clients.polymarketdata import PMDClient, PMDError


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class Violation(NamedTuple):
    buy_slug: str      # should be priced higher — it's underpriced
    buy_price: float
    sell_slug: str     # wrongly priced higher — it's overpriced
    sell_price: float
    guaranteed_profit: float
    ladder_type: str   # "above" | "by_date"


# ---------------------------------------------------------------------------
# Slug pattern matching
# ---------------------------------------------------------------------------

# "above-1t", "above-1pt2t", "above-2pt4t"  → threshold in $T
_ABOVE_RE = re.compile(r"above[_-](\d+)(?:pt(\d+))?t", re.IGNORECASE)

# "march-31-2026", "dec-31-2027"
_MONTH_MAP = {
    "january": 1, "jan": 1, "february": 2, "feb": 2,
    "march": 3,   "mar": 3, "april": 4,    "apr": 4,
    "may": 5,     "june": 6,"jun": 6,      "july": 7,
    "jul": 7,     "august": 8,"aug": 8,    "september": 9,
    "sep": 9,     "october": 10,"oct": 10, "november": 11,
    "nov": 11,    "december": 12,"dec": 12,
}
_DATE_RE = re.compile(
    r"(january|february|march|april|may|june|july|august|"
    r"september|october|november|december|jan|feb|mar|apr|"
    r"jun|jul|aug|sep|oct|nov|dec)[_-](\d{1,2})[_-](\d{4})",
    re.IGNORECASE,
)

# Trailing disambiguation suffix added by Polymarket: "-528", "-1023" etc.
_DISAMBIG_RE = re.compile(r"-\d{3,}$")


def _extract_above(slug: str) -> float | None:
    m = _ABOVE_RE.search(slug)
    if not m:
        return None
    return int(m.group(1)) + (int(m.group(2)) / 10.0 if m.group(2) else 0.0)


def _extract_date_ord(slug: str) -> float | None:
    m = _DATE_RE.search(slug)
    if not m:
        return None
    month = _MONTH_MAP.get(m.group(1).lower())
    if not month:
        return None
    try:
        return datetime(int(m.group(3)), month, int(m.group(2)),
                        tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _ladder_key(slug: str) -> tuple[str, str, float] | None:
    """
    Return (group_key, kind, sort_value) if the slug is part of a ladder,
    or None if it has no recognisable ladder token.
    """
    clean = _DISAMBIG_RE.sub("", slug)

    above = _extract_above(clean)
    if above is not None:
        key = _ABOVE_RE.sub("__ABOVE__", clean)
        return key, "above", above

    date_ord = _extract_date_ord(clean)
    if date_ord is not None:
        key = _DATE_RE.sub("__DATE__", clean)
        return key, "by_date", date_ord

    return None


# ---------------------------------------------------------------------------
# Core: group → fetch prices → detect violations
# ---------------------------------------------------------------------------

def build_ladder_groups(
    markets: list[dict],
) -> dict[str, list[tuple[str, str, float, str]]]:
    """
    Return {group_key: [(slug, question, sort_value, kind), ...]}
    keeping only groups with ≥ 2 members (actual ladders).
    """
    groups: dict[str, list] = defaultdict(list)
    for m in markets:
        slug = m.get("slug", "")
        result = _ladder_key(slug)
        if result is not None:
            key, kind, sort_val = result
            groups[key].append((slug, m.get("question", slug), sort_val, kind))

    return {k: v for k, v in groups.items() if len(v) >= 2}


def fetch_prices_for_slugs(
    client: PMDClient,
    slugs: list[str],
    verbose: bool = True,
) -> dict[str, float]:
    """Fetch the most recent YES price for each slug."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=6)
    prices: dict[str, float] = {}
    for i, slug in enumerate(slugs):
        if verbose and i % 10 == 0 and i > 0:
            print(f"    … {i}/{len(slugs)} prices fetched", end="\r")
        try:
            data = client.get_prices(slug, start, now, "1h")
            pts = data.get("Yes") or data.get("YES") or []
            if pts:
                prices[slug] = pts[-1]["p"]
        except PMDError:
            pass
    if verbose:
        print(f"    … {len(slugs)}/{len(slugs)} prices fetched" + " " * 10)
    return prices


def find_violations(
    groups: dict[str, list[tuple[str, str, float, str]]],
    prices: dict[str, float],
    min_profit: float,
) -> list[Violation]:
    violations: list[Violation] = []

    for members in groups.values():
        kind = members[0][3]
        # Sort by sort_value ascending
        ordered = sorted(members, key=lambda r: r[2])

        for i in range(len(ordered) - 1):
            lo_slug, _, lo_key, _ = ordered[i]
            hi_slug, _, hi_key, _ = ordered[i + 1]
            lo_p = prices.get(lo_slug)
            hi_p = prices.get(hi_slug)
            if lo_p is None or hi_p is None:
                continue

            if kind == "above":
                # lower threshold → should be priced HIGHER
                if hi_p > lo_p + min_profit:
                    violations.append(Violation(lo_slug, lo_p, hi_slug, hi_p,
                                                hi_p - lo_p, "above"))
            else:  # by_date
                # earlier deadline → should be priced LOWER
                if lo_p > hi_p + min_profit:
                    violations.append(Violation(hi_slug, hi_p, lo_slug, lo_p,
                                                lo_p - hi_p, "by_date"))

    violations.sort(key=lambda v: v.guaranteed_profit, reverse=True)
    return violations


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _short(slug: str, n: int = 48) -> str:
    return slug if len(slug) <= n else slug[:n - 1] + "…"


def print_ladder_summary(
    groups: dict[str, list],
    prices: dict[str, float],
) -> None:
    """Print every discovered ladder with current prices."""
    print(f"\n{'='*72}")
    print(f"Discovered Ladders  ({len(groups)} families)")
    print(f"{'='*72}")
    for key, members in sorted(groups.items()):
        kind = members[0][3]
        ordered = sorted(members, key=lambda r: r[2])
        tag = "above-$X" if kind == "above" else "by-date"
        print(f"\n  [{tag}]  {_short(key, 60)}")
        prev_p = None
        for slug, question, sort_val, _ in ordered:
            p = prices.get(slug)
            p_str = f"{p:.4f}" if p is not None else "  N/A "
            arrow = ""
            if prev_p is not None and p is not None:
                if kind == "above" and p > prev_p:
                    arrow = "  *** VIOLATION"
                elif kind == "by_date" and p < prev_p:
                    arrow = "  *** VIOLATION"
            print(f"    {p_str}  {_short(slug, 55)}{arrow}")
            prev_p = p


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Scan Polymarket for ladder-monotonicity arbitrage"
    )
    p.add_argument("--api-key", default=os.environ.get("PMD_API_KEY"))
    p.add_argument("--search", default=None,
                   help="Free-text filter (e.g. 'spacex ipo')")
    p.add_argument("--candidates", type=int, default=2000,
                   help="Max open markets to scan (default: 2000)")
    p.add_argument("--min-profit", type=float, default=0.005,
                   help="Minimum guaranteed profit pp to flag (default: 0.5 pp)")
    p.add_argument("--show-ladders", action="store_true",
                   help="Print every discovered ladder even without violations")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.api_key:
        print("ERROR: set --api-key or PMD_API_KEY")
        sys.exit(1)

    client = PMDClient(api_key=args.api_key)
    now = datetime.now(timezone.utc)

    # ── Step 1: fetch market slugs (no prices yet) ──────────────────────────
    # Two-pass: sort by updated_at desc (recently active) AND created_at asc
    # (older standing markets).  Deduplicate by slug.  This ensures we catch
    # both newly-created ladders and older rungs that weren't recently traded.
    print(f"Step 1 — fetching up to {args.candidates} open market slugs (2 passes)…")
    seen: set[str] = set()
    markets: list[dict] = []
    per_pass = args.candidates
    for sort_field, order in [("updated_at", "desc"), ("created_at", "asc")]:
        for m in client.list_markets(
            search=args.search,
            sort=sort_field,
            order=order,
            end_date_min=now.isoformat(),
            limit=per_pass * 3,
        ):
            if m.get("status") in ("closed", "resolved"):
                continue
            slug = m.get("slug", "")
            if slug and slug not in seen:
                seen.add(slug)
                markets.append(m)
            if len(markets) >= per_pass * 2:
                break
    print(f"  {len(markets)} unique open markets.")

    # ── Step 2: group into ladder families ──────────────────────────────────
    print("Step 2 — detecting ladder families from slugs…")
    groups = build_ladder_groups(markets)
    ladder_slugs = [slug for members in groups.values() for slug, *_ in members]
    print(f"  {len(groups)} ladder families, {len(ladder_slugs)} markets to price.")

    if not groups:
        print("  No ladder families found — try a broader search or more candidates.")
        return

    # ── Step 3: fetch prices only for ladder members ─────────────────────────
    print("Step 3 — fetching current prices for ladder members…")
    prices = fetch_prices_for_slugs(client, ladder_slugs)
    priced = sum(1 for s in ladder_slugs if s in prices)
    print(f"  {priced}/{len(ladder_slugs)} prices obtained.")

    # ── Optional: show all ladders ───────────────────────────────────────────
    if args.show_ladders:
        print_ladder_summary(groups, prices)

    # ── Violations ──────────────────────────────────────────────────────────
    violations = find_violations(groups, prices, args.min_profit)

    print(f"\n{'='*72}")
    print(f"Violations  (min_profit ≥ {args.min_profit:.1%})")
    print(f"{'='*72}")

    if not violations:
        print("  None right now — markets are correctly priced at this moment.")
        print()
        print("  Tip: violations appear transiently (seconds to minutes) after news")
        print("  breaks when related markets update at different speeds.")
        print("  Run this script on a cron (every 1–5 min) to catch them in real time.")
    else:
        print(f"  {'BUY (underpriced)':<50}  p_buy  |  {'SELL (overpriced)':<50}  p_sell   profit  type")
        print("  " + "-" * 130)
        for v in violations:
            print(
                f"  {_short(v.buy_slug, 50):<50}  {v.buy_price:.4f}  |  "
                f"{_short(v.sell_slug, 50):<50}  {v.sell_price:.4f}  "
                f"{v.guaranteed_profit:+.4f}  {v.ladder_type}"
            )
        print(f"\n  {len(violations)} violation(s) — act immediately, these close fast.")


if __name__ == "__main__":
    main()
