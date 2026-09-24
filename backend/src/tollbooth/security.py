import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

VIRTUAL_KEY_PREFIX = "tb_"
_DISPLAY_PREFIX_LEN = len(VIRTUAL_KEY_PREFIX) + 8


@dataclass(frozen=True)
class NewVirtualKey:
    plaintext: str
    key_hash: str
    display_prefix: str


def new_id() -> str:
    return uuid.uuid4().hex


def generate_virtual_key() -> NewVirtualKey:
    plaintext = VIRTUAL_KEY_PREFIX + secrets.token_urlsafe(32)
    return NewVirtualKey(
        plaintext=plaintext,
        key_hash=hash_virtual_key(plaintext),
        display_prefix=plaintext[:_DISPLAY_PREFIX_LEN],
    )


def hash_virtual_key(plaintext: str) -> str:
    """Unsalted SHA-256 is enough: keys carry 256 random bits, so they can't be brute-forced."""
    return hashlib.sha256(plaintext.encode()).hexdigest()


def tokens_match(presented: str, expected: str) -> bool:
    return hmac.compare_digest(presented.encode(), expected.encode())


class DecryptionError(Exception):
    pass


class SecretBox:
    """Fernet encryption for provider keys.

    Accepts a comma-separated list of keys: the first encrypts, all are tried for decryption, which
    allows key rotation without re-encrypting everything at once.
    """

    def __init__(self, keys: str) -> None:
        parts = [k.strip() for k in keys.split(",") if k.strip()]
        if not parts:
            raise ValueError("at least one encryption key is required")
        self._fernet = MultiFernet([Fernet(k) for k in parts])

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as e:
            raise DecryptionError(
                "provider key could not be decrypted with the configured keys"
            ) from e
