"""Uvicorn server running in a background thread: loopback, plus HTTPS for LAN sharing."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import uvicorn
import uvicorn.config
from fastapi import FastAPI

# Uvicorn 0.35 and later: the sans-I/O websockets implementation, the one that
# does not warn with websockets 14. Debian 13 ships uvicorn 0.32, which lacks it.
WS_PROTOCOL = (
    "websockets-sansio" if "websockets-sansio" in uvicorn.config.WS_PROTOCOLS else "websockets"
)


class PortInUseError(Exception):
    pass


def bind_loopback(port: int) -> socket.socket:
    """Bind 127.0.0.1:port (0 = pick a free port) before uvicorn starts."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError as exc:
        sock.close()
        raise PortInUseError(f"127.0.0.1:{port} is already in use") from exc
    return sock


def bind_lan(port: int) -> socket.socket:
    """Bind every IPv4 address on port: the HTTPS listener of LAN sharing."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", port))  # noqa: S104 (LAN sharing, guests log in over HTTPS)
    except OSError as exc:
        sock.close()
        raise PortInUseError(f"port {port} is already in use") from exc
    return sock


@dataclass(frozen=True, slots=True)
class LanListener:
    sock: socket.socket
    cert: Path
    key: Path


class BackgroundServer:
    """Uvicorn in a thread: the loopback listener, and the HTTPS one of LAN
    sharing when given. Both run on one asyncio loop, which the live events
    and the console proxy rely on."""

    def __init__(self, app: FastAPI, sock: socket.socket, lan: LanListener | None = None) -> None:
        self.port: int = sock.getsockname()[1]
        self._socks = [sock]
        self._servers = [uvicorn.Server(uvicorn.Config(app, log_level="warning", ws=WS_PROTOCOL))]
        if lan is not None:
            self._socks.append(lan.sock)
            self._servers.append(
                uvicorn.Server(
                    uvicorn.Config(
                        app,
                        log_level="warning",
                        ws=WS_PROTOCOL,
                        # The app starts and stops once, with the first listener.
                        lifespan="off",
                        ssl_certfile=str(lan.cert),
                        ssl_keyfile=str(lan.key),
                    )
                )
            )
        self._thread = threading.Thread(target=lambda: asyncio.run(self._serve()), daemon=True)

    async def _serve(self) -> None:
        await asyncio.gather(
            *(
                server.serve(sockets=[sock])
                for server, sock in zip(self._servers, self._socks, strict=True)
            )
        )

    def start(self, timeout: float = 10.0) -> None:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not all(server.started for server in self._servers):
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("the internal web server did not start")
            time.sleep(0.05)

    def wait(self) -> None:
        self._thread.join()

    def stop(self) -> None:
        for server in self._servers:
            server.should_exit = True
        self._thread.join(timeout=5)
        for sock in self._socks:
            sock.close()
