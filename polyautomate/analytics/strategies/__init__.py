"""
Built-in trading strategies for the polyautomate backtesting framework.
"""

from .whale_watcher import WhaleWatcherStrategy
from .optimal_entry import EntryProfile, ProfileStrategy, scan_optimal_entries

__all__ = ["WhaleWatcherStrategy", "EntryProfile", "ProfileStrategy", "scan_optimal_entries"]
