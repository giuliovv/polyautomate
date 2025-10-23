# Polyautomate

Utility clients for building Polymarket trading automations.

## Features

- Fetch active markets and market metadata from the CLOB API.
- Pull price history for specific tickets/outcomes to seed simulations.
- Submit, cancel, and list orders with authenticated requests.
- Minimal data models for order creation and acknowledgement handling.

## Installation

```
pip install -e .
```

Requires Python 3.10+.

## Quick start

```python
from polyautomate.api.data import PolymarketDataClient
from polyautomate.api.trading import PolymarketTradingClient
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
from polyautomate.api.data import PolymarketDataClient
from polyautomate.catalog import MarketCatalog
from polyautomate.history import PriceHistoryService

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
from polyautomate.archive import MarketHistoryExporter

exporter = MarketHistoryExporter(output_dir="history")
summary = exporter.export_search(query="shutdown", closed=False, interval="1m")
print(f"Failures: {summary.failed}")
for item in summary.successes:
    print(item.path, item.rows)
```

Each CSV is indexed by timestamp and ready for downstream analysis.


## Authentication notes

The trading client signs every request using the standard Polymarket CLOB flow:

# Before you can trade programmatically

1. Log in at [polymarket.com](https://polymarket.com) with your wallet (e.g. MetaMask).
2. Navigate to **Settings → API** and follow the prompts to enable API access. Polymarket
   has you confirm the request with your wallet; this step is where MetaMask is involved.
3. Download the generated credentials (`apiKey` and `secret`). The secret is an Ed25519
   private key expressed in hex. Store it securely—Polymarket only shows it once.
4. Supply those values to `PolymarketTradingClient`. From that point on, requests are
   signed locally with the Ed25519 secret rather than through MetaMask.

```
signature = Ed25519_sign(
    timestamp + HTTP_METHOD + path + canonical_json_body
)
```

- `timestamp` is expressed in milliseconds and automatically generated.
- `canonical_json_body` is serialized with sorted keys and no whitespace.
- Install `pynacl` to provide Ed25519 signing support.

Consult the official Polymarket API documentation to learn how to create API keys
and to understand the permissible order parameters.
