"""Guest account of LAN sharing (F-100, F-105): password, sessions, lockout.

A single guest account, usable by several people at once. Its password is set
by the owner in Preferences > Interface and stored as an argon2 hash in
$XDG_CONFIG_HOME/kvm-studio/guest.hash. A login opens a session (cookie,
HttpOnly, Secure, SameSite=Strict) that expires after inactivity. Too many
failures from one address lock it out for a while.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

from ..config import config_dir

COOKIE = "kvmstudio_session"
SESSION_IDLE_S = 30 * 60
LOCKOUT_S = 5 * 60
MIN_PASSWORD = 8
MAX_PASSWORD = 256

_hasher = PasswordHasher()


def hash_path() -> Path:
    return config_dir() / "guest.hash"


def has_password(path: Path | None = None) -> bool:
    try:
        return (path or hash_path()).read_text(encoding="ascii").startswith("$argon2")
    except OSError:
        return False


def set_password(password: str, path: Path | None = None) -> None:
    """Store the argon2 hash only, readable by the user alone."""
    path = path or hash_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as out:
        out.write(_hasher.hash(password) + "\n")
    os.replace(tmp, path)


def check_password(password: str, path: Path | None = None) -> bool:
    try:
        stored = (path or hash_path()).read_text(encoding="ascii").strip()
        return bool(_hasher.verify(stored, password))
    # A malformed hash raises InvalidHash in argon2-cffi 21 (Debian 13) and
    # InvalidHashError later, both ValueError: only Argon2Error exists everywhere.
    except (OSError, ValueError, Argon2Error):
        return False


@dataclass(slots=True)
class Session:
    address: str
    created: float
    seen: float


class GuestSessions:
    """Open guest sessions, by random id, forgotten after SESSION_IDLE_S without a request."""

    def __init__(self, idle: float = SESSION_IDLE_S) -> None:
        self._idle = idle
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def open(self, address: str) -> str:
        sid = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._sessions[sid] = Session(address, now, now)
        return sid

    def touch(self, sid: str | None) -> bool:
        """True when the session is open; it then lasts SESSION_IDLE_S longer."""
        if not sid:
            return False
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            session = self._sessions.get(sid)
            if session is None:
                return False
            session.seen = now
            return True

    def close(self, sid: str | None) -> None:
        with self._lock:
            self._sessions.pop(sid or "", None)

    def close_all(self) -> None:
        with self._lock:
            self._sessions.clear()

    def count(self) -> int:
        with self._lock:
            self._expire(time.monotonic())
            return len(self._sessions)

    def _expire(self, now: float) -> None:
        for sid in [s for s, v in self._sessions.items() if now - v.seen > self._idle]:
            del self._sessions[sid]


class LoginLimiter:
    """Temporary lockout of an address after max_attempts failed logins."""

    def __init__(self, max_attempts: int, lockout: float = LOCKOUT_S) -> None:
        self._max = max_attempts
        self._lockout = lockout
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def locked_for(self, address: str) -> int:
        """Seconds left before this address may try again (0: it may)."""
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._failures.get(address, []) if now - t < self._lockout]
            self._failures[address] = recent
            if len(recent) < self._max:
                return 0
            return max(1, int(self._lockout - (now - recent[-self._max])))

    def failed(self, address: str) -> None:
        with self._lock:
            self._failures.setdefault(address, []).append(time.monotonic())

    def succeeded(self, address: str) -> None:
        with self._lock:
            self._failures.pop(address, None)
