from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import time
from typing import Any, Dict, List, Optional

from .base import BaseAPIClient, DEFAULT_BASE_URL, RequestContext, _json_dumps, _normalize_path
from ..models import OrderRequest, OrderResponse


class PolymarketTradingClient(BaseAPIClient):
    """Authenticated helper for interacting with the CLOB trading API.

    Uses Polymarket L2 auth: HMAC-SHA256 signed requests with POLY_* headers.
    See: https://docs.polymarket.com/#authentication
    """

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        api_passphrase: str,
        address: str,
        signer_address: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        session=None,
        timeout: float = 10.0,
    ) -> None:
        super().__init__(base_url=base_url, session=session, timeout=timeout)
        self.api_key = api_key
        self._api_secret = api_secret
        self._api_passphrase = api_passphrase
        self._address = address
        # POLY_ADDRESS must be the EOA (signer) address. For proxy/email accounts
        # this differs from `address` (the proxy wallet / funder). Falls back to
        # `address` for pure-EOA accounts where they are the same.
        self._signer_address = signer_address or address

    def place_order(
        self,
        order: OrderRequest,
        *,
        post_only: bool = False,
        reduce_only: bool = False,
    ) -> OrderResponse:
        payload = order.to_payload()
        if post_only:
            payload["postOnly"] = True
        if reduce_only:
            payload["reduceOnly"] = True
        ctx = RequestContext(method="POST", path="/orders", body=payload, params=None)
        response = self._signed_request(ctx)
        order_id = response.get("orderId") or response.get("id") or ""
        status = response.get("status", "submitted")
        return OrderResponse(order_id=order_id, status=status, raw=response)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        ctx = RequestContext(method="DELETE", path=f"/orders/{order_id}", body=None, params=None)
        return self._signed_request(ctx)

    def get_open_orders(self, *, token_id: Optional[str] = None) -> Dict[str, Any] | List[Dict[str, Any]]:
        params = {"tokenId": token_id} if token_id else None
        ctx = RequestContext(method="GET", path="/orders", body=None, params=params)
        payload = self._signed_request(ctx)
        if isinstance(payload, dict):
            return payload.get("orders") or payload.get("data") or []
        return payload or []

    def get_balances(self) -> Dict[str, Any]:
        ctx = RequestContext(method="GET", path="/balance-allowance", body=None, params={"asset_type": "COLLATERAL"})
        payload = self._signed_request(ctx)
        return payload or {}

    def _signed_request(self, ctx: RequestContext) -> Any:
        path = _normalize_path(ctx.path)
        timestamp = str(int(time.time()))
        body_str = _json_dumps(ctx.body)

        # Build the message: timestamp + method + path + body (body omitted if empty)
        message = f"{timestamp}{ctx.method.upper()}{path}"
        if body_str:
            message += body_str.replace("'", '"')

        secret_bytes = base64.urlsafe_b64decode(self._api_secret)
        sig = base64.urlsafe_b64encode(
            _hmac.new(secret_bytes, message.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")

        headers = {
            "POLY_ADDRESS": self._signer_address,
            "POLY_SIGNATURE": sig,
            "POLY_TIMESTAMP": timestamp,
            "POLY_API_KEY": self.api_key,
            "POLY_PASSPHRASE": self._api_passphrase,
        }
        return self._request(ctx, headers=headers)
