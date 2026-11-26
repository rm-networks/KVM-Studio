"""Which local account a loopback TCP client runs as.

The owner's token is only accepted from this computer, but other accounts of
the same computer reach 127.0.0.1 too. The kernel lists every TCP socket of
the network namespace with its owner in /proc/net/tcp and /proc/net/tcp6:
the client's end is the line whose local address is the client's and whose
remote address is ours. When no such line is found (another namespace, a
kernel without /proc), the caller falls back on the token alone.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import sys
import time
from pathlib import Path

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger(__name__)

PROC_TABLES = (Path("/proc/net/tcp"), Path("/proc/net/tcp6"))
_WARN_EVERY_S = 300.0


def _hex_address(host: str, port: int) -> set[str] | None:
    """The forms the kernel prints for host:port, in tcp and in tcp6."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    # The kernel prints each 32-bit word in host byte order.
    step = -1 if sys.byteorder == "little" else 1
    if ip.version == 4:
        v4 = socket.inet_aton(str(ip))[::step].hex().upper()
        mapped = ipaddress.IPv6Address(f"::ffff:{ip}").packed
    else:
        v4 = ""
        mapped = ip.packed
    v6 = "".join(mapped[i : i + 4][::step].hex().upper() for i in range(0, 16, 4))
    suffix = f":{port:04X}"
    return {v4 + suffix, v6 + suffix} if v4 else {v6 + suffix}


def peer_uid(
    client: tuple[str, int], server: tuple[str, int], tables: tuple[Path, ...] = PROC_TABLES
) -> int | None:
    """uid owning the client end of the TCP connection client -> server, if listed."""
    mine = _hex_address(*client)
    ours = _hex_address(*server)
    if mine is None or ours is None:
        return None
    for table in tables:
        try:
            lines = table.read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 8:
                continue
            local, remote, uid = fields[1], fields[2], fields[7]
            if local in mine and remote in ours:
                try:
                    return int(uid)
                except ValueError:
                    return None
    return None


def _loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class LocalUserCheck:
    """Refuses loopback clients run by another account than the backend's (403)."""

    def __init__(self, app: ASGIApp, uid: int | None = None) -> None:
        self.app = app
        self.uid = os.getuid() if uid is None else uid
        self._warned = 0.0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            client, server = scope.get("client"), scope.get("server")
            if client and server and _loopback(client[0]):
                uid = peer_uid((client[0], client[1]), (server[0], server[1]))
                if uid is None:
                    self._warn()
                elif uid != self.uid:
                    log.warning("refused a local connection of uid %d", uid)
                    await _refuse(scope, receive, send)
                    return
        await self.app(scope, receive, send)

    def _warn(self) -> None:
        now = time.monotonic()
        if now - self._warned > _WARN_EVERY_S:
            self._warned = now
            log.warning("the account of a local client is unknown: the token alone is checked")


async def _refuse(scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] == "websocket":
        await receive()  # websocket.connect
        await send({"type": "websocket.close", "code": 1008})
        return
    response = PlainTextResponse("Another account of this computer", status_code=403)
    await response(scope, receive, send)
