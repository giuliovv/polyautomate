# Risk Profile & Market Selection for WhaleWatcher

**Date:** 2026-02-25

---

## 1. Exit Strategy & Risk Profile

### How exits work (engine.py:_check_exit)

Every bar, every open position is checked against three triggers (in priority order):

```
take_profit : directional_move >= tp  →  close, keep the gain
stop_loss   : directional_move <= -sl →  close, accept the loss
timeout     : bars_held >= hold_periods → force-close at current price
```

With the sweep parameters (`sl=0.04, tp=0.08`):
- **Maximum loss per trade (in simulation):** 4 probability points of position
- **Maximum gain per trade:** 8 probability points
- Risk/reward ratio: 1:2

### The gap: no resolution-date awareness

The engine does NOT know when a market resolves. This matters because:

1. A market that resolves YES sends the token from ~0.60 → 1.00 in one bar.
   - If you're short (SELL signal): `price_move = +0.40`, which is 10× your `sl=0.04`.
     The stop-loss fires but at the already-resolved price — full loss.
2. A market that resolves NO sends the token from ~0.60 → 0.00.
   - If you're long (BUY signal): same catastrophic outcome.
3. The `timeout` exit is a safety net but not a resolution guard — it only fires
   after `hold_periods` bars regardless of resolution.

**Practical consequence:** we must never hold a position into the final few bars before
a market's resolution date. The current code has no mechanism for this.

### Fix required (not yet implemented)

The engine needs a `resolution_date` parameter passed to `run()`. At each bar,
if `(resolution_ts - current_ts) < some_safety_buffer` (e.g. 2 × hold_period bars),
close any open position and stop opening new ones.

---

## 2. What Makes a Market Good for WhaleWatcher

### Required conditions

| Property | Minimum threshold | Why |
|----------|------------------|-----|
| Avg best-bid notional | > $500 | Below this, `min_whale_notional` filter silences everything |
| Avg price range (89-day) | > 5 pp | Strategy needs `min_trend_move=0.02` — flat markets never signal |
| Days to resolution | > 2× hold_periods | Must be able to hold without resolution risk |
| Current price | 0.10 – 0.90 | Near 0 or 1: no room for a 4pp stop, thin books, no signal |
| Historical data available | ≥ stat_window + trend_lookback bars | Not enough warmup = no signals |

### Ideal market profile

- **Long-dated binary outcome** (weeks to months out): enough time for multiple whale
  events and price discovery
- **Contested probability** (0.35–0.65): maximum uncertainty → thick books, active
  price movement, most room for stops and take-profits
- **Macro / geopolitical** (rate decisions, elections, treaties): attract institutional
  size. Sports and micro-events typically have retail-sized orders only.
- **Multiple resolvable events feeding it** (e.g. FOMC meetings): whales re-enter
  after each new data release, generating repeat signals

### Markets that will *not* work

- Resolved or nearly-resolved (price < 0.05 or > 0.95): no signal, resolution risk
- Very new markets (< stat_window bars of history): warmup failure
- Thin markets (avg notional < $500): all Z-scores are 0
- Ultra-short-duration (< 48h): no room for a 24h hold before resolution

---

## 3. Market Screening Approach (not yet implemented)

To systematically find good markets, we need a screener that queries live markets
and scores them before running the whale strategy.

### Scoring dimensions

```
liquidity_score  = avg(best_bid_notional + best_ask_notional) / 2  [want high]
movement_score   = price_range_89d / 0.30                          [want > 1]
time_score       = days_to_resolution / 30                         [want > 1, cap at 3]
position_score   = 1 - |current_price - 0.50| / 0.50              [want close to 1]
history_score    = min(1, n_bars / (stat_window + trend_lookback)) [want 1]

composite = (liquidity_score × 0.3 + movement_score × 0.25 +
             time_score × 0.25 + position_score × 0.2)
```

### Suggested next implementation

Build `examples/market_screener.py` that:
1. Calls `PMDClient.list_markets(status="active", limit=200)`
2. For each market, fetches lightweight 6h price data (cheap API call)
3. Computes the scoring dimensions above
4. Returns top-N markets sorted by composite score
5. Optionally feeds those directly into `granularity_sweep.py`

This closes the loop: screener finds candidates → sweep backtests them →
best markets get allocated live position.

---

## 4. Summary: What We Know vs What We Need

### Known (from sweep results)
- WhaleWatcher fires at 1h resolution on macro markets with 89-day history
- It does NOT fire at 10m with wall-clock-proportional parameters (too conservative)
- Sample sizes are tiny (2–5 trades per market) — no statistical confidence yet

### Open gaps
1. **Resolution-date guard** in the engine — critical before any live use
2. **Market screener** — currently we pick markets manually; needs automation
3. **Named results** — we lost the market→file mapping from the sweep
   (re-run with API key to restore)
4. **More resolved markets** — need N > 20 per config to trust win rates
5. **10m fix** — test fixed `trend_lookback=4–8` (not scaled) at 10m resolution
