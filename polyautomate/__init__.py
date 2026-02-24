"""
Polymarket automation toolkit.

Provides a backtesting framework for evaluating trading strategies against
historical data, clients for both legacy Polymarket APIs (CLOB trading,
Gamma catalog) and the polymarketdata.co high-granularity data API, plus
utilities for market discovery and history export.

Analytics (backtesting)::

    from polyautomate.clients.polymarketdata import PMDClient
    from polyautomate.analytics import BacktestEngine
    from polyautomate.analytics.strategies.whale_watcher import WhaleWatcherStrategy

    client   = PMDClient(api_key="pk_live_...")
    engine   = BacktestEngine(client)
    strategy = WhaleWatcherStrategy(whale_z_threshold=3.0)
    result   = engine.run(strategy, "some-market-slug", "YES", start_ts="...", end_ts="...")
    print(result.summary())

Data clients::

    from polyautomate.clients.trading import PolymarketTradingClient
    from polyautomate.data.catalog import MarketCatalog
    from polyautomate.data.history import PriceHistoryService

polymarketdata.co client::

    from polyautomate.clients.polymarketdata import PMDClient

    client = PMDClient(api_key="pk_live_...")
    prices = client.get_prices("some-market-slug", start_ts="...", end_ts="...", resolution="1h")
    books  = client.get_books("some-market-slug",  start_ts="...", end_ts="...", resolution="1h")
"""

from .exceptions import PolymarketAPIError
# Analytics (primary)
from .analytics import BacktestEngine, BacktestResult, Trade, TradeSignal, Signal
# Clients
from .clients.data import PolymarketDataClient
from .clients.trading import PolymarketTradingClient
from .clients.polymarketdata import PMDClient, PMDError
# Data
from .data.catalog import MarketCatalog, CatalogEvent, CatalogMarket
from .data.market import MarketToken, parse_market_tokens, resolve_market_id, resolve_token_id
from .data.history import PriceHistory, PriceHistoryService
from .data.archive import MarketHistoryExporter, ExportResult, ExportSummary
# Models
from .models import OrderRequest, OrderResponse, PricePoint

__all__ = [
    # Analytics / backtesting
    "BacktestEngine",
    "BacktestResult",
    "Trade",
    "TradeSignal",
    "Signal",
    # Clients
    "PolymarketDataClient",
    "PolymarketTradingClient",
    "PMDClient",
    "PMDError",
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
    # Models
    "OrderRequest",
    "OrderResponse",
    "PricePoint",
    # Errors
    "PolymarketAPIError",
]
