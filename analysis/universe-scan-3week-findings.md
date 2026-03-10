# Universe Scan — 3-Week Window Findings

**Date:** 2026-03-10
**Script:** `examples/universe_scan.py`
**Raw CSV:** `analysis/universe_scan_3weeks.csv`

---

## Run Parameters

```
Universe size    : 200 markets (sorted by updated_at desc)
Resolved window  : 2026-02-17 → 2026-03-10 (21 days)
Backtest window  : 21 days before each market's end_date
Resolution       : 1h
Strategy         : WhaleWatcher z=2.5, sl=0.04, tp=0.08, hold=24h
Warmup           : trend_lookback=12, stat_window=48 bars
```

---

## Top-Level Results

| Metric | Value |
|--------|-------|
| Markets attempted | 200 |
| Skipped (spread > 3pp) | 160 |
| Errors (missing price data) | 4 |
| Markets with 0 trades | 35 |
| **Triggered markets (≥1 trade)** | **1** |
| **Trigger rate** (of accessible markets) | **2.8%** |
| Total trades | 1 |
| Win rate | 0.0% |
| Sum P&L | **-0.0140** |

---

## Key Finding: The Universe Has Changed

The most recent 3-week window is dominated by **short-duration, high-spread markets** that the strategy correctly filters out but can never trade:

| Category | Count | Action |
|----------|-------|--------|
| eSports (CS, LoL, Dota2 — props/handicaps) | ~80 | SKIP: spread 10–92pp |
| Crypto price 5-min O/U (BTC, ETH, SOL, XRP) | ~15 | 0 trades (no whale flow) |
| Sports (basketball spreads/totals) | ~10 | SKIP or error |
| Netflix rankings, weather, social media tweets | ~30 | SKIP: spread 4–26pp |
| Substantive political/geopolitical markets | ~10 | 0 trades or 1 trade |

The only triggered market was:

- **"Will Scott Colom be the Democratic nominee for MS Senate?"** — 1 trade, 0% win, P&L = -0.014

---

## Comparison vs. Feb 25 Scan (90-day window)

| Metric | Feb 25 (90d) | Mar 10 (21d) |
|--------|-------------|-------------|
| Triggered markets | 14 / 200 | 1 / 200 |
| Trigger rate | 8.7% | 2.8% |
| Total trades | 24 | 1 |
| Sum P&L | +0.903 | -0.014 |
| Market diversity | Soccer, global politics, US politics, geopolitics | Almost all eSports + crypto 5-min |

The drop in trigger rate is **not evidence the strategy stopped working** — it reflects the composition of the recent universe. The last 3 weeks on Polymarket have been flooded with esports prop markets and crypto micro-markets. None of these pass the 3pp spread filter, and none attract the sustained order flow needed for the whale z-score to fire.

---

## Should We Have Found Something?

**No. The strategy correctly found nothing actionable in this window.**

Reasons:
1. **160/200 markets (80%) filtered by spread > 3pp.** These are structurally untradeable for the WhaleWatcher approach — the spread alone exceeds the take-profit threshold.
2. **The remaining 40 markets are crypto 5-min and social-media-count markets.** These have tiny durations (minutes to hours) — far shorter than the 48-bar stat_window warmup. The engine runs but sees no stable trend or z-score signal.
3. **Only ~10 substantive political markets appeared in the window**, and those (UN Secretary General candidates, MS Senate nominees) are thin markets with no detectable whale activity.

The single triggered trade (-0.014) is in a low-liquidity political binary — consistent with random noise at this sample size.

---

## What Would Change This

- **A meaningful signal** would require substantive political or macro-economic markets (like Honduras election, Chile election, US Fed decisions) appearing in the top-200 recently resolved list.
- The current Polymarket universe is being dominated by eSports props and crypto micro-markets. The substantive macro markets take longer to resolve and appear less frequently in a short 21-day window.
- **Re-run with `--resolved-days 45`** to capture more of the slower-resolving substantive markets while staying within the free plan's ~30-day data window.

---

## Recommended Next Steps

1. **No strategy changes needed** — the lack of triggers is a universe composition problem, not a strategy problem.
2. **Add a market duration pre-filter** (`min_duration_hours = 48` or `72`) to automatically exclude esports props, crypto 5-min markets, and other ultra-short markets from the screener. This would reduce API calls and improve scan speed.
3. **Increase `--resolved-days` to 45** on future scans to capture the longer-tail substantive markets that take weeks to resolve.
4. **Check the live executor's recent trade log** to see if any longshot positions have been entered and how they're performing — the WhaleWatcher scan and the live longshot executor operate on different strategies and universes.
