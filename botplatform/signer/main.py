"""Signer service entry point."""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from signer.config import get_signer_settings
from signer.handlers import handle_sign_request, handle_post_order
from signer.models import (
    SignRequest,
    SignResponse,
    PostOrderRequest,
    PostOrderResponse,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

settings = get_signer_settings()

# Database setup (read-only access to wallets)
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Handle startup and shutdown."""
    yield
    await engine.dispose()


app = FastAPI(
    title="Bot Platform Signer",
    description="Isolated signing service for secure wallet management",
    version="0.1.0",
    lifespan=lifespan,
)


def get_client_ip(request: Request) -> str | None:
    """Extract client IP from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "signer"}


@app.post("/sign", response_model=SignResponse)
async def sign_order(request: SignRequest, http_request: Request) -> SignResponse:
    """Sign an order for Polymarket.

    This endpoint:
    1. Verifies the request signature from the backend
    2. Checks rate limits
    3. Retrieves and decrypts the wallet private key
    4. Signs the order using py_clob_client
    5. Returns the signed order (without posting it)
    """
    async with async_session_maker() as db:
        return await handle_sign_request(
            request,
            db,
            requester_ip=get_client_ip(http_request),
        )


@app.post("/post-order", response_model=PostOrderResponse)
async def post_order(request: PostOrderRequest, http_request: Request) -> PostOrderResponse:
    """Post a signed order to Polymarket CLOB.

    This endpoint:
    1. Verifies the request signature
    2. Retrieves wallet API credentials
    3. Posts the signed order to Polymarket
    """
    async with async_session_maker() as db:
        return await handle_post_order(
            request,
            db,
            requester_ip=get_client_ip(http_request),
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "signer.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
