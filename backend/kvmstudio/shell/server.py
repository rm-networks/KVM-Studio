"""Uvicorn server running in a background thread, bound to loopback only."""

from __future__ import annotations

import socket
import threading
import time

import uvicorn
from fastapi import FastAPI


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


class BackgroundServer:
    def __init__(self, app: FastAPI, sock: socket.socket) -> None:
        self.port: int = sock.getsockname()[1]
        self._sock = sock
        self._server = uvicorn.Server(
            uvicorn.Config(app, log_level="warning", ws="websockets-sansio")
        )
        self._thread = threading.Thread(
            target=self._server.run, kwargs={"sockets": [sock]}, daemon=True
        )

    def start(self, timeout: float = 10.0) -> None:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("the internal web server did not start")
            time.sleep(0.05)

    def wait(self) -> None:
        self._thread.join()

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)
        self._sock.close()
