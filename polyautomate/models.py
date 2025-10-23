from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, Sequence
import secrets


OrderSide = str  # accepted values: "buy" or "sell"


def _ensure_decimal(value: Decimal | float | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _ensure_datetime(value: datetime | int | float) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


@dataclass(slots=True)
class OrderRequest:
    """Represents the minimal payload needed to submit an order to the CLOB API."""

    token_id: str
    side: OrderSide
    price: Decimal | float | int | str
    size: Decimal | float | int | str
    expiration: datetime | int | float
    salt: str = field(default_factory=lambda: secrets.token_hex(16))
    client_order_id: Optional[str] = None

    def normalized_side(self) -> str:
        value = self.side.lower()
        if value not in {"buy", "sell"}:
            raise ValueError(f"invalid order side '{self.side}' (expected 'buy' or 'sell')")
        return value

    def to_payload(self) -> Dict[str, Any]:
        expiration_ts = int(_ensure_datetime(self.expiration).timestamp())
        payload: Dict[str, Any] = {
            "tokenId": self.token_id,
            "side": self.normalized_side(),
            "price": str(_ensure_decimal(self.price)),
            "size": str(_ensure_decimal(self.size)),
            "expiration": expiration_ts,
            "salt": self.salt,
        }
        if self.client_order_id:
            payload["clientOrderId"] = self.client_order_id
        return payload


@dataclass(slots=True)
class OrderResponse:
    """Simplified representation of an order acknowledgement."""

    order_id: str
    status: str
    raw: Dict[str, Any]


@dataclass(slots=True)
class PricePoint:
    """Represents a single timestamp/price observation."""

    timestamp: datetime
    price: Decimal

    @classmethod
    def from_api(cls, data: Any) -> "PricePoint":
        if isinstance(data, dict):
            ts = (
                data.get("timestamp")
                or data.get("time")
                or data.get("ts")
                or data.get("t")
            )
            price = (
                data.get("price")
                or data.get("value")
                or data.get("close")
                or data.get("p")
            )
        elif isinstance(data, Sequence) and len(data) >= 2:
            ts, price = data[0], data[1]
        else:
            raise ValueError(f"Unsupported price history entry: {data!r}")
        if ts is None or price is None:
            raise ValueError(f"Missing timestamp/price in entry: {data!r}")
        return cls(
            timestamp=_ensure_datetime(ts),
            price=_ensure_decimal(price),
        )
