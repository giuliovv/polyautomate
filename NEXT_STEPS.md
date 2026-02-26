# Next Steps — Polyautomate

Living document. Update after each session with what was done and what remains.

---

## Status Legend

- ✅ Done
- 🔄 In progress
- ⬜ Not started
- ❌ Blocked / needs investigation

---

## Longshot Bias Strategy

### Backtest & Validation

| # | Status | Task | Notes |
|---|--------|------|-------|
| 1 | ✅ | Hold-to-resolution backtest (`longshot_backtest.py`) | P&L from zone entry → resolution |
| 2 | ✅ | Sports/live-game filter (`--no-sports`) | Keyword-based; excludes intra-game spikes |
| 3 | ✅ | Threshold sweep (0.25 / 0.35 / 0.40) | 0.40 best Sharpe; all profitable |
| 4 | ✅ | Sell-only mode (`--sell-only`) | Favorite BUY unreliable without entry condition fix |
| 5 | ✅ | Spread cost in P&L model (`--half-spread`) | Default 1 pp half-spread; shows gross vs net P&L |
| 6 | ✅ | Kelly-optimal position sizing output | Per-bucket Kelly fractions; recommends ¼ Kelly |
| 7 | ⬜ | Fetch actual spreads from `/metrics` at entry bar | Replace fixed assumption with real data per market |
| 8 | ⬜ | Broader universe (1000+ markets, 180-day window) | Need paid plan for full history; N=72 trades too small |
| 9 | ⬜ | Favorite BUY with "opens above threshold" condition | Test markets that *start* above 0.65, not zone-crossing |

### Signal Generation & Screener

| # | Status | Task | Notes |
|---|--------|------|-------|
| 10 | ⬜ | Add longshot zone flag to `market_screener.py` | Flag open markets currently ≤ 0.35 with spread filter |
| 11 | ⬜ | Live paper-trading monitor | Poll for zone entries; adapt `arbitrage_scanner.py` pattern |

### Position Management

| # | Status | Task | Notes |
|---|--------|------|-------|
| 12 | ✅ | Kelly fraction per price bucket (theoretical) | f* = (p·b − q·(1−b)) / (b·(1−b)); recommend ¼ Kelly |
| 13 | ⬜ | Portfolio-level Kelly (correlated positions) | Multiple simultaneous positions need adjusted sizing |
| 14 | ⬜ | Hard max-position cap | e.g. never > 5% bankroll per trade regardless of Kelly |

---

## WhaleWatcher Strategy

### Backtest & Validation

| # | Status | Task | Notes |
|---|--------|------|-------|
| 20 | ✅ | Granularity sweep (10m vs 1h) | 1h fires on macro markets; 10m zero trades at scaled params |
| 21 | ✅ | Universe scan (200 markets, 89-day window) | 8.7% trigger rate; N=24 trades total |
| 22 | ⬜ | Resolution-date guard in `BacktestEngine` | Critical: engine holds into resolution → catastrophic P&L |
| 23 | ⬜ | Fix 10m resolution: use fixed `trend_lookback=4–8` | Scaled 72-bar lookback is too conservative at 10m |
| 24 | ⬜ | Lower z-threshold test (z=2.0) | Increase trade count at 1h for better statistics |
| 25 | ⬜ | 6h resolution sweep | Lowest bar count; may suit slow-moving macro markets |

### Market Selection

| # | Status | Task | Notes |
|---|--------|------|-------|
| 26 | ✅ | Market screener (`market_screener.py`) | Scores liquidity, movement, time, position |
| 27 | ⬜ | Tag enrichment in universe scan | API returns no tags; call `get_market()` per slug |
| 28 | ⬜ | Min-duration hard filter (≥ 48h) | Exclude same-day sports / crypto 5-min markets |

---

## Infrastructure

| # | Status | Task | Notes |
|---|--------|------|-------|
| 30 | ⬜ | Upgrade API plan | Free plan: ~30-day effective history; 39/200 markets 403'd |
| 31 | ⬜ | Named backtest results (market→P&L mapping) | Lost in background task; re-run with `--verbose` |
| 32 | ⬜ | Live execution integration | Connect signals to `trading.py` client |

---

## Empirical Results Reference

### Longshot Bias (as of 2026-02-26)

**Parameters:** 400 markets, 89-day window, first-entry-only, sell-only, no-sports

| Threshold | Trades | Win% | Gross P&L | Gross Avg/trade | Sharpe |
|-----------|--------|------|-----------|-----------------|--------|
| ≤ 0.25 | 69 | 89.9% | +4.29 | +0.062 | 0.489 |
| ≤ 0.35 | 72 | 90.3% | +6.68 | +0.093 | 0.614 |
| ≤ 0.40 | 72 | 91.7% | +7.68 | +0.107 | 0.647 |

Net P&L (after 1 pp half-spread): subtract ~0.072 total (72 trades × 0.001... wait — see backtest output for exact net figures).

**Calibration (threshold=0.35):**

| Bucket | N | Implied YES% | Observed YES% | Edge |
|--------|---|-------------|---------------|------|
| 0.02–0.10 | 39 | 6.0% | 0.0% | −6 pp |
| 0.10–0.20 | 10 | 15.0% | 0.0% | −15 pp |
| 0.20–0.35 | 23 | 27.5% | 4.3% | −23 pp |

**Worst single trade:** Costa Rica 2026 election turnout (entry 0.241, resolved YES) → −0.749.

### WhaleWatcher (as of 2026-02-25)

- 1h: 2–5 trades per market, win rates 40–75%, Sharpe 0.70–1.14 (low N)
- 10m: 0 trades with wall-clock-scaled parameters

---

## Session Log

| Date | Branch | What was done |
|------|--------|---------------|
| 2026-02-25 | `claude/test-whales-strategy-AuKyU` | WhaleWatcher granularity sweep (10m vs 1h), universe scan, risk & market-selection analysis |
| 2026-02-26 | `claude/test-whales-strategy-AuKyU` | Longshot bias hold-to-resolution backtest, sports filter, threshold sweep (0.25/0.35/0.40), LONGSHOT_ANALYSIS.md |
| 2026-02-26 | `claude/test-whales-strategy-AuKyU` | Spread cost model (`--half-spread`), Kelly position sizing output, NEXT_STEPS.md |
