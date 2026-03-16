"""Wallet API endpoints."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from backend.dependencies import CurrentUser, DbSession
from backend.services.wallet_service import WalletService

router = APIRouter()


class WalletResponse(BaseModel):
    """Wallet response."""

    id: str
    name: str
    address: str
    signer_address: str
    wallet_type: str
    signature_type: int
    status: str

    class Config:
        from_attributes = True


class CreatePlatformWalletRequest(BaseModel):
    """Request to create a platform-managed wallet."""

    name: str


class CreateDelegatedWalletRequest(BaseModel):
    """Request to create a delegated wallet."""

    name: str
    address: str
    signer_address: str
    signature_type: int = 1
    api_key: str | None = None
    api_secret: str | None = None
    api_passphrase: str | None = None


@router.post("", response_model=WalletResponse, status_code=status.HTTP_201_CREATED)
async def create_platform_wallet(
    request: CreatePlatformWalletRequest,
    user: CurrentUser,
    db: DbSession,
) -> WalletResponse:
    """Create a new platform-managed wallet."""
    wallet_service = WalletService(db)
    wallet = await wallet_service.create_platform_managed(
        user_id=user.id,
        name=request.name,
    )
    return WalletResponse.model_validate(wallet)


@router.post("/delegate", response_model=WalletResponse, status_code=status.HTTP_201_CREATED)
async def create_delegated_wallet(
    request: CreateDelegatedWalletRequest,
    user: CurrentUser,
    db: DbSession,
) -> WalletResponse:
    """Link an existing wallet via delegation."""
    wallet_service = WalletService(db)
    wallet = await wallet_service.create_delegated(
        user_id=user.id,
        name=request.name,
        address=request.address,
        signer_address=request.signer_address,
        signature_type=request.signature_type,
        api_key=request.api_key,
        api_secret=request.api_secret,
        api_passphrase=request.api_passphrase,
    )
    return WalletResponse.model_validate(wallet)


@router.get("", response_model=list[WalletResponse])
async def list_wallets(user: CurrentUser, db: DbSession) -> list[WalletResponse]:
    """List all wallets for the current user."""
    wallet_service = WalletService(db)
    wallets = await wallet_service.list_by_user(user.id)
    return [WalletResponse.model_validate(w) for w in wallets]


@router.get("/{wallet_id}", response_model=WalletResponse)
async def get_wallet(
    wallet_id: str,
    user: CurrentUser,
    db: DbSession,
) -> WalletResponse:
    """Get wallet details."""
    wallet_service = WalletService(db)
    wallet = await wallet_service.get_by_id(wallet_id)

    if wallet is None or wallet.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found",
        )

    return WalletResponse.model_validate(wallet)


@router.delete("/{wallet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wallet(
    wallet_id: str,
    user: CurrentUser,
    db: DbSession,
) -> None:
    """Delete a wallet."""
    wallet_service = WalletService(db)
    wallet = await wallet_service.get_by_id(wallet_id)

    if wallet is None or wallet.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found",
        )

    await wallet_service.delete(wallet)
