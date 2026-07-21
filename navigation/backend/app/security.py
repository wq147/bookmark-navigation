"""Security primitives for authentication."""

import hashlib
import secrets
import time
from collections import OrderedDict, deque
from threading import RLock

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

password_hash = PasswordHasher()
_dummy_hash = password_hash.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(stored_hash: str | None, supplied_password: str) -> bool:
    """Verify real and missing users with comparable Argon2 work."""

    try:
        return password_hash.verify(stored_hash or _dummy_hash, supplied_password)
    except VerificationError:
        return False


def new_session_tokens() -> tuple[str, str, str]:
    raw = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return raw, digest, csrf


def digest_session_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class LoginFailureLimiter:
    """Bounded, process-local sliding window keyed by user and peer IP."""

    def __init__(self, limit: int = 5, window_seconds: int = 300, max_keys: int = 1024):
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._failures: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()
        self._lock = RLock()

    def _key(self, username: str, client_ip: str) -> tuple[str, str]:
        return username.strip().casefold(), client_ip

    def is_limited(self, username: str, client_ip: str) -> bool:
        with self._lock:
            key = self._key(username, client_ip)
            failures = self._failures.get(key)
            if failures is None:
                return False
            cutoff = time.monotonic() - self.window_seconds
            while failures and failures[0] < cutoff:
                failures.popleft()
            return len(failures) >= self.limit

    def record_failure(self, username: str, client_ip: str) -> None:
        with self._lock:
            key = self._key(username, client_ip)
            failures = self._failures.setdefault(key, deque())
            failures.append(time.monotonic())
            self._failures.move_to_end(key)
            while len(self._failures) > self.max_keys:
                self._failures.popitem(last=False)

    def clear(self, username: str, client_ip: str) -> None:
        with self._lock:
            self._failures.pop(self._key(username, client_ip), None)
