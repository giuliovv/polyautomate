"""Cryptography service for envelope encryption with AWS KMS."""

import base64
import os
from typing import Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.config import get_settings

settings = get_settings()


class CryptoService:
    """Service for encrypting/decrypting sensitive data using envelope encryption.

    In production, uses AWS KMS to generate and decrypt data encryption keys (DEKs).
    The DEK is used to encrypt the actual data (e.g., private keys) using AES-256-GCM.

    Flow:
    1. Request a new DEK from KMS (returns plaintext + encrypted versions)
    2. Use plaintext DEK to encrypt the data locally
    3. Store encrypted data + encrypted DEK
    4. To decrypt: ask KMS to decrypt the DEK, then decrypt data locally
    """

    def __init__(self) -> None:
        self._kms_client = None

    @property
    def kms_client(self):
        """Lazy-load KMS client."""
        if self._kms_client is None and settings.kms_key_id:
            import boto3

            self._kms_client = boto3.client("kms", region_name=settings.aws_region)
        return self._kms_client

    async def encrypt_private_key(self, private_key: str) -> Tuple[bytes, bytes]:
        """Encrypt a private key using envelope encryption.

        Returns:
            Tuple of (encrypted_data, encrypted_dek)
        """
        if self.kms_client and settings.kms_key_id:
            return await self._kms_encrypt(private_key)
        else:
            # Development fallback: use a local key
            return self._local_encrypt(private_key)

    async def decrypt_private_key(
        self, encrypted_data: bytes, encrypted_dek: bytes
    ) -> str:
        """Decrypt a private key using envelope encryption."""
        if self.kms_client and settings.kms_key_id:
            return await self._kms_decrypt(encrypted_data, encrypted_dek)
        else:
            return self._local_decrypt(encrypted_data, encrypted_dek)

    async def _kms_encrypt(self, plaintext: str) -> Tuple[bytes, bytes]:
        """Encrypt using AWS KMS envelope encryption."""
        # Generate a new data key
        response = self.kms_client.generate_data_key(
            KeyId=settings.kms_key_id,
            KeySpec="AES_256",
        )

        plaintext_dek = response["Plaintext"]
        encrypted_dek = response["CiphertextBlob"]

        # Encrypt the data with the plaintext DEK
        encrypted_data = self._aes_encrypt(plaintext_dek, plaintext.encode())

        return encrypted_data, encrypted_dek

    async def _kms_decrypt(
        self, encrypted_data: bytes, encrypted_dek: bytes
    ) -> str:
        """Decrypt using AWS KMS envelope encryption."""
        # Decrypt the DEK
        response = self.kms_client.decrypt(
            CiphertextBlob=encrypted_dek,
            KeyId=settings.kms_key_id,
        )
        plaintext_dek = response["Plaintext"]

        # Decrypt the data
        plaintext = self._aes_decrypt(plaintext_dek, encrypted_data)
        return plaintext.decode()

    def _local_encrypt(self, plaintext: str) -> Tuple[bytes, bytes]:
        """Local encryption for development (not for production use)."""
        # Generate a random DEK
        dek = os.urandom(32)
        # "Encrypt" the DEK with a local key (in production this would be KMS)
        local_key = settings.local_encryption_key.encode()[:32].ljust(32, b"\0")
        encrypted_dek = self._aes_encrypt(local_key, dek)

        # Encrypt the data
        encrypted_data = self._aes_encrypt(dek, plaintext.encode())

        return encrypted_data, encrypted_dek

    def _local_decrypt(self, encrypted_data: bytes, encrypted_dek: bytes) -> str:
        """Local decryption for development."""
        local_key = settings.local_encryption_key.encode()[:32].ljust(32, b"\0")
        dek = self._aes_decrypt(local_key, encrypted_dek)
        plaintext = self._aes_decrypt(dek, encrypted_data)
        return plaintext.decode()

    def _aes_encrypt(self, key: bytes, plaintext: bytes) -> bytes:
        """Encrypt using AES-256-GCM."""
        nonce = os.urandom(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        # Prepend nonce to ciphertext
        return nonce + ciphertext

    def _aes_decrypt(self, key: bytes, data: bytes) -> bytes:
        """Decrypt using AES-256-GCM."""
        nonce = data[:12]
        ciphertext = data[12:]
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, None)
