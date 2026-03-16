"""Bot execution runner."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from executor.config import get_executor_settings
from executor.signer_client import SignerClient
from executor.strategies.base import BaseExecutorStrategy, ExecutionContext
from executor.strategies.longshot import LongshotStrategy

LOGGER = logging.getLogger("executor.runner")

settings = get_executor_settings()

# Strategy registry
STRATEGY_REGISTRY: dict[str, type[BaseExecutorStrategy]] = {
    "longshot": LongshotStrategy,
}


class BotRunner:
    """Runs trading bots according to their schedules."""

    def __init__(self, db_url: str | None = None) -> None:
        self.engine = create_async_engine(
            db_url or settings.database_url,
            echo=False,
            pool_pre_ping=True,
        )
        self.session_maker = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self.signer = SignerClient()

    async def run_bot(self, bot_id: str) -> int:
        """Execute a single bot run.

        Returns the number of actions taken.
        """
        from backend.models.bot import Bot
        from backend.models.wallet import Wallet
        from backend.models.trade import Trade
        from backend.models.execution import Execution, ExecutionLog

        async with self.session_maker() as db:
            # Load bot
            result = await db.execute(select(Bot).where(Bot.id == bot_id))
            bot = result.scalar_one_or_none()

            if bot is None:
                LOGGER.error("bot_not_found bot_id=%s", bot_id)
                return 0

            if bot.status != "running":
                LOGGER.info("bot_not_running bot_id=%s status=%s", bot_id, bot.status)
                return 0

            # Load wallet
            result = await db.execute(select(Wallet).where(Wallet.id == bot.wallet_id))
            wallet = result.scalar_one_or_none()

            if wallet is None or wallet.status != "active":
                LOGGER.error("wallet_not_available bot_id=%s wallet_id=%s", bot_id, bot.wallet_id)
                return 0

            # Create execution record
            execution = Execution(
                bot_id=bot_id,
                trigger="scheduled",
                status="running",
            )
            db.add(execution)
            await db.flush()

            try:
                # Get strategy
                strategy_cls = STRATEGY_REGISTRY.get(bot.strategy)
                if strategy_cls is None:
                    raise ValueError(f"Unknown strategy: {bot.strategy}")

                strategy = strategy_cls(bot.config)

                # Get existing positions (open trades for this bot)
                result = await db.execute(
                    select(Trade.market_slug)
                    .where(Trade.bot_id == bot_id, Trade.status == "open")
                )
                existing_positions = [r[0] for r in result.fetchall()]

                # Build context
                # TODO: Fetch actual balance from Polymarket
                bankroll_usd = 500.0  # Default/placeholder

                context = ExecutionContext(
                    bot_id=bot_id,
                    wallet_id=str(bot.wallet_id),
                    bankroll_usd=bankroll_usd,
                    config=bot.config,
                    existing_positions=existing_positions,
                )

                # Scan for candidates
                candidates = await strategy.scan_candidates(context)
                LOGGER.info(
                    "scan_complete bot_id=%s candidates=%d",
                    bot_id,
                    len(candidates),
                )

                actions_taken = 0
                max_actions = bot.max_actions_per_hour or 5

                for candidate in candidates[:max_actions]:
                    # Compute order
                    order_result = await strategy.compute_order(candidate, context)
                    if order_result is None:
                        continue

                    order, sizing = order_result

                    if settings.dry_run:
                        LOGGER.info(
                            "dry_run_order bot_id=%s slug=%s size=%.2f price=%.4f",
                            bot_id,
                            candidate.slug,
                            order.size,
                            order.price,
                        )
                        actions_taken += 1
                        continue

                    # Sign and post order
                    request_id = str(uuid4())
                    try:
                        result = await self.signer.sign_and_post(
                            request_id=request_id,
                            wallet_id=str(bot.wallet_id),
                            order_payload={
                                "token_id": order.token_id,
                                "side": order.side,
                                "price": order.price,
                                "size": order.size,
                            },
                            bot_id=bot_id,
                        )

                        if result.get("success"):
                            order_id = result.get("order_id", request_id)

                            # Record trade
                            trade = Trade(
                                bot_id=bot_id,
                                execution_id=execution.id,
                                wallet_id=bot.wallet_id,
                                market_slug=candidate.slug,
                                market_question=candidate.question,
                                token_id=order.token_id,
                                side=order.side,
                                entry_price=order.price,
                                entry_size=order.size,
                                entry_notional_usd=sizing.notional_usd,
                                entry_order_id=order_id,
                                entry_timestamp=datetime.now(timezone.utc),
                                status="open",
                            )
                            db.add(trade)

                            await strategy.on_order_placed(candidate, order, order_id, context)
                            actions_taken += 1
                        else:
                            error = result.get("error", "Unknown error")
                            await strategy.on_order_failed(candidate, order, error, context)

                    except Exception as e:
                        LOGGER.exception("order_exception bot_id=%s", bot_id)
                        await strategy.on_order_failed(candidate, order, str(e), context)

                # Update execution record
                execution.status = "completed"
                execution.finished_at = datetime.now(timezone.utc)
                execution.actions_taken = actions_taken

                # Update bot last_run_at
                await db.execute(
                    update(Bot)
                    .where(Bot.id == bot_id)
                    .values(last_run_at=datetime.now(timezone.utc))
                )

                await db.commit()
                return actions_taken

            except Exception as e:
                LOGGER.exception("bot_run_failed bot_id=%s", bot_id)
                execution.status = "failed"
                execution.finished_at = datetime.now(timezone.utc)
                execution.error_message = str(e)

                # Increment error count
                await db.execute(
                    update(Bot)
                    .where(Bot.id == bot_id)
                    .values(error_count=Bot.error_count + 1)
                )

                await db.commit()
                return 0

    async def run_all_active_bots(self) -> dict[str, int]:
        """Run all bots that are in 'running' status.

        Returns a dict mapping bot_id to actions taken.
        """
        from backend.models.bot import Bot

        async with self.session_maker() as db:
            result = await db.execute(
                select(Bot.id).where(Bot.status == "running")
            )
            bot_ids = [r[0] for r in result.fetchall()]

        LOGGER.info("running_bots count=%d", len(bot_ids))

        results = {}
        for bot_id in bot_ids:
            try:
                actions = await self.run_bot(bot_id)
                results[bot_id] = actions
            except Exception:
                LOGGER.exception("bot_run_error bot_id=%s", bot_id)
                results[bot_id] = 0

        return results

    async def close(self) -> None:
        """Clean up resources."""
        await self.signer.close()
        await self.engine.dispose()


async def main() -> None:
    """Main entry point for the executor."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    runner = BotRunner()

    try:
        while True:
            LOGGER.info("poll_start")
            results = await runner.run_all_active_bots()

            total_actions = sum(results.values())
            LOGGER.info("poll_complete bots=%d actions=%d", len(results), total_actions)

            await asyncio.sleep(settings.poll_interval_seconds)

    except KeyboardInterrupt:
        LOGGER.info("shutdown_requested")
    finally:
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
