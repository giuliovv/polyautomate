"""Bot service."""

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.bot import Bot


class BotService:
    """Service for bot-related operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, bot_id: str) -> Bot | None:
        """Get bot by ID."""
        result = await self.db.execute(select(Bot).where(Bot.id == bot_id))
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: str) -> Sequence[Bot]:
        """List all bots for a user."""
        result = await self.db.execute(
            select(Bot).where(Bot.user_id == user_id).order_by(Bot.created_at.desc())
        )
        return result.scalars().all()

    async def list_by_wallet(self, wallet_id: str) -> Sequence[Bot]:
        """List all bots for a wallet."""
        result = await self.db.execute(
            select(Bot).where(Bot.wallet_id == wallet_id).order_by(Bot.created_at.desc())
        )
        return result.scalars().all()

    async def create(
        self,
        user_id: str,
        wallet_id: str,
        name: str,
        strategy: str,
        config: dict | None = None,
        schedule: str | None = None,
        max_position_usd: float | None = None,
        daily_loss_limit_usd: float | None = None,
        max_actions_per_hour: int | None = None,
    ) -> Bot:
        """Create a new bot."""
        bot = Bot(
            user_id=user_id,
            wallet_id=wallet_id,
            name=name,
            strategy=strategy,
            config=config or {},
            schedule=schedule,
            max_position_usd=max_position_usd,
            daily_loss_limit_usd=daily_loss_limit_usd,
            max_actions_per_hour=max_actions_per_hour,
            status="stopped",
        )
        self.db.add(bot)
        await self.db.flush()
        await self.db.refresh(bot)
        return bot

    async def update(
        self,
        bot: Bot,
        name: str | None = None,
        config: dict | None = None,
        schedule: str | None = None,
        max_position_usd: float | None = None,
        daily_loss_limit_usd: float | None = None,
        max_actions_per_hour: int | None = None,
    ) -> Bot:
        """Update bot configuration."""
        if name is not None:
            bot.name = name
        if config is not None:
            bot.config = config
        if schedule is not None:
            bot.schedule = schedule
        if max_position_usd is not None:
            bot.max_position_usd = max_position_usd
        if daily_loss_limit_usd is not None:
            bot.daily_loss_limit_usd = daily_loss_limit_usd
        if max_actions_per_hour is not None:
            bot.max_actions_per_hour = max_actions_per_hour

        await self.db.flush()
        await self.db.refresh(bot)
        return bot

    async def start(self, bot: Bot) -> Bot:
        """Start a bot."""
        bot.status = "running"
        bot.error_count = 0
        await self.db.flush()
        await self.db.refresh(bot)
        return bot

    async def stop(self, bot: Bot) -> Bot:
        """Stop a bot."""
        bot.status = "stopped"
        await self.db.flush()
        await self.db.refresh(bot)
        return bot

    async def delete(self, bot: Bot) -> None:
        """Delete a bot."""
        await self.db.delete(bot)
        await self.db.flush()
