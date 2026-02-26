# Longshot Bias Strategy — Empirical Analysis

**Date:** 2026-02-26
**Data window:** 89 days (2025-11-29 → 2026-02-26)
**Universe:** 400 resolved Polymarket markets
**Methodology:** Hold-to-resolution backtest, first zone-entry per market

---

## 1. Background: What Is Longshot Bias?

Prediction market bettors systematically **over-weight unlikely outcomes** and
**under-weight likely ones**. This is the "longshot bias" — documented in horse
racing (Thaler & Ziemba 1988, Snowberg & Wolfers 2010) and later in
sports betting and prediction markets.

The practical implication:

- A market priced at **p = 0.20** (20% implied YES probability) actually resolves
  YES far less often than 20% of the time — the market is *overpriced*.
- A market priced at **p = 0.80** should (by theory) resolve YES *more* often than
  80% — but this effect is weaker and harder to trade cleanly.

**Strategy:** SELL YES tokens when price ≤ threshold (e.g., 0.35). Hold to
resolution. Win when the market resolves NO (token → $0); lose when YES (token → $1).

---

## 2. Testing Methodology

### Hold-to-resolution exits

Standard SL/TP backtests cannot evaluate this strategy: the edge is captured at
resolution (price → 0 or 1), not in short-term price movements. We used a dedicated
script (`examples/longshot_backtest.py`) that:

1. Fetches resolved markets from the past 89 days.
2. For each market, fetches the full price series at 1h resolution.
3. Detects the **first** bar where YES price enters the longshot zone (≤ threshold)
   using the same zone-entry state machine as `LongshotBiasStrategy`.
4. Classifies the resolution outcome from the **final 4 bars**: avg ≥ 0.90 → YES,
   avg ≤ 0.10 → NO; otherwise skip (market not yet resolved).
5. Computes P&L as: SELL at entry price p → win `+p` if NO, lose `-(1-p)` if YES.

### Filters applied

| Filter | Value | Reason |
|--------|-------|--------|
| `--first-entry-only` | on | One trade per market; avoids within-market correlation |
| `--sell-only` | on | Only SELL (longshot) signals; BUY (favorite) unreliable (see §5) |
| `--no-sports` | on | Excludes live-game markets where intra-game swings fake zone entries |
| min_price | 0.02 | Capture extreme longshots (e.g., p=0.03 candidates) |
| resolution classifier | avg last 4 bars ≥ 0.90 / ≤ 0.10 | Robustly identifies resolved markets |

---

## 3. Results by Threshold

All three runs: 400 markets, 89-day window, first-entry-only, sell-only, no-sports.

| Longshot threshold | Trades | Win% | Total P&L | Avg P&L/trade | Sharpe |
|--------------------|--------|------|-----------|---------------|--------|
| ≤ 0.25             | 69     | 89.9% | +4.29     | +0.062        | 0.489  |
| **≤ 0.35**         | **72** | **90.3%** | **+6.68** | **+0.093** | **0.614** |
| ≤ 0.40             | 72     | 91.7% | +7.68     | +0.107        | 0.647  |

**Key observations:**
- All three thresholds are profitable and show positive Sharpe.
- Wider threshold (0.40) gives slightly *better* results — markets at 0.35–0.40
  are also systematically overpriced, not just those below 0.35.
- Win rate is remarkably stable at ~90% across all thresholds.
- The edge is real but not enormous per trade (~0.07–0.11 probability pts average).

---

## 4. Calibration: Market-Implied vs. Observed Resolution Rate

*Using threshold = 0.35, first-entry-only, no-sports, 400 markets.*

| Price bucket | N trades | Market-implied YES% | Observed YES% | Edge |
|---|---|---|---|---|
| 0.02 – 0.10 | 39 | 6.0% | **0.0%** | −6.0 pp |
| 0.10 – 0.20 | 10 | 15.0% | **0.0%** | −15.0 pp |
| 0.20 – 0.35 | 23 | 27.5% | **4.3%** | −23.2 pp |

**Reading this table:** A market priced at 0.25 says "25% chance of YES." Empirically,
only 4.3% of markets priced 0.20–0.35 actually resolved YES. The market is charging
27.5¢ for a bet worth only 4.3¢ — a 23pp mismatch.

- The **0.20–0.35 bucket has the largest per-trade edge** (~23pp) and the largest
  absolute wins (~+0.27 per winning trade).
- The **0.02–0.10 bucket** has tiny per-trade P&L (~+0.05 avg) but near-perfect win
  rate. Many trades are needed to generate meaningful P&L.
- The **0.10–0.20 bucket** is the sweet spot: 0/10 resolved YES in this sample
  (though with only 10 trades, this could be sampling noise).

---

## 5. Favorite BUY: Why It Doesn't Work Here

The symmetric trade (BUY when price ≥ 0.65, expecting YES) showed poor results:

| Mode | Trades | Win% | P&L | Issue |
|------|--------|------|-----|-------|
| All entries, with sports | 85 | 23.5% | −34.05 | Dominated by intra-game spikes |
| First-entry-only, with sports | 7 | 57.1% | −0.78 | 4/4 sports losses |

**Root cause:** Live esports and football match markets regularly trade above 0.65
*during a game* when one side is ahead, then resolve to the other outcome. This
creates false BUY signals that lose almost entirely.

When the **no-sports** filter is applied, the remaining favorite BUY signals
(0.65–0.80 bucket, 7 trades, 57.1% win) are marginally above break-even but not
statistically meaningful at n=7.

**Bottom line:** The academic "favorites are underpriced" finding likely exists on
Polymarket, but it requires a **different entry condition** — e.g., market opens
above 0.65 rather than crossing into the zone during a live event. Not tested here.

---

## 6. Dominant P&L Drivers

Top profitable trades (threshold=0.35, first-entry-only, 400 markets):

| Entry | Market | Resolution | P&L |
|-------|--------|------------|-----|
| 0.350 | Will Russia capture all of Kupiansk by March 31? | NO | +0.334 |
| 0.350 | Will Central African Democratic Rally win most seats? | NO | +0.330 |
| 0.335 | Will Union for Central African Renewal win? | NO | +0.329 |
| 0.328 | Will Kwa Na Kwa win 2025 Central African election? | NO | +0.326 |
| 0.326 | Will Warner Bros (WBD) beat quarterly earnings? | NO | +0.326 |
| 0.309 | Will Justin Tucker sign with an NFL team? | NO | +0.289 |
| 0.313 | Ukraine election called by March 31, 2026? | NO | +0.279 |
| 0.290 | Will JD Vance's remarks not air? | NO | +0.264 |

Best performing market types: **political events**, **geopolitical outcomes**,
**quarterly earnings beats**, **SSA baby name rankings**.

Worst trade:
| Entry | Market | Resolution | P&L |
|-------|--------|------------|-----|
| 0.241 | Will Costa Rica 2026 election turnout exceed X%? | YES | −0.749 |

This was a longshot that *actually happened* — the resolution event occurred. The
remaining 71 trades returned +7.42pp combined.

---

## 7. What Works in Practice

### Signal generation

Monitor for markets (excluding live-game) where YES price is:
- In the **0.20–0.35 range**: best per-trade P&L, meaningful edge
- In the **0.10–0.20 range**: slightly less P&L but very high win rate
- Below **0.10**: near-certain win but tiny P&L per trade

The existing `market_screener.py` already identifies open markets; add a longshot
zone check (`price ≤ 0.35`) and use `rel_spread ≤ 15%` to ensure liquidity.

### Position management

- **No SL/TP needed** — hold to resolution. Intermediate price moves are noise.
- **Position sizing** must account for the tail risk: a 0.20-entry that resolves YES
  loses 0.80 (4× the typical win). Kelly-optimal size is small (< 5% of capital
  per trade given the ~10% loss rate and ~4× loss magnitude).
- **Max one trade per market** — multiple zone re-entries are highly correlated.

### Market type preferences

| Preferred | Avoid |
|-----------|-------|
| Political events (elections, geopolitical) | Live esports / match maps |
| Quarterly earnings beats | Crypto 5-min up/down markets |
| Long-duration "will X happen by DATE?" | Same-day sports outcomes |
| Celebrity / policy events | Intra-game props (first blood, kills) |

---

## 8. Limitations and Caveats

1. **Sample size:** 72 trades from 400 markets. Statistically, the 90% win rate
   has a 95% CI of roughly [81%, 96%] (Wilson interval). The Sharpe of 0.61 is
   encouraging but could shift meaningfully with more data.

2. **Survivorship / selection:** We only test markets that cleanly resolve to 0 or 1
   in our data window (final 4 bars avg ≤ 0.10 or ≥ 0.90). Markets that resolve
   ambiguously (still at 0.15 in our data) are excluded. This could bias results
   if ambiguous-resolution markets are systematically different.

3. **Mid-price execution:** P&L is computed at mid-price. Real execution on SELL
   signals hits the bid (lower price), reducing P&L by ~half the spread. At a
   typical 2–3pp spread for liquid markets, this costs ~1–1.5pp per trade, which
   materially reduces the ~7–9pp per-trade average.

4. **One-sided:** We do not trade favorites (BUY signals). A full strategy would
   need a robust favorite entry condition to capture that part of the bias too.

5. **Horizon risk:** Markets at 0.35 that resolve YES lose 0.65 per unit. One
   unexpected event (e.g., an unlikely election outcome) can wipe out many small wins.
   The Costa Rica example showed exactly this.

---

## 9. Next Steps

| Priority | Action |
|----------|--------|
| 1 | Integrate longshot screener into `market_screener.py` — flag markets in longshot zone |
| 2 | Test favorite BUY with "open above threshold" condition (not zone-crossing) |
| 3 | Run on broader universe (1000+ markets) and longer history to tighten CIs |
| 4 | Add spread cost to P&L model (currently uses mid-price, overestimates returns) |
| 5 | Implement Kelly-optimal position sizing given 90% win / 4× loss profile |
| 6 | Live paper-trading: use arbitrage_scanner.py pattern to monitor for zone entries |

---

## 10. Code Reference

| File | Purpose |
|------|---------|
| `examples/longshot_backtest.py` | Hold-to-resolution backtest (this analysis) |
| `polyautomate/analytics/strategies/longshot_bias.py` | Live strategy (zone-entry signals for the trading engine) |
| `examples/market_screener.py` | Finds tradeable open markets (add longshot filter here) |
| `examples/arbitrage_scanner.py` | Detects monotonicity violations in price ladders |

```bash
# Reproduce the main result:
python examples/longshot_backtest.py \
  --api-key $PMD_API_KEY \
  --first-entry-only --sell-only --no-sports \
  --longshot 0.35 --days 89 --universe 400 \
  --csv trades.csv

# Threshold sensitivity (run separately):
# --longshot 0.25  →  69 trades, 89.9% win, +4.29 P&L, Sharpe 0.489
# --longshot 0.35  →  72 trades, 90.3% win, +6.68 P&L, Sharpe 0.614  ← baseline
# --longshot 0.40  →  72 trades, 91.7% win, +7.68 P&L, Sharpe 0.647
```
