"""
Utilities for retrieving and shaping Polymarket price history.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence

from .api.data import PolymarketDataClient
from .models import PricePoint


@dataclass(slots=True)
class PriceHistory:
    """Container representing a sequence of price observations for a single outcome token."""

    market_id: str
    token_id: str
    points: Sequence[PricePoint]

    def to_rows(self) -> List[dict]:
        """Return price observations as simple dicts (timestamp, price)."""
        rows: List[dict] = []
        for point in self.points:
            rows.append({"timestamp": point.timestamp, "price": float(point.price)})
        return rows

    def to_dataframe(self):
        """Convert the price history into a pandas DataFrame."""
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError(
                "pandas is required for to_dataframe(). Install it with 'pip install pandas'."
            ) from exc

        rows = self.to_rows()
        if not rows:
            return pd.DataFrame(columns=["price"]).set_index(
                pd.Index([], name="timestamp")
            )
        frame = pd.DataFrame(rows)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame.set_index("timestamp").sort_index()
        frame.index.name = "timestamp"
        return frame

    @property
    def candles(self) -> Sequence[PricePoint]:
        """Backwards-compatible alias for callers expecting a candle-like attribute."""
        return self.points


class PriceHistoryService:
    """Helper for collecting price history sequences."""

    def __init__(self, data_client: PolymarketDataClient | None = None) -> None:
        self._data_client = data_client or PolymarketDataClient()

    @property
    def data_client(self) -> PolymarketDataClient:
        return self._data_client

    def get_price_history(
        self,
        market_id: str,
        token_id: str,
        *,
        interval: str = "1h",
        **filters,
    ) -> PriceHistory:
        points = self.data_client.get_price_history(
            market_id,
            token_id,
            interval=interval,
            **filters,
        )
        return PriceHistory(market_id=market_id, token_id=token_id, points=points)

    def batch_price_history(
        self,
        targets: Iterable[tuple[str, str]],
        *,
        interval: str = "1h",
        **filters,
    ) -> List[PriceHistory]:
        histories: List[PriceHistory] = []
        for market_id, token_id in targets:
            histories.append(
                self.get_price_history(
                    market_id,
                    token_id,
                    interval=interval,
                    **filters,
                )
            )
        return histories
