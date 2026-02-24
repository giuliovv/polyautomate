"""
Backtesting framework for Polymarket trading strategies.

Uses historical price, order book, and metrics data from polymarketdata.co
to simulate strategy performance on resolved markets.

Quick start::

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
"""

from .engine import BacktestEngine
from .models import BacktestResult, Trade, TradeSignal, Signal
from .stats import wilson_ci, price_correlation_matrix, min_trades_for_significance
from .indicators import compute_features, FEATURE_NAMES
from .strategies.optimal_entry import scan_optimal_entries, EntryProfile, ProfileStrategy

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "Trade",
    "TradeSignal",
    "Signal",
    "wilson_ci",
    "price_correlation_matrix",
    "min_trades_for_significance",
    "compute_features",
    "FEATURE_NAMES",
    "scan_optimal_entries",
    "EntryProfile",
    "ProfileStrategy",
]
