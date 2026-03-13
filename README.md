# Polyautomate

Utility clients for building Polymarket trading automations, with a built-in
backtesting framework for evaluating strategies against historical data.

## Package layout

```
polyautomate/
├── analytics/      ← backtesting engine & strategies (primary)
├── data/           ← market discovery, price history, CSV export
├── clients/        ← API wrappers (CLOB, Gamma, polymarketdata.co)
├── models.py       ← shared order/price models
└── exceptions.py
```

## Installation

```
pip install -e .
```

Requires Python 3.10+.

## Quick start — backtesting

```python
from polyautomate.clients.polymarketdata import PMDClient
from polyautomate.analytics import BacktestEngine
from polyautomate.analytics.strategies.whale_watcher import WhaleWatcherStrategy

client = PMDClient(api_key="pk_live_...")
engine = BacktestEngine(client)

strategy = WhaleWatcherStrategy(
    whale_z_threshold=3.0,
    trend_lookback=24,
    hold_periods=12,
    stop_loss=0.05,
    take_profit=0.10,
)

result = engine.run(
    strategy=strategy,
    market_id="some-market-slug",
    token_label="YES",
    start_ts="2024-01-01T00:00:00Z",
    end_ts="2024-06-01T00:00:00Z",
    resolution="1h",
)
print(result.summary())
```

## Quick start — data clients

```python
from polyautomate.clients.data import PolymarketDataClient
from polyautomate.clients.trading import PolymarketTradingClient
from polyautomate.models import OrderRequest

data = PolymarketDataClient()  # price history & trade lookups

# Trading (requires an API key pair derived from your wallet)
trader = PolymarketTradingClient(
    api_key="pm_api_key",
    signing_key="hex_encoded_ed25519_private_key",
)

order = OrderRequest(
    token_id="outcome-token-id",
    side="buy",
    price="0.45",
    size="100",
    expiration=3600 + int(__import__("time").time()),
)

ack = trader.place_order(order, post_only=True)
print(ack.order_id, ack.status)
```

### Historical prices

```python
from polyautomate.clients.data import PolymarketDataClient
from polyautomate.data.catalog import MarketCatalog
from polyautomate.data.history import PriceHistoryService

data = PolymarketDataClient()
catalog = MarketCatalog()
event = catalog.get_event("when-will-the-government-shutdown-end-545")
shutdown_market = event.markets[0]
token_id = shutdown_market.clob_token_ids[0]

history_service = PriceHistoryService(data)
price_history = history_service.get_price_history(
    market_id=shutdown_market.condition_id,
    token_id=token_id,
    interval="1m",
)

frame = price_history.to_dataframe()
print(frame.head())
```

### Exporting a local history archive

```python
from polyautomate.data.archive import MarketHistoryExporter

exporter = MarketHistoryExporter(output_dir="history")
summary = exporter.export_search(query="shutdown", closed=False, interval="1m")
print(f"Failures: {summary.failed}")
for item in summary.successes:
    print(item.path, item.rows)
```

Each CSV is indexed by timestamp and ready for downstream analysis.


## Authentication notes

The flow below is the one we use in production and matches the Polymarket CLOB model.

### What you need

1. Wallet private key for the EOA signer address.
2. CLOB API credentials: `apiKey`, `secret`, `passphrase`.
3. Funder/proxy wallet address (for Magic/email/proxy setups, this differs from signer EOA).

### How to obtain credentials (recommended)

1. Log in at [polymarket.com](https://polymarket.com) with your wallet.
2. Go to **Settings -> API** and enable API access.
3. Either:
   - use credentials shown in UI (`apiKey`, `secret`, `passphrase`), or
   - derive them programmatically from wallet key using the official `py-clob-client`:

```python
from py_clob_client.client import ClobClient

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
PRIVATE_KEY = "0x..."              # signer EOA private key
SIGNATURE_TYPE = 1                 # 1 for Magic/email proxy, 0 for pure EOA
FUNDER = "0x..."                   # proxy/funder wallet (or same as signer for pure EOA)

client = ClobClient(HOST, chain_id=CHAIN_ID, key=PRIVATE_KEY, signature_type=SIGNATURE_TYPE, funder=FUNDER)
creds = client.create_or_derive_api_creds()
print(creds.api_key, creds.api_secret, creds.api_passphrase)
```

### Secret mapping used in this repo

- `POLYMARKET_API_KEY` -> CLOB `apiKey`
- `POLYMARKET_SIGNING_KEY` -> CLOB `secret` (L2 auth secret)
- `POLYMARKET_PASSPHRASE` -> CLOB `passphrase`
- `POLYMARKET_SIGNER_ADDRESS` -> signer EOA address
- `POLYMARKET_ADDRESS` -> funder/proxy wallet address
- `POLYMARKET_SIGNATURE_TYPE` -> `0` (EOA), `1` (Magic/email proxy), `2` (browser-wallet proxy)

Important:
- `POLYMARKET_SIGNING_KEY` is not your wallet private key.
- Keep wallet private key and API secret separate.
- If credentials are regenerated, update all three values together (`apiKey`, `secret`, `passphrase`).

Consult official docs for latest auth/order requirements:
- https://docs.polymarket.com/developers/CLOB/authentication
- https://docs.polymarket.com/developers/CLOB/orders/create-order
