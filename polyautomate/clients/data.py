from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from .base import BaseAPIClient, DEFAULT_BASE_URL, RequestContext, _coerce_timestamp
from ..models import PricePoint

_INTERVAL_ALIASES = {
    "1m": "1m",
    "1min": "1m",
    "1minute": "1m",
    "one_minute": "1m",
    "minute": "1m",
    "five_minute": "1m",
    "5m": "1m",
    "1h": "1h",
    "1hr": "1h",
    "1hour": "1h",
    "one_hour": "1h",
    "hour": "1h",
    "6h": "6h",
    "6hour": "6h",
    "6hr": "6h",
    "1d": "1d",
    "1day": "1d",
    "day": "1d",
    "1w": "1w",
    "1week": "1w",
    "week": "1w",
    "max": "max",
}

_SUPPORTED_INTERVALS = {"1m", "1h", "6h", "1d", "1w", "max"}


def _normalize_interval(interval: str) -> str:
    key = interval.lower().replace(" ", "").replace("-", "_")
    normalized = _INTERVAL_ALIASES.get(key)
    if normalized:
        return normalized
    if key in _SUPPORTED_INTERVALS:
        return key
    raise ValueError(
        "Unsupported interval value. Accepted options are '1m', '1h', '6h', '1d', '1w', or 'max'."
    )


def _extract_price_history_records(payload: Any) -> Sequence[Any]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "prices", "history", "results", "points"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        if "timestamp" in payload or "price" in payload or "t" in payload or "p" in payload:
            return [payload]
    return []


class PolymarketDataClient(BaseAPIClient):
    """Focused helper for price history and trade data."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        session=None,
        timeout: float = 10.0,
    ) -> None:
        super().__init__(base_url=base_url, session=session, timeout=timeout)

    def get_price_history(
        self,
        market_id: str,
        token_id: str,
        *,
        interval: str = "1h",
        fidelity_minutes: Optional[int] = None,
        start_time: Optional[datetime | int | float] = None,
        end_time: Optional[datetime | int | float] = None,
    ) -> List[PricePoint]:
        params: Dict[str, Any] = {"market": token_id}
        has_start = start_time is not None
        has_end = end_time is not None
        if has_start ^ has_end:
            raise ValueError("start_time and end_time must be provided together when requesting price history.")
        if has_start and has_end:
            params["startTs"] = _coerce_timestamp(start_time)  # type: ignore[arg-type]
            params["endTs"] = _coerce_timestamp(end_time)  # type: ignore[arg-type]
            if fidelity_minutes is not None:
                fidelity_value = int(fidelity_minutes)
                if fidelity_value < 1:
                    raise ValueError("fidelity_minutes must be a positive integer.")
                params["fidelity"] = fidelity_value
        else:
            normalized_interval = _normalize_interval(interval) if interval else "1h"
            params["interval"] = normalized_interval
            min_fidelity = 10 if normalized_interval == "1m" else None
            if fidelity_minutes is not None:
                fidelity_value = int(fidelity_minutes)
                if min_fidelity is not None and fidelity_value < min_fidelity:
                    raise ValueError("fidelity_minutes must be at least 10 when interval is '1m'.")
                params["fidelity"] = fidelity_value
            elif min_fidelity is not None:
                params["fidelity"] = min_fidelity
        ctx = RequestContext(
            method="GET",
            path="/prices-history",
            body=None,
            params=params,
        )
        payload = self._request(ctx)
        records = _extract_price_history_records(payload)
        return [PricePoint.from_api(item) for item in records]

    def get_trades(
        self,
        market_id: str,
        *,
        limit: int = 100,
        before: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"limit": limit}
        if before:
            params["before"] = before
        ctx = RequestContext(
            method="GET",
            path=f"/markets/{market_id}/trades",
            body=None,
            params=params,
        )
        payload = self._request(ctx)
        if isinstance(payload, dict):
            return payload.get("trades") or payload.get("data") or []
        return payload or []
