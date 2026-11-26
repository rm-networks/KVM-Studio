"""Per-process session token, required on every API call.

The token reaches the window in the URL fragment (never sent to the server);
a browser gets a single-use code there instead, traded for the token at once.
It is kept in sessionStorage and comes back in the Authorization header. No cookie
is involved, so other sites cannot make the browser call the API on our behalf.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable

from fastapi import Request

from ..context import get_context
from ..errors import ApiException

# The browser cannot set headers on a WebSocket, so the token travels as an
# extra subprotocol ("kvmstudio.<token>") next to the one the endpoint accepts.
TOKEN_PROTOCOL_PREFIX = "kvmstudio."  # noqa: S105 (a prefix, not a secret)
# A link opened at once, and one copied to be pasted.
LINK_OPEN_S = 30.0
LINK_COPY_S = 120.0
MAX_LINK_CODES = 32


def new_token() -> str:
    return secrets.token_urlsafe(32)


def require_token(request: Request) -> None:
    expected = get_context(request).token
    scheme, _, given = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(given.encode(), expected.encode()):
        raise ApiException(401, "auth.invalid_token", "Missing or invalid session token")


def offered_subprotocols(raw: list[str]) -> list[str]:
    # Some uvicorn backends pass the header unsplit ("binary, kvmstudio.x").
    return [p.strip() for entry in raw for p in entry.split(",") if p.strip()]


def token_in_subprotocols(raw: list[str], expected: str) -> bool:
    for proto in offered_subprotocols(raw):
        if proto.startswith(TOKEN_PROTOCOL_PREFIX):
            given = proto.removeprefix(TOKEN_PROTOCOL_PREFIX).encode()
            if secrets.compare_digest(given, expected.encode()):
                return True
    return False


class LinkCodes:
    """Single-use codes that stand for the token in a link given to a browser.

    The browser is started with the link on its command line, which every
    local account can read: the link carries a code that the page trades once
    for the token, within a few seconds, instead of the token itself.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._codes: dict[str, float] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def new(self, ttl: float) -> str:
        code = secrets.token_urlsafe(24)
        now = self._clock()
        with self._lock:
            self._codes = {c: t for c, t in self._codes.items() if t > now}
            if len(self._codes) >= MAX_LINK_CODES:
                self._codes.pop(next(iter(self._codes)))
            self._codes[code] = now + ttl
        return code

    def redeem(self, code: str) -> bool:
        with self._lock:
            expires = self._codes.pop(code, None)
        return expires is not None and expires > self._clock()
