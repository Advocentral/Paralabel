from __future__ import annotations

import pytest

from server.app.crypto import TokenCipher, new_key


def test_roundtrip():
    cipher = TokenCipher(new_key())
    secret = "1//refresh-token-value"
    assert cipher.decrypt(cipher.encrypt(secret)) == secret


def test_ciphertext_is_not_plaintext():
    cipher = TokenCipher(new_key())
    enc = cipher.encrypt("sensitive")
    assert "sensitive" not in enc


def test_missing_key_raises():
    with pytest.raises(RuntimeError):
        TokenCipher("")
