"""Per-process session token, required on every API call.

The token reaches the frontend in the URL fragment (never sent to the server),
is kept in sessionStorage and comes back in the Authorization header. No cookie
is involved, so other sites cannot make the browser call the API on our behalf.
"""

from __future__ import annotations

import secrets

from fastapi import Request

from ..context import get_context
from ..errors import ApiException

# The browser cannot set headers on a WebSocket, so the token travels as an
# extra subprotocol ("kvmstudio.<token>") next to the one the endpoint accepts.
TOKEN_PROTOCOL_PREFIX = "kvmstudio."  # noqa: S105 (a prefix, not a secret)


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
