"""
Polymarket automation toolkit.

Provides clients for both legacy Polymarket APIs (CLOB trading, Gamma catalog)
and the new polymarketdata.co high-granularity data API, plus a backtesting
framework for evaluating trading strategies against historical data.

Legacy clients::

    from polyautomate.api.trading import PolymarketTradingClient
    from polyautomate.catalog import MarketCatalog
    from polyautomate.history import PriceHistoryService

polymarketdata.co client::

    from polyautomate.api.polymarketdata import PMDClient

    client = PMDClient(api_key="pk_live_...")
    prices = client.get_prices("some-market-slug", start_ts="...", end_ts="...", resolution="1h")
    books  = client.get_books("some-market-slug",  start_ts="...", end_ts="...", resolution="1h")

Backtesting::

    from polyautomate.backtest import BacktestEngine
    from polyautomate.backtest.strategies.whale_watcher import WhaleWatcherStrategy

    engine   = BacktestEngine(client)
    strategy = WhaleWatcherStrategy(whale_z_threshold=3.0)
    result   = engine.run(strategy, "some-market-slug", "YES", start_ts="...", end_ts="...")
    print(result.summary())
"""

from .exceptions import PolymarketAPIError
from .catalog import MarketCatalog, CatalogEvent, CatalogMarket
from .market import MarketToken, parse_market_tokens, resolve_market_id, resolve_token_id
from .api.data import PolymarketDataClient
from .api.trading import PolymarketTradingClient
from .api.polymarketdata import PMDClient, PMDError
from .models import OrderRequest, OrderResponse, PricePoint
from .history import PriceHistory, PriceHistoryService
from .archive import MarketHistoryExporter, ExportResult, ExportSummary
from .backtest import BacktestEngine, BacktestResult, Trade, TradeSignal, Signal

__all__ = [
    # Legacy Polymarket API clients
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
    # polymarketdata.co client
    "PMDClient",
    "PMDError",
    # Backtesting framework
    "BacktestEngine",
    "BacktestResult",
    "Trade",
    "TradeSignal",
    "Signal",
]
