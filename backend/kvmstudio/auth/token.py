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


def new_token() -> str:
    return secrets.token_urlsafe(32)


def require_token(request: Request) -> None:
    expected = get_context(request).token
    scheme, _, given = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(given.encode(), expected.encode()):
        raise ApiException(401, "auth.invalid_token", "Missing or invalid session token")
