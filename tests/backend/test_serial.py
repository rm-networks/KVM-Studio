from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from kvmstudio.app import create_app
from kvmstudio.config import Config
from kvmstudio.console.serial import SerialChannel, has_serial
from kvmstudio.errors import ApiException
from kvmstudio.libvirt_conn import LibvirtConnection

from .conftest import TOKEN

PROTOCOLS = ["binary", f"kvmstudio.{TOKEN}"]
URL = "ws://127.0.0.1/api/vms/u1/serial"


class EchoSerial:
    """Stand-in for the libvirt stream: answers what it gets, uppercased."""

    def __init__(self) -> None:
        self.closed = False
        self._data: Callable[[bytes], None] | None = None

    def start(self, on_data: Callable[[bytes], None], on_end: Callable[[], None]) -> None:
        self._data = on_data
        on_data(b"login: ")

    def send(self, data: bytes) -> None:
        assert self._data is not None
        self._data(data.upper())

    def close(self) -> None:
        self.closed = True


def client(config: Config, conn: LibvirtConnection, frontend_dir: Path, opener) -> TestClient:  # type: ignore[no-untyped-def]
    app = create_app(config, conn, TOKEN, mode="web", frontend_dir=frontend_dir, open_serial=opener)
    return TestClient(app, base_url="http://127.0.0.1")


def test_serial_relays_both_ways(
    config: Config, conn: LibvirtConnection, frontend_dir: Path
) -> None:
    serial = EchoSerial()

    def opener(_c: LibvirtConnection, _u: str) -> SerialChannel:
        return serial

    with client(config, conn, frontend_dir, opener).websocket_connect(
        URL, subprotocols=PROTOCOLS
    ) as ws:
        assert ws.receive_bytes() == b"login: "
        ws.send_bytes(b"root\r")
        assert ws.receive_bytes() == b"ROOT\r"
    assert serial.closed


def test_serial_requires_the_token(
    config: Config, conn: LibvirtConnection, frontend_dir: Path
) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client(config, conn, frontend_dir, lambda c, u: EchoSerial()).websocket_connect(
            URL, subprotocols=["binary"]
        ),
    ):
        pass
    assert exc.value.code == 4401


def test_vm_without_serial_is_explained(
    config: Config, conn: LibvirtConnection, frontend_dir: Path
) -> None:
    def opener(_c: LibvirtConnection, _u: str) -> SerialChannel:
        raise ApiException(409, "serial.none", "no serial console")

    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client(config, conn, frontend_dir, opener).websocket_connect(
            URL, subprotocols=PROTOCOLS
        ) as ws,
    ):
        ws.receive_bytes()
    assert (exc.value.code, exc.value.reason) == (4409, "serial.none")


def test_has_serial() -> None:
    assert has_serial("<domain><devices><console type='pty'/></devices></domain>")
    assert not has_serial("<domain><devices><graphics type='vnc'/></devices></domain>")
