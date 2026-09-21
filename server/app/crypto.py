"""Encrypt Google refresh tokens at rest (Fernet).

The key comes from TOKEN_ENCRYPTION_KEY. Tokens are only ever stored encrypted and are
never logged. If the key is missing, encryption fails loudly rather than storing
plaintext.
"""

from __future__ import annotations

from cryptography.fernet import Fernet

from .config import get_settings


class TokenCipher:
    def __init__(self, key: str | None = None):
        key = key if key is not None else get_settings().token_encryption_key
        if not key:
            raise RuntimeError(
                "TOKEN_ENCRYPTION_KEY is not set. Generate one with:\n"
                '  python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode()).decode()


def new_key() -> str:
    return Fernet.generate_key().decode()
