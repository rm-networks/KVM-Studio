"""Who calls: the owner (session token, from this computer) or a guest (LAN sharing).

The owner holds the token printed or handed to the window, and only from a
loopback address. A guest holds a session cookie opened by the guest password,
only on the HTTPS listener of LAN sharing. The guest manages VMs but not the
host: the routes below answer 403 to a guest, whatever the interface shows
(F-102, docs/ARCHITECTURE.md).
"""

from __future__ import annotations

import contextlib
import ipaddress
import re
import secrets
from dataclasses import dataclass
from typing import Literal

import libvirt
from fastapi import Request
from starlette.requests import HTTPConnection
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ..context import get_context
from ..errors import ApiException
from .guest import COOKIE, GuestSessions, LoginLimiter

Role = Literal["owner", "guest"]

# (methods, path) a guest never reaches. None: every method.
GUEST_FORBIDDEN: list[tuple[frozenset[str] | None, re.Pattern[str]]] = [
    # Preferences, ISO libraries included, and LAN sharing.
    (None, re.compile(r"^/api/preferences(/.*)?$")),
    (None, re.compile(r"^/api/sharing(/.*)?$")),
    # The network editor: only the list stays, to pick a network for a card.
    (None, re.compile(r"^/api/networks/.+$")),
    (frozenset({"POST", "PUT", "PATCH", "DELETE"}), re.compile(r"^/api/networks$")),
    # Access rights on the ISO libraries go through the root helper.
    (None, re.compile(r"^/api/isos/access/fix$")),
    # The host itself: first run, uninstall, restart, closing actions.
    (None, re.compile(r"^/api/setup(/.*)?$")),
    (None, re.compile(r"^/api/uninstall(/.*)?$")),
    (None, re.compile(r"^/api/restart$")),
    (None, re.compile(r"^/api/session(/.*)?$")),
    # Importing copies disks from outside the KVM-Studio root (F-103), and so
    # does a folder scan, which also reads folders anywhere.
    (None, re.compile(r"^/api/vms/[^/]+/import$")),
    (None, re.compile(r"^/api/scan(/.*)?$")),
]


def guest_forbidden(method: str, path: str) -> bool:
    return any(
        (methods is None or method.upper() in methods) and pattern.match(path)
        for methods, pattern in GUEST_FORBIDDEN
    )


@dataclass(slots=True)
class Sharing:
    """LAN sharing state of a running backend."""

    https_port: int
    sessions: GuestSessions
    limiter: LoginLimiter
    fingerprint: str = ""
    firewall: str | None = None


def _loopback(conn: HTTPConnection) -> bool:
    host = conn.client.host if conn.client else ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "testclient"  # Starlette's test client


def on_lan_listener(conn: HTTPConnection) -> bool:
    sharing = get_context(conn).sharing
    server = conn.scope.get("server") or ("", 0)
    return sharing is not None and server[1] == sharing.https_port


def bearer_ok(conn: HTTPConnection) -> bool:
    expected = get_context(conn).token
    scheme, _, given = conn.headers.get("authorization", "").partition(" ")
    return scheme.lower() == "bearer" and secrets.compare_digest(given.encode(), expected.encode())


def guest_ok(conn: HTTPConnection) -> bool:
    sharing = get_context(conn).sharing
    return (
        sharing is not None
        and on_lan_listener(conn)
        and sharing.sessions.touch(conn.cookies.get(COOKIE))
    )


def role_of(conn: HTTPConnection, *, token_ok: bool) -> Role | None:
    # The owner's token is only good from this computer.
    if token_ok and _loopback(conn):
        return "owner"
    if guest_ok(conn):
        return "guest"
    return None


def require_access(request: Request) -> None:
    role = role_of(request, token_ok=bearer_ok(request))
    if role is None:
        raise ApiException(401, "auth.invalid_token", "Missing or invalid session token")
    if role == "guest" and guest_forbidden(request.method, request.url.path):
        raise ApiException(403, "auth.guest_forbidden", "Not allowed with the guest account")
    request.state.role = role


def socket_role(websocket: HTTPConnection) -> Role | None:
    """WebSockets carry the owner's token as a subprotocol; guests their cookie."""
    from .token import token_in_subprotocols

    ctx = get_context(websocket)
    token_ok = token_in_subprotocols(websocket.scope.get("subprotocols", []), ctx.token)
    return role_of(websocket, token_ok=token_ok)


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})


class HostCheck:
    """The loopback listener only answers to loopback names (DNS rebinding);
    the LAN listener answers whatever name or address the guests use."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            conn = HTTPConnection(scope)
            host = conn.headers.get("host", "").rsplit(":", 1)[0].strip("[]")
            if host not in LOOPBACK_HOSTS and not on_lan_listener(conn):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 4400})
                    return
                response = PlainTextResponse("Invalid host header", status_code=400)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def check_guest_networks(request: Request, names: list[str | None]) -> None:
    """A guest plugs VM cards into KVM Studio's own kvmnet networks only."""
    if getattr(request.state, "role", None) != "guest":
        return
    conn = get_context(request).conn

    def bridges(c: libvirt.virConnect) -> dict[str, str]:
        found = {}
        for net in c.listAllNetworks():
            with contextlib.suppress(libvirt.libvirtError):
                found[net.name()] = net.bridgeName()
        return found

    known = conn.run(bridges)
    for name in names:
        if name is not None and not known.get(name, "").startswith("kvmnet"):
            raise ApiException(
                403, "auth.guest_network", f"The guest account only uses kvmnet networks: {name}"
            )
