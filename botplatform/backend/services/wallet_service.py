"""Wallet service."""

from typing import Sequence

from eth_account import Account
from mnemonic import Mnemonic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.wallet import Wallet
from backend.services.crypto_service import CryptoService


class WalletService:
    """Service for wallet-related operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.crypto = CryptoService()
        self.mnemo = Mnemonic("english")

    async def get_by_id(self, wallet_id: str) -> Wallet | None:
        """Get wallet by ID."""
        result = await self.db.execute(select(Wallet).where(Wallet.id == wallet_id))
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: str) -> Sequence[Wallet]:
        """List all wallets for a user."""
        result = await self.db.execute(
            select(Wallet).where(Wallet.user_id == user_id).order_by(Wallet.created_at.desc())
        )
        return result.scalars().all()

    async def create_platform_managed(
        self,
        user_id: str,
        name: str,
    ) -> Wallet:
        """Create a new platform-managed wallet.

        Generates a new Ethereum account and encrypts the private key.
        """
        # Generate new account
        account = Account.create()
        private_key = account.key.hex()
        address = account.address

        # Encrypt private key using envelope encryption
        encrypted_key, encrypted_dek = await self.crypto.encrypt_private_key(private_key)

        # Get next derivation index for this user
        existing = await self.list_by_user(user_id)
        derivation_index = len(existing)

        wallet = Wallet(
            user_id=user_id,
            name=name,
            address=address,
            signer_address=address,
            wallet_type="platform_managed",
            signature_type=0,  # EOA
            encrypted_private_key=encrypted_key,
            encrypted_dek=encrypted_dek,
            derivation_index=derivation_index,
            status="active",
        )
        self.db.add(wallet)
        await self.db.flush()
        await self.db.refresh(wallet)
        return wallet

    async def create_delegated(
        self,
        user_id: str,
        name: str,
        address: str,
        signer_address: str,
        signature_type: int = 1,
        api_key: str | None = None,
        api_secret: str | None = None,
        api_passphrase: str | None = None,
    ) -> Wallet:
        """Create a delegated wallet (user provides credentials)."""
        encrypted_api_key = None
        encrypted_api_secret = None
        encrypted_api_passphrase = None

        # Encrypt API credentials if provided
        if api_key:
            encrypted_api_key, _ = await self.crypto.encrypt_private_key(api_key)
        if api_secret:
            encrypted_api_secret, _ = await self.crypto.encrypt_private_key(api_secret)
        if api_passphrase:
            encrypted_api_passphrase, _ = await self.crypto.encrypt_private_key(api_passphrase)

        wallet = Wallet(
            user_id=user_id,
            name=name,
            address=address.lower(),
            signer_address=signer_address.lower(),
            wallet_type="delegated",
            signature_type=signature_type,
            encrypted_api_key=encrypted_api_key,
            encrypted_api_secret=encrypted_api_secret,
            encrypted_api_passphrase=encrypted_api_passphrase,
            status="active",
        )
        self.db.add(wallet)
        await self.db.flush()
        await self.db.refresh(wallet)
        return wallet

    async def get_decrypted_private_key(self, wallet: Wallet) -> str | None:
        """Decrypt and return the private key for a platform-managed wallet."""
        if wallet.wallet_type != "platform_managed":
            return None
        if wallet.encrypted_private_key is None or wallet.encrypted_dek is None:
            return None

        return await self.crypto.decrypt_private_key(
            wallet.encrypted_private_key,
            wallet.encrypted_dek,
        )

    async def delete(self, wallet: Wallet) -> None:
        """Delete a wallet."""
        await self.db.delete(wallet)
        await self.db.flush()
