"""Bounds on what one client may make the backend hold, and WebSocket origins.

Request bodies: a small cap for anyone not signed in (the login form), a
larger one for the owner and guests (a network import, notes, an XML
definition). Both the announced Content-Length and what really arrives are
counted, before anything is parsed. WebSockets: a cap per guest session, or
per address without one.
"""

from __future__ import annotations

from collections import Counter

from starlette.requests import HTTPConnection
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .auth.guest import COOKIE

PUBLIC_BODY = 64 * 1024
SIGNED_IN_BODY = 8 * 1024 * 1024
SOCKETS_PER_SESSION = 32


def _signed_in(scope: Scope) -> bool:
    from .auth.roles import bearer_ok, role_of

    conn = HTTPConnection(scope)
    try:
        return role_of(conn, token_ok=bearer_ok(conn)) is not None
    except (AttributeError, KeyError):
        return False  # an app without our context (never in practice)


class BodyLimit:
    def __init__(
        self, app: ASGIApp, public: int = PUBLIC_BODY, signed_in: int = SIGNED_IN_BODY
    ) -> None:
        self.app = app
        self.public = public
        self.signed_in = signed_in

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.signed_in if _signed_in(scope) else self.public
        announced = HTTPConnection(scope).headers.get("content-length")
        if announced is not None:
            if not announced.isdigit():
                await PlainTextResponse("Bad Content-Length", 400)(scope, receive, send)
                return
            if int(announced) > limit:
                await _too_large(scope, receive, send)
                return
        received = 0
        started = False
        refused = False

        async def counted() -> Message:
            nonlocal received, refused
            if refused:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # Answer now and tell the app the client left: it stops
                    # reading, and whatever it answers is dropped.
                    refused = True
                    if not started:
                        await _too_large(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def watched(message: Message) -> None:
            nonlocal started
            if refused:
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, counted, watched)


async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
    response = PlainTextResponse("Request too large", status_code=413)
    await response(scope, receive, send)


class SocketLimit:
    """At most SOCKETS_PER_SESSION WebSockets at once per guest session or address."""

    def __init__(self, app: ASGIApp, limit: int = SOCKETS_PER_SESSION) -> None:
        self.app = app
        self.limit = limit
        self.open: Counter[str] = Counter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "websocket":
            await self.app(scope, receive, send)
            return
        conn = HTTPConnection(scope)
        sid = conn.cookies.get(COOKIE)
        key = f"session:{sid}" if sid else f"address:{conn.client.host if conn.client else ''}"
        if self.open[key] >= self.limit:
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 1008})
            return
        self.open[key] += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.open[key] -= 1
            if self.open[key] <= 0:
                del self.open[key]


def expected_origins(scope: Scope) -> set[str]:
    """Origins of our own pages for this connection: the address it came to."""
    conn = HTTPConnection(scope)
    host = conn.headers.get("host", "")
    secure = scope.get("scheme") in ("https", "wss")
    origins = {f"{'https' if secure else 'http'}://{host}"}
    if not secure:
        port = (scope.get("server") or ("", 0))[1]
        origins |= {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    return origins


class SocketOrigin:
    """Refuses a WebSocket opened by a page of another origin.

    The guest cookie is SameSite=Strict, but a page on another port of the
    same address is the same site: its origin tells it apart. Clients that
    send no Origin (not a browser) are let through to the usual checks.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            origin = HTTPConnection(scope).headers.get("origin")
            if origin is not None and origin not in expected_origins(scope):
                await receive()  # websocket.connect
                await send({"type": "websocket.close", "code": 1008})
                return
        await self.app(scope, receive, send)
