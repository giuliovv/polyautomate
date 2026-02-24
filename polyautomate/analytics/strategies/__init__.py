"""
Built-in trading strategies for the polyautomate backtesting framework.
"""

from .whale_watcher import WhaleWatcherStrategy
from .rsi_mean_reversion import RSIMeanReversionStrategy
from .macd_momentum import MACDMomentumStrategy
from .optimal_entry import EntryProfile, ProfileStrategy, scan_optimal_entries

__all__ = [
    "WhaleWatcherStrategy",
    "RSIMeanReversionStrategy",
    "MACDMomentumStrategy",
    "EntryProfile",
    "ProfileStrategy",
    "scan_optimal_entries",
]
