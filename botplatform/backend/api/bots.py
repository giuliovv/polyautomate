"""Bot API endpoints."""

from decimal import Decimal
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from backend.dependencies import CurrentUser, DbSession
from backend.services.bot_service import BotService
from backend.services.wallet_service import WalletService

router = APIRouter()


class BotResponse(BaseModel):
    """Bot response."""

    id: str
    wallet_id: str
    name: str
    strategy: str
    config: dict
    schedule: str | None
    max_position_usd: Decimal | None
    daily_loss_limit_usd: Decimal | None
    max_actions_per_hour: int | None
    status: str
    last_run_at: datetime | None
    error_count: int

    class Config:
        from_attributes = True


class CreateBotRequest(BaseModel):
    """Request to create a bot."""

    wallet_id: str
    name: str
    strategy: str
    config: dict | None = None
    schedule: str | None = None
    max_position_usd: float | None = None
    daily_loss_limit_usd: float | None = None
    max_actions_per_hour: int | None = None


class UpdateBotRequest(BaseModel):
    """Request to update a bot."""

    name: str | None = None
    config: dict | None = None
    schedule: str | None = None
    max_position_usd: float | None = None
    daily_loss_limit_usd: float | None = None
    max_actions_per_hour: int | None = None


@router.post("", response_model=BotResponse, status_code=status.HTTP_201_CREATED)
async def create_bot(
    request: CreateBotRequest,
    user: CurrentUser,
    db: DbSession,
) -> BotResponse:
    """Create a new bot."""
    # Verify wallet ownership
    wallet_service = WalletService(db)
    wallet = await wallet_service.get_by_id(request.wallet_id)
    if wallet is None or wallet.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found",
        )

    bot_service = BotService(db)
    bot = await bot_service.create(
        user_id=user.id,
        wallet_id=request.wallet_id,
        name=request.name,
        strategy=request.strategy,
        config=request.config,
        schedule=request.schedule,
        max_position_usd=request.max_position_usd,
        daily_loss_limit_usd=request.daily_loss_limit_usd,
        max_actions_per_hour=request.max_actions_per_hour,
    )
    return BotResponse.model_validate(bot)


@router.get("", response_model=list[BotResponse])
async def list_bots(user: CurrentUser, db: DbSession) -> list[BotResponse]:
    """List all bots for the current user."""
    bot_service = BotService(db)
    bots = await bot_service.list_by_user(user.id)
    return [BotResponse.model_validate(b) for b in bots]


@router.get("/{bot_id}", response_model=BotResponse)
async def get_bot(
    bot_id: str,
    user: CurrentUser,
    db: DbSession,
) -> BotResponse:
    """Get bot details."""
    bot_service = BotService(db)
    bot = await bot_service.get_by_id(bot_id)

    if bot is None or bot.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bot not found",
        )

    return BotResponse.model_validate(bot)


@router.patch("/{bot_id}", response_model=BotResponse)
async def update_bot(
    bot_id: str,
    request: UpdateBotRequest,
    user: CurrentUser,
    db: DbSession,
) -> BotResponse:
    """Update bot configuration."""
    bot_service = BotService(db)
    bot = await bot_service.get_by_id(bot_id)

    if bot is None or bot.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bot not found",
        )

    if bot.status == "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot update a running bot. Stop it first.",
        )

    bot = await bot_service.update(
        bot,
        name=request.name,
        config=request.config,
        schedule=request.schedule,
        max_position_usd=request.max_position_usd,
        daily_loss_limit_usd=request.daily_loss_limit_usd,
        max_actions_per_hour=request.max_actions_per_hour,
    )
    return BotResponse.model_validate(bot)


@router.post("/{bot_id}/start", response_model=BotResponse)
async def start_bot(
    bot_id: str,
    user: CurrentUser,
    db: DbSession,
) -> BotResponse:
    """Start a bot."""
    bot_service = BotService(db)
    bot = await bot_service.get_by_id(bot_id)

    if bot is None or bot.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bot not found",
        )

    if bot.status == "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bot is already running",
        )

    bot = await bot_service.start(bot)
    return BotResponse.model_validate(bot)


@router.post("/{bot_id}/stop", response_model=BotResponse)
async def stop_bot(
    bot_id: str,
    user: CurrentUser,
    db: DbSession,
) -> BotResponse:
    """Stop a bot."""
    bot_service = BotService(db)
    bot = await bot_service.get_by_id(bot_id)

    if bot is None or bot.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bot not found",
        )

    if bot.status != "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bot is not running",
        )

    bot = await bot_service.stop(bot)
    return BotResponse.model_validate(bot)


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(
    bot_id: str,
    user: CurrentUser,
    db: DbSession,
) -> None:
    """Delete a bot."""
    bot_service = BotService(db)
    bot = await bot_service.get_by_id(bot_id)

    if bot is None or bot.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bot not found",
        )

    if bot.status == "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a running bot. Stop it first.",
        )

    await bot_service.delete(bot)
