"""Signer service data models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SignRequest(BaseModel):
    """Order signing request from executor."""

    request_id: str  # Idempotency key
    wallet_id: str  # Platform wallet UUID
    bot_id: str | None  # Requesting bot UUID (optional for direct API calls)
    order_payload: dict[str, Any]  # {token_id, side, price, size, expiration?}
    timestamp: int  # Unix timestamp
    signature: str  # HMAC of payload signed by backend


class SignResponse(BaseModel):
    """Order signing response."""

    request_id: str
    success: bool
    signed_order: dict[str, Any] | None = None
    order_id: str | None = None
    error: str | None = None


class PostOrderRequest(BaseModel):
    """Request to post a signed order to Polymarket."""

    request_id: str
    wallet_id: str
    bot_id: str | None
    signed_order: dict[str, Any]
    post_only: bool = True
    timestamp: int
    signature: str


class PostOrderResponse(BaseModel):
    """Response from posting an order."""

    request_id: str
    success: bool
    order_id: str | None = None
    status: str | None = None
    error: str | None = None


class BalanceRequest(BaseModel):
    """Request to fetch wallet balance."""

    request_id: str
    wallet_id: str
    timestamp: int
    signature: str


class BalanceResponse(BaseModel):
    """Wallet balance response."""

    request_id: str
    success: bool
    balance_usdc: float | None = None
    error: str | None = None
