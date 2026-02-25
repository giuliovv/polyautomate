# Universe Scan Findings

**Date:** 2026-02-25
**Script:** `examples/universe_scan.py`
**Raw CSV:** `analysis/universe_scan_results.csv`

---

## Run Parameters

```
Universe size    : 200 markets (sorted by updated_at desc)
Resolved window  : 2025-11-27 → 2026-02-25 (90 days)
Backtest window  : 30 days before each market's end_date
Resolution       : 1h
Strategy         : WhaleWatcher z=2.5, sl=0.04, tp=0.08, hold=24h
Warmup           : trend_lookback=12, stat_window=48 bars
```

---

## Top-Level Results

| Metric | Value |
|--------|-------|
| Markets attempted | 200 |
| HTTP 403 errors (plan limit) | 39 |
| Markets with 0 trades | 147 |
| **Triggered markets (≥1 trade)** | **14** |
| **Trigger rate** (of accessible markets) | **8.7%** |
| Total trades across all triggered markets | 24 |
| Approx win rate | **58.3%** (14/24) |
| Sum P&L across all triggered markets | **+0.9030** |
| Avg P&L per triggered market | +0.0645 |
| Profitable triggered markets | 10 / 14 |

---

## Critical Finding: The Resolution Spike Problem

The **+0.4739 P&L** on "Total Kills Over/Under 30.5 in Game 3" and the **-0.2368** on "Total Kills Over/Under 30.5 in Game 2" are not legitimate strategy outcomes — they are **resolution events**.

When a market resolves YES/NO, its token price jumps from ~0.5 to 1.0 or 0.0 in a single bar. The engine's `_check_exit` runs at the start of each bar and fires `take_profit` or `stop_loss` at the resolved price. So:

- We entered at ~0.52 (BUY signal), market resolved YES → price = 1.0 → P&L = +0.48
- We entered at ~0.76 (BUY signal), market resolved NO → price = 0.0 → P&L = −0.76, but stop-loss at 0.04 saves us... **only if the stop fires first**

For short-duration markets (eSports matches resolving in hours), the 24h hold window means we can easily be holding at resolution. The `take_profit` / `stop_loss` fire at the resolution price, not at ±0.04/0.08 above entry.

**This means our stop-loss does NOT protect against resolution events in fast markets.** The -0.2368 loss is catastrophically worse than the -0.04 stop-loss we thought we had. The +0.4739 gain is real money but it came from correctly predicting the binary outcome — luck, not strategy.

**Implication:** Any P&L from `end_of_data` or resolution exits is unreliable. The only clean signals are `take_profit` and `stop_loss` exits that trigger before resolution.

---

## Market Diversity (Actual, Despite Missing Tags)

The API returned no tags for any market in this run. Manual inspection of the 14 triggered markets shows genuine cross-category diversity:

| Category | Triggered markets | Trades | Net P&L |
|----------|------------------|--------|---------|
| eSports (LoL kills) | 2 | 2 | +0.2371 |
| Soccer (Portsmouth/Ipswich) | 2 | 5 | +0.3080 |
| Global politics (Honduras election) | 5 | 8 | +0.1842 |
| US politics (Nicki Minaj at SOTU) | 1 | 3 | +0.0861 |
| Geopolitics (Russia/Kupiansk) | 1 | 2 | -0.0000 |
| Global politics (Chile election) | 3 | 4 | +0.0876 |

**This is a positive signal.** The strategy fires across genuinely different market types, not just one correlated theme. The prior concern about all results being US macro 2025 does not apply to this broader universe.

---

## What the Correlation Warning Was Flagging

The "100% untagged" correlation warning fired because the API's `list_markets` returns markets with no tag data. This is a data quality issue, not a real correlation signal. Fix: enrich with `get_market()` calls to fetch individual market metadata, or use search/tag filters at query time.

---

## Plan Limitation

39 markets (19.5%) returned HTTP 403: "Your plan allows up to the last [N] days." These were all markets that resolved before approximately 2026-01-26 (the free-plan data cutoff). This means:

- The accessible "90-day window" is actually **only ~30 days deep** on the free plan
- Markets resolving in Nov–Dec 2025 are invisible to us
- The 200 markets fetched skew heavily toward the last 2–4 weeks

**Impact on the scan:** We're not sampling the full 90-day universe — we're effectively scanning the last 30 days. This is fine for the current analysis but should be noted when interpreting the trigger rate.

---

## Key Numbers to Track

The strategy fired on **8.7%** of accessible markets. That's actually relatively high — it means the whale conditions are met in ~1 in 11 markets. The question is whether those 8.7% are selected by the strategy for good reasons (actual whale activity) or at random.

With 24 total trades across 14 markets:
- Excluding the resolution-spike outliers (#1: +0.4739, #14: -0.2368):
  - Adjusted sum P&L: **+0.9030 − 0.4739 + 0.2368 = +0.6659**
  - Adjusted trades: 22
  - Adjusted win rate: ~57% (13/22)
- Still positive, but significantly smaller than the raw headline

---

## Recommended Next Steps

1. **Fix the resolution-date guard** (highest priority before any live use)
   - Add `resolution_ts` parameter to `BacktestEngine.run()`
   - Force-close and block new entries in the last `hold_periods` bars before resolution
   - Re-run this scan with the fix to get clean P&L numbers

2. **Fix the tag enrichment** in `universe_scan.py`
   - Call `get_market(slug)` for each market to get proper category data
   - Re-run the correlation diagnostic with real tags

3. **Upgrade plan or accept 30-day limit**
   - The effective data window is ~30 days, not 90
   - N=24 trades is not enough for statistical confidence
   - A paid plan would allow the full 90-day scan and much larger N

4. **Filter out ultra-short-duration markets from the screener**
   - eSports (resolves in hours), NBA props (single game), crypto 5-minute markets
   - These have no time for the 48h stat_window warmup and are dominated by resolution risk
   - Add `min_duration_hours = 48` hard filter to both screener and universe scan

5. **Re-run with the macro markets we originally tested**
   - Cross-check: do the 9 manual markets we originally cached appear in the triggered set?
   - If they don't, understand why (they may have been within plan limits at run time)
