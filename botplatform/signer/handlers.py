"""Request handlers for the signing service."""

import json
import time
from collections import defaultdict
from datetime import datetime, timezone

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signer.audit import AuditLogger
from signer.config import get_signer_settings
from signer.crypto import SignerCrypto, verify_request_signature
from signer.models import (
    SignRequest,
    SignResponse,
    PostOrderRequest,
    PostOrderResponse,
    BalanceRequest,
    BalanceResponse,
)

settings = get_signer_settings()


class RateLimiter:
    """Simple in-memory rate limiter."""

    def __init__(self) -> None:
        self.requests: dict[str, list[float]] = defaultdict(list)

    def is_limited(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        """Check if key has exceeded rate limit."""
        now = time.time()
        cutoff = now - window_seconds

        # Clean old entries
        self.requests[key] = [t for t in self.requests[key] if t > cutoff]

        if len(self.requests[key]) >= limit:
            return True

        self.requests[key].append(now)
        return False


# Global rate limiter (in production, use Redis)
rate_limiter = RateLimiter()


async def handle_sign_request(
    request: SignRequest,
    db: AsyncSession,
    requester_ip: str | None = None,
) -> SignResponse:
    """Handle an order signing request.

    1. Verify request signature
    2. Check rate limits
    3. Retrieve wallet and decrypt private key
    4. Sign order using py_clob_client
    5. Return signed order
    """
    crypto = SignerCrypto()
    audit = AuditLogger()

    # Verify request signature
    payload_str = json.dumps(request.order_payload, sort_keys=True)
    if not verify_request_signature(payload_str, request.signature, request.timestamp):
        await audit.log_auth_failure(request.request_id, "invalid_signature", requester_ip)
        return SignResponse(
            request_id=request.request_id,
            success=False,
            error="Invalid request signature",
        )

    # Check timestamp freshness (within 5 minutes)
    now = int(time.time())
    if abs(now - request.timestamp) > 300:
        await audit.log_auth_failure(request.request_id, "stale_timestamp", requester_ip)
        return SignResponse(
            request_id=request.request_id,
            success=False,
            error="Request timestamp too old",
        )

    # Check rate limits
    wallet_key = f"wallet:{request.wallet_id}"
    if rate_limiter.is_limited(wallet_key, settings.rate_limit_per_wallet_per_minute):
        await audit.log_rate_limit(request.request_id, request.wallet_id, request.bot_id)
        return SignResponse(
            request_id=request.request_id,
            success=False,
            error="Wallet rate limit exceeded",
        )

    if request.bot_id:
        bot_key = f"bot:{request.bot_id}"
        if rate_limiter.is_limited(bot_key, settings.rate_limit_per_bot_per_minute):
            await audit.log_rate_limit(request.request_id, request.wallet_id, request.bot_id)
            return SignResponse(
                request_id=request.request_id,
                success=False,
                error="Bot rate limit exceeded",
            )

    # Start audit trail
    audit_id = await audit.log_sign_request(
        request.request_id,
        request.wallet_id,
        request.bot_id,
        request.order_payload,
        requester_ip,
    )

    try:
        # Import Wallet model here to avoid circular imports
        from backend.models.wallet import Wallet

        # Retrieve wallet
        result = await db.execute(select(Wallet).where(Wallet.id == request.wallet_id))
        wallet = result.scalar_one_or_none()

        if wallet is None:
            await audit.log_sign_failure(audit_id, request.request_id, "wallet_not_found")
            return SignResponse(
                request_id=request.request_id,
                success=False,
                error="Wallet not found",
            )

        if wallet.status != "active":
            await audit.log_sign_failure(audit_id, request.request_id, "wallet_not_active")
            return SignResponse(
                request_id=request.request_id,
                success=False,
                error="Wallet is not active",
            )

        if wallet.wallet_type != "platform_managed":
            await audit.log_sign_failure(audit_id, request.request_id, "not_platform_managed")
            return SignResponse(
                request_id=request.request_id,
                success=False,
                error="Only platform-managed wallets can be signed",
            )

        # Decrypt private key
        private_key = await crypto.decrypt_private_key(
            wallet.encrypted_private_key,
            wallet.encrypted_dek,
        )

        # Create py_clob_client and sign order
        client = ClobClient(
            settings.polymarket_clob_url,
            chain_id=settings.polymarket_chain_id,
            key=private_key,
            signature_type=wallet.signature_type,
            funder=wallet.address,
        )

        # Build order args
        order_args = OrderArgs(
            token_id=request.order_payload["token_id"],
            price=float(request.order_payload["price"]),
            size=float(request.order_payload["size"]),
            side=request.order_payload["side"].upper(),  # BUY or SELL
        )

        # Sign the order
        signed_order = client.create_order(order_args)

        # Clear sensitive data
        del private_key

        await audit.log_sign_success(audit_id, request.request_id)

        return SignResponse(
            request_id=request.request_id,
            success=True,
            signed_order=signed_order,
        )

    except Exception as e:
        await audit.log_sign_failure(audit_id, request.request_id, str(e))
        return SignResponse(
            request_id=request.request_id,
            success=False,
            error=str(e),
        )


async def handle_post_order(
    request: PostOrderRequest,
    db: AsyncSession,
    requester_ip: str | None = None,
) -> PostOrderResponse:
    """Post a signed order to Polymarket CLOB.

    This requires API credentials (api_key, api_secret, api_passphrase).
    """
    crypto = SignerCrypto()
    audit = AuditLogger()

    # Verify request signature
    payload_str = json.dumps(request.signed_order, sort_keys=True)
    if not verify_request_signature(payload_str, request.signature, request.timestamp):
        return PostOrderResponse(
            request_id=request.request_id,
            success=False,
            error="Invalid request signature",
        )

    try:
        from backend.models.wallet import Wallet

        # Retrieve wallet
        result = await db.execute(select(Wallet).where(Wallet.id == request.wallet_id))
        wallet = result.scalar_one_or_none()

        if wallet is None:
            return PostOrderResponse(
                request_id=request.request_id,
                success=False,
                error="Wallet not found",
            )

        # Decrypt credentials
        private_key = await crypto.decrypt_private_key(
            wallet.encrypted_private_key,
            wallet.encrypted_dek,
        )

        api_key = None
        api_secret = None
        api_passphrase = None

        if wallet.encrypted_api_key:
            api_key = await crypto.decrypt_private_key(
                wallet.encrypted_api_key,
                wallet.encrypted_dek,
            )
        if wallet.encrypted_api_secret:
            api_secret = await crypto.decrypt_private_key(
                wallet.encrypted_api_secret,
                wallet.encrypted_dek,
            )
        if wallet.encrypted_api_passphrase:
            api_passphrase = await crypto.decrypt_private_key(
                wallet.encrypted_api_passphrase,
                wallet.encrypted_dek,
            )

        # Create client
        client = ClobClient(
            settings.polymarket_clob_url,
            chain_id=settings.polymarket_chain_id,
            key=private_key,
            signature_type=wallet.signature_type,
            funder=wallet.address,
        )

        if api_key and api_secret and api_passphrase:
            client.set_api_creds(ApiCreds(api_key, api_secret, api_passphrase))

        # Post the order
        response = client.post_order(
            request.signed_order,
            OrderType.GTC,
            post_only=request.post_only,
        )

        # Clear sensitive data
        del private_key

        return PostOrderResponse(
            request_id=request.request_id,
            success=True,
            order_id=response.get("orderID"),
            status=response.get("status"),
        )

    except Exception as e:
        return PostOrderResponse(
            request_id=request.request_id,
            success=False,
            error=str(e),
        )
