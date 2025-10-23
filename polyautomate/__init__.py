"""
High-level client helpers for interacting with Polymarket's public data endpoints
and the central limit order book (CLOB) trading API.

The package exposes two main entry points:

- :class:`polyautomate.api.data.PolymarketDataClient` for market metadata and
  historical pricing information.
- :class:`polyautomate.api.trading.PolymarketTradingClient` for managing private
  trading actions such as submitting orders.

Typical usage::

    from polyautomate.api.trading import PolymarketTradingClient
    from polyautomate.catalog import MarketCatalog
    from polyautomate.history import PriceHistoryService

    trading = PolymarketTradingClient(api_key="...", signing_key="...")
    trading.place_order(order)

    catalog = MarketCatalog()
    event = catalog.get_event("event-slug")
    market = event.markets[0]
    history = PriceHistoryService().get_price_history(
        market_id=market.condition_id,
        token_id=market.clob_token_ids[0],
    )
"""

from .exceptions import PolymarketAPIError
from .catalog import MarketCatalog, CatalogEvent, CatalogMarket
from .market import MarketToken, parse_market_tokens, resolve_market_id, resolve_token_id
from .api.data import PolymarketDataClient
from .api.trading import PolymarketTradingClient
from .models import OrderRequest, OrderResponse, PricePoint
from .history import PriceHistory, PriceHistoryService
from .archive import MarketHistoryExporter, ExportResult, ExportSummary

__all__ = [
    "PolymarketDataClient",
    "PolymarketTradingClient",
    "PolymarketAPIError",
    "OrderRequest",
    "OrderResponse",
    "MarketToken",
    "parse_market_tokens",
    "resolve_market_id",
    "resolve_token_id",
    "MarketCatalog",
    "CatalogEvent",
    "CatalogMarket",
    "PricePoint",
    "PriceHistory",
    "PriceHistoryService",
    "MarketHistoryExporter",
    "ExportResult",
    "ExportSummary",
]
