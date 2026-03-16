"""Cryptography utilities for the signer service."""

import hashlib
import hmac
import os
from typing import Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from signer.config import get_signer_settings

settings = get_signer_settings()


class SignerCrypto:
    """Cryptography utilities for envelope encryption."""

    def __init__(self) -> None:
        self._kms_client = None

    @property
    def kms_client(self):
        """Lazy-load KMS client."""
        if self._kms_client is None and settings.kms_key_id:
            import boto3

            self._kms_client = boto3.client("kms", region_name=settings.aws_region)
        return self._kms_client

    async def decrypt_private_key(
        self,
        encrypted_data: bytes,
        encrypted_dek: bytes,
    ) -> str:
        """Decrypt a private key using envelope encryption."""
        if self.kms_client and settings.kms_key_id:
            return await self._kms_decrypt(encrypted_data, encrypted_dek)
        else:
            return self._local_decrypt(encrypted_data, encrypted_dek)

    async def _kms_decrypt(
        self,
        encrypted_data: bytes,
        encrypted_dek: bytes,
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

    def _local_decrypt(self, encrypted_data: bytes, encrypted_dek: bytes) -> str:
        """Local decryption for development."""
        local_key = settings.backend_shared_secret.encode()[:32].ljust(32, b"\0")
        dek = self._aes_decrypt(local_key, encrypted_dek)
        plaintext = self._aes_decrypt(dek, encrypted_data)
        return plaintext.decode()

    def _aes_decrypt(self, key: bytes, data: bytes) -> bytes:
        """Decrypt using AES-256-GCM."""
        nonce = data[:12]
        ciphertext = data[12:]
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, None)


def verify_request_signature(
    payload: str,
    signature: str,
    timestamp: int,
) -> bool:
    """Verify HMAC signature from backend.

    The signature should be HMAC-SHA256(shared_secret, f"{timestamp}:{payload}")
    """
    message = f"{timestamp}:{payload}"
    expected_sig = hmac.new(
        settings.backend_shared_secret.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_sig, signature)


def generate_request_signature(payload: str, timestamp: int) -> str:
    """Generate HMAC signature for a request (used by backend/executor)."""
    message = f"{timestamp}:{payload}"
    return hmac.new(
        settings.backend_shared_secret.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()
