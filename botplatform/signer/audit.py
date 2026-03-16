"""Audit logging for signing operations."""

import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

# Note: In production, this would be a separate audit-specific table
# For now, we log to stdout in a structured format

logger = logging.getLogger("signer.audit")


class AuditLogger:
    """Structured audit logging for all signing operations."""

    def __init__(self, db: AsyncSession | None = None) -> None:
        self.db = db

    async def log_sign_request(
        self,
        request_id: str,
        wallet_id: str,
        bot_id: str | None,
        order_payload: dict,
        requester_ip: str | None = None,
    ) -> str:
        """Log the start of a signing request."""
        audit_id = str(uuid4())
        entry = {
            "audit_id": audit_id,
            "event": "sign_request_started",
            "request_id": request_id,
            "wallet_id": wallet_id,
            "bot_id": bot_id,
            "order_payload": order_payload,
            "requester_ip": requester_ip,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(json.dumps(entry))
        return audit_id

    async def log_sign_success(
        self,
        audit_id: str,
        request_id: str,
        order_id: str | None = None,
    ) -> None:
        """Log successful signing."""
        entry = {
            "audit_id": audit_id,
            "event": "sign_request_success",
            "request_id": request_id,
            "order_id": order_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(json.dumps(entry))

    async def log_sign_failure(
        self,
        audit_id: str,
        request_id: str,
        error: str,
    ) -> None:
        """Log signing failure."""
        entry = {
            "audit_id": audit_id,
            "event": "sign_request_failed",
            "request_id": request_id,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.warning(json.dumps(entry))

    async def log_rate_limit(
        self,
        request_id: str,
        wallet_id: str,
        bot_id: str | None,
    ) -> None:
        """Log rate limit hit."""
        entry = {
            "event": "rate_limit_exceeded",
            "request_id": request_id,
            "wallet_id": wallet_id,
            "bot_id": bot_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.warning(json.dumps(entry))

    async def log_auth_failure(
        self,
        request_id: str,
        reason: str,
        requester_ip: str | None = None,
    ) -> None:
        """Log authentication failure."""
        entry = {
            "event": "auth_failure",
            "request_id": request_id,
            "reason": reason,
            "requester_ip": requester_ip,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.warning(json.dumps(entry))
