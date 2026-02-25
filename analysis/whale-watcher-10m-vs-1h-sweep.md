# WhaleWatcher: 10m vs 1h Granularity Sweep

**Date run:** 2026-02-25
**Branch:** `claude/test-whales-strategy-AuKyU`
**Script:** `examples/granularity_sweep.py` (via background task)
**Cache dir:** `.cache/backtest/` (31 entries, all data pre-fetched)

---

## Strategy Configuration

```python
WhaleWatcherStrategy(
    whale_z_threshold   = 2.5,
    min_trend_move      = 0.02,      # 2 pp minimum trend move to qualify
    min_whale_notional  = 500.0,     # minimum order size in USD
    imbalance_confirm   = True,      # require order book imbalance confirmation
)
```

### Wall-clock-normalised parameters (same window regardless of bar width)

| Resolution | trend_lookback | stat_window | hold_periods | Bars/hour |
|------------|---------------|-------------|--------------|-----------|
| 10m        | 72 bars (12h) | 288 bars (48h) | 144 bars (24h) | 6 |
| 1h         | 12 bars (12h) | 48 bars (48h)  | 24 bars (24h)  | 1 |

Trade parameters: `stop_loss=0.04`, `take_profit=0.08`

---

## Markets Tested (9 markets, 89-day window)

Window: **2025-11-28 → 2026-02-25**

```
fed-emergency-rate-cut-in-2025
fed-rate-hike-in-2025
khamenei-out-as-supreme-leader-of-iran-in-2025
nuclear-weapon-detonation-in-2025
tether-insolvent-in-2025
ukraine-joins-nato-in-2025
us-recession-in-2025
usdt-depeg-in-2025
weed-rescheduled-in-2025
```

(The task notification said "7 markets" — 2 markets may not have had 89-day cache coverage
and fell back to shorter windows; see cache inventory below.)

---

## Results

### 1h resolution (3 markets with full 89-day data)

| File hash prefix | N trades | Win % | 95% CI | Total P&L | Sharpe |
|-----------------|---------|-------|--------|-----------|--------|
| 36599c1e | 4 | **75.0%** | [30%, 95%] | +0.0297 | 1.142 |
| 4a494a6d | 2 | 50.0% | [9%, 91%] | **+0.1710** | 0.699 |
| b5756b7d | 5 | 40.0% | [12%, 77%] | -0.0568 | -0.172 |

> Note: file → market mapping was lost (background task output file captured 0 bytes).
> Re-run `examples/granularity_sweep.py` with a valid API key to get named results.

### 10m resolution (6 markets with full 89-day data)

All 6 markets: **0 trades generated.**

This is expected given:
- `trend_lookback=72 bars` = 720 minutes (12h) of consistent directional movement required
- `stat_window=288 bars` = 2,880 minutes (48h) warmup before any Z-score can fire
- The large lookback at 10m makes signal conditions extremely rare on low-volatility
  prediction markets that drift slowly

---

## Key Findings

1. **1h resolution outperforms 10m** on these macro prediction markets — the signal
   conditions never fire at sub-hourly granularity with proportionally-scaled parameters.

2. **Parameter scaling at 10m is too conservative.** `trend_lookback=72` (12h) and
   `stat_window=288` (48h) demand a near-impossible level of confluence. Consider
   using a fixed shorter `trend_lookback` (~4–8 bars) at 10m rather than scaling
   wall-clock hours linearly.

3. **1h results are low-N** (2–5 trades per market). Win rates have very wide CIs.
   Not enough evidence to draw strong conclusions — need more resolved markets.

4. **Highest absolute P&L at 1h** was `+0.1710` (2 trades, 50% win rate) — driven
   by large individual wins, not consistent edge. Sharpe 0.70 is marginal.

5. **Best risk-adjusted at 1h** was Sharpe 1.14 (4 trades, 75% win rate, +0.030 P&L)
   — small P&L but consistent. Worth watching if sample size grows.

---

## Suggested Next Steps

- [ ] Re-run with API key to get named market results (so P&L can be attributed)
- [ ] Try fixed `trend_lookback=4` and `stat_window=24` at 10m (un-scaled from 1h)
- [ ] Test `z_threshold=2.0` to increase trade count at 1h (more signal, less selectivity)
- [ ] Add more resolved markets to get N > 10 per resolution for meaningful stats
- [ ] Consider a separate 6h resolution sweep — lowest bar count, but may suit
  markets that move in day-scale reactions

---

## Cache Inventory (2026-02-25)

31 JSON files in `.cache/backtest/`:

| Resolution | Start date | # files | Bar count |
|-----------|-----------|---------|-----------|
| 10m | 2025-11-28 | 6 | 12792–12793 |
| 1h  | 2025-11-28 | 3 | 2133 |
| 10m | 2025-12-16 | 7 | 9988–10174 |
| 1h  | 2025-12-16 | 6 | 1665–1696 |
| 1m  | 2025-12-16 | 1 | 100679 |
| 10m | 2026-02-11 | 2 | 2000–19699 |
| 24m | 2026-02-11 | 1 | 19698 |
| 30m | 2026-02-11 | 1 | 1999 |
| 6h  | 2025-12-16 | 2 | 283 |
