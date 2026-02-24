"""
Polymarket analytics toolkit.

Provides an analytics and strategy-simulation framework backed by
polymarketdata.co data, with thin client wrappers for the Polymarket APIs.

Analytics / backtesting::

    from polyautomate.clients.polymarketdata import PMDClient
    from polyautomate.analytics import BacktestEngine
    from polyautomate.analytics.strategies.whale_watcher import WhaleWatcherStrategy

    client   = PMDClient(api_key="pk_live_...")
    engine   = BacktestEngine(client)
    strategy = WhaleWatcherStrategy(whale_z_threshold=3.0)
    result   = engine.run(strategy, "some-market-slug", "YES", start_ts="...", end_ts="...")
    print(result.summary())

Data collection::

    from polyautomate.data import MarketCatalog, PriceHistoryService

Market clients::

    from polyautomate.clients.trading import PolymarketTradingClient
    from polyautomate.models import OrderRequest
"""

from .exceptions import PolymarketAPIError
from .models import OrderRequest, OrderResponse, PricePoint
from .data import (
    MarketCatalog,
    CatalogEvent,
    CatalogMarket,
    MarketToken,
    parse_market_tokens,
    resolve_market_id,
    resolve_token_id,
    PriceHistory,
    PriceHistoryService,
    MarketHistoryExporter,
    ExportResult,
    ExportSummary,
)
from .clients import PolymarketDataClient, PolymarketTradingClient
from .clients.polymarketdata import PMDClient, PMDError
from .analytics import BacktestEngine, BacktestResult, Trade, TradeSignal, Signal

__all__ = [
    # Analytics framework
    "BacktestEngine",
    "BacktestResult",
    "Trade",
    "TradeSignal",
    "Signal",
    # Data utilities
    "MarketCatalog",
    "CatalogEvent",
    "CatalogMarket",
    "MarketToken",
    "parse_market_tokens",
    "resolve_market_id",
    "resolve_token_id",
    "PriceHistory",
    "PriceHistoryService",
    "MarketHistoryExporter",
    "ExportResult",
    "ExportSummary",
    # polymarketdata.co client
    "PMDClient",
    "PMDError",
    # Legacy Polymarket API clients
    "PolymarketDataClient",
    "PolymarketTradingClient",
    "PolymarketAPIError",
    "OrderRequest",
    "OrderResponse",
    "PricePoint",
]
