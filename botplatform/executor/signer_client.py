"""Client for communicating with the signing service."""

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from executor.config import get_executor_settings

settings = get_executor_settings()


class SignerClient:
    """Client for the signing service."""

    def __init__(self, base_url: str | None = None, shared_secret: str | None = None) -> None:
        self.base_url = base_url or settings.signer_url
        self.shared_secret = shared_secret or settings.signer_shared_secret
        self._client = httpx.AsyncClient(timeout=30.0)

    def _sign_payload(self, payload: str, timestamp: int) -> str:
        """Generate HMAC signature for a payload."""
        message = f"{timestamp}:{payload}"
        return hmac.new(
            self.shared_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()

    async def sign_order(
        self,
        request_id: str,
        wallet_id: str,
        order_payload: dict[str, Any],
        bot_id: str | None = None,
    ) -> dict[str, Any]:
        """Request an order to be signed.

        Args:
            request_id: Unique request ID for idempotency
            wallet_id: UUID of the wallet to sign with
            order_payload: Order details {token_id, side, price, size}
            bot_id: Optional bot UUID for tracking

        Returns:
            SignResponse dict with success, signed_order, or error
        """
        timestamp = int(time.time())
        payload_str = json.dumps(order_payload, sort_keys=True)
        signature = self._sign_payload(payload_str, timestamp)

        request_data = {
            "request_id": request_id,
            "wallet_id": wallet_id,
            "bot_id": bot_id,
            "order_payload": order_payload,
            "timestamp": timestamp,
            "signature": signature,
        }

        response = await self._client.post(
            f"{self.base_url}/sign",
            json=request_data,
        )
        response.raise_for_status()
        return response.json()

    async def post_order(
        self,
        request_id: str,
        wallet_id: str,
        signed_order: dict[str, Any],
        bot_id: str | None = None,
        post_only: bool = True,
    ) -> dict[str, Any]:
        """Post a signed order to Polymarket.

        Args:
            request_id: Unique request ID
            wallet_id: UUID of the wallet
            signed_order: The signed order from sign_order()
            bot_id: Optional bot UUID
            post_only: Whether to use post-only mode

        Returns:
            PostOrderResponse dict
        """
        timestamp = int(time.time())
        payload_str = json.dumps(signed_order, sort_keys=True)
        signature = self._sign_payload(payload_str, timestamp)

        request_data = {
            "request_id": request_id,
            "wallet_id": wallet_id,
            "bot_id": bot_id,
            "signed_order": signed_order,
            "post_only": post_only,
            "timestamp": timestamp,
            "signature": signature,
        }

        response = await self._client.post(
            f"{self.base_url}/post-order",
            json=request_data,
        )
        response.raise_for_status()
        return response.json()

    async def sign_and_post(
        self,
        request_id: str,
        wallet_id: str,
        order_payload: dict[str, Any],
        bot_id: str | None = None,
        post_only: bool = True,
    ) -> dict[str, Any]:
        """Sign and post an order in one operation.

        This is a convenience method that calls sign_order then post_order.
        """
        # Sign the order
        sign_result = await self.sign_order(request_id, wallet_id, order_payload, bot_id)
        if not sign_result.get("success"):
            return sign_result

        # Post the signed order
        post_result = await self.post_order(
            request_id=f"{request_id}-post",
            wallet_id=wallet_id,
            signed_order=sign_result["signed_order"],
            bot_id=bot_id,
            post_only=post_only,
        )
        return post_result

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
