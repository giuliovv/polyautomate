"""Database utilities."""

import asyncio

from backend.db.session import Base, get_db, engine

__all__ = ["Base", "get_db", "engine", "init_db"]


async def init_db() -> None:
    """Create all database tables."""
    # Import models to register them with Base
    from backend import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables created successfully.")


def run_init_db() -> None:
    """CLI entry point for database initialization."""
    asyncio.run(init_db())
