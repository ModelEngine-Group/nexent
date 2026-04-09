"""
AES-256-CBC encryption for OAuth provider tokens stored at rest.
"""

import base64
import logging
import os

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)

_ENCRYPTION_KEY = os.getenv("OAUTH_TOKEN_ENCRYPTION_KEY", "")


def _get_key() -> bytes:
    if not _ENCRYPTION_KEY:
        raise ValueError(
            "OAUTH_TOKEN_ENCRYPTION_KEY is not configured. "
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    key_bytes = _ENCRYPTION_KEY.encode("utf-8")
    if len(key_bytes) != 32:
        raise ValueError(
            f"OAUTH_TOKEN_ENCRYPTION_KEY must be 32 bytes (64 hex chars), got {len(key_bytes)} bytes"
        )
    return key_bytes


def encrypt_token(plaintext: str) -> str:
    if not plaintext:
        return ""

    key = _get_key()
    iv = os.urandom(16)

    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(plaintext.encode("utf-8")) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()

    return base64.b64encode(iv + ciphertext).decode("utf-8")


def decrypt_token(encrypted: str) -> str:
    if not encrypted:
        return ""

    key = _get_key()
    raw = base64.b64decode(encrypted.encode("utf-8"))

    iv = raw[:16]
    ciphertext = raw[16:]

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded_data = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(padded_data) + unpadder.finalize()

    return plaintext.decode("utf-8")
