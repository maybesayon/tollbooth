import asyncio
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from tollbooth.domain import Role, User
from tollbooth.security import hash_virtual_key

SESSION_COOKIE = "tollbooth_session"
CSRF_HEADER = "x-tollbooth-csrf"
SESSION_TOKEN_PREFIX = "tbs_"
API_TOKEN_PREFIX = "tbu_"
MIN_PASSWORD_LENGTH = 12

_hasher = PasswordHasher()
# Verified against when the email is unknown, so a miss costs as much as a wrong password.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    def check() -> bool:
        try:
            return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
        except (VerificationError, InvalidHashError):
            return False

    return await asyncio.to_thread(check)


def new_session_token() -> str:
    return SESSION_TOKEN_PREFIX + secrets.token_urlsafe(32)


def new_api_token() -> str:
    return API_TOKEN_PREFIX + secrets.token_urlsafe(32)


def new_temporary_password() -> str:
    return secrets.token_urlsafe(15)


def token_hash(token: str) -> str:
    """Session and API tokens carry 256 random bits, so unsalted SHA-256 is enough."""
    return hash_virtual_key(token)


def normalize_email(email: str) -> str:
    return email.strip().lower()


class Via(StrEnum):
    SESSION = "session"
    API_TOKEN = "api_token"
    ADMIN_TOKEN = "admin_token"


@dataclass(frozen=True)
class Principal:
    """Who is making an admin request: a user (by session or API token) or the admin token."""

    role: Role
    via: Via
    user: User | None = None
    session_hash: str | None = None

    @property
    def label(self) -> str:
        return self.user.email if self.user else "admin token"


@dataclass
class LoginThrottle:
    """Limits failed logins per email and per client address, in memory (per process)."""

    per_email: int = 5
    per_address: int = 20
    window_seconds: float = 900.0
    _failures: dict[str, deque[float]] = field(default_factory=dict)

    def retry_after(self, email: str, address: str) -> int:
        """Seconds until another attempt is allowed; 0 if allowed now."""
        now = time.monotonic()
        wait = 0.0
        for key, limit in (
            (f"email:{email}", self.per_email),
            (f"addr:{address}", self.per_address),
        ):
            attempts = self._recent(key, now)
            if len(attempts) >= limit:
                wait = max(wait, attempts[0] + self.window_seconds - now)
        return int(wait) + 1 if wait > 0 else 0

    def failed(self, email: str, address: str) -> None:
        now = time.monotonic()
        if len(self._failures) > 10_000:
            # Forget keys with no recent failures so random emails can't grow this forever.
            for key in [k for k in self._failures if not self._recent(k, now)]:
                del self._failures[key]
        for key in (f"email:{email}", f"addr:{address}"):
            self._recent(key, now).append(now)

    def succeeded(self, email: str) -> None:
        self._failures.pop(f"email:{email}", None)

    def _recent(self, key: str, now: float) -> deque[float]:
        attempts = self._failures.setdefault(key, deque())
        while attempts and attempts[0] <= now - self.window_seconds:
            attempts.popleft()
        return attempts


EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def password_problem(password: str, email: str | None = None) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"password must be at least {MIN_PASSWORD_LENGTH} characters"
    if len(password) > 256:
        return "password must be at most 256 characters"
    if email is not None and password.strip().lower() == email:
        return "password must not be the email address"
    return None
