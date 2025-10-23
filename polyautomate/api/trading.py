from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

try:
    from nacl import signing  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    signing = None

from .base import BaseAPIClient, DEFAULT_BASE_URL, RequestContext, _json_dumps, _normalize_path
from ..models import OrderRequest, OrderResponse


class PolymarketTradingClient(BaseAPIClient):
    """Authenticated helper for interacting with the CLOB trading API."""

    def __init__(
        self,
        *,
        api_key: str,
        signing_key: str,
        base_url: str = DEFAULT_BASE_URL,
        session=None,
        timeout: float = 10.0,
        signature_type: str = "ed25519",
    ) -> None:
        super().__init__(base_url=base_url, session=session, timeout=timeout)
        if signing is None:
            raise ImportError(
                "pynacl is required for signing requests. Install it via 'pip install pynacl'."
            )
        self.api_key = api_key
        self._signing_key_hex = signing_key
        self.signature_type = signature_type
        self._signing_key = signing.SigningKey(bytes.fromhex(signing_key))

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
        ctx = RequestContext(method="GET", path="/balances", body=None, params=None)
        payload = self._signed_request(ctx)
        return payload or {}

    def _signed_request(self, ctx: RequestContext) -> Any:
        path = _normalize_path(ctx.path)
        timestamp = str(int(time.time() * 1000))
        body_serialized = _json_dumps(ctx.body)
        prehash = f"{timestamp}{ctx.method.upper()}{path}{body_serialized}".encode()
        signature = self._signing_key.sign(prehash).signature
        headers = {
            "X-API-Key": self.api_key,
            "X-Timestamp": timestamp,
            "X-Signature": signature.hex(),
            "X-Signature-Type": self.signature_type,
        }
        return self._request(ctx, headers=headers)
