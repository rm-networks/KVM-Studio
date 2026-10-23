from __future__ import annotations

import socket
import threading
from pathlib import Path

import libvirt
import pytest
from fastapi.testclient import TestClient
from lxml import etree
from starlette.websockets import WebSocketDisconnect

from kvmstudio.app import create_app
from kvmstudio.config import Config
from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.xml.devices import vdagent_channel, vnc_graphics

from .conftest import TOKEN

PROTOCOLS = ["binary", f"kvmstudio.{TOKEN}"]


def echo_opener(_conn: LibvirtConnection, _uuid: str) -> socket.socket:
    """Stand-in for libvirt: the 'VM' echoes back what it receives, uppercased."""
    ours, theirs = socket.socketpair()

    def serve() -> None:
        with theirs:
            while data := theirs.recv(4096):
                theirs.sendall(data.upper())

    threading.Thread(target=serve, daemon=True).start()
    return ours


def failing_opener(_conn: LibvirtConnection, _uuid: str) -> socket.socket:
    class NotRunning(libvirt.libvirtError):
        def __init__(self) -> None:
            Exception.__init__(self, "domain is not running")

        def get_error_code(self) -> int:
            return libvirt.VIR_ERR_OPERATION_INVALID

        def get_error_message(self) -> str:
            return "domain is not running"

    raise NotRunning()


def make_client(config: Config, conn: LibvirtConnection, frontend_dir: Path, opener) -> TestClient:  # type: ignore[no-untyped-def]
    app = create_app(
        config, conn, TOKEN, mode="web", frontend_dir=frontend_dir, open_console=opener
    )
    return TestClient(app, base_url="http://127.0.0.1")


def test_console_relays_bytes_both_ways(
    config: Config, conn: LibvirtConnection, frontend_dir: Path
) -> None:
    client = make_client(config, conn, frontend_dir, echo_opener)
    with client.websocket_connect(
        "ws://127.0.0.1/api/vms/some-uuid/console", subprotocols=PROTOCOLS
    ) as ws:
        assert ws.accepted_subprotocol == "binary"
        ws.send_bytes(b"rfb hello")
        assert ws.receive_bytes() == b"RFB HELLO"


@pytest.mark.parametrize("protocols", [["binary"], ["binary", "kvmstudio.wrong"], []])
def test_console_requires_the_token(
    config: Config, conn: LibvirtConnection, frontend_dir: Path, protocols: list[str]
) -> None:
    client = make_client(config, conn, frontend_dir, echo_opener)
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("ws://127.0.0.1/api/vms/x/console", subprotocols=protocols),
    ):
        pass
    assert exc.value.code == 4401


def test_console_reports_libvirt_errors(
    config: Config, conn: LibvirtConnection, frontend_dir: Path
) -> None:
    client = make_client(config, conn, frontend_dir, failing_opener)
    with client.websocket_connect("ws://127.0.0.1/api/vms/x/console", subprotocols=PROTOCOLS) as ws:
        message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4409
        assert message["reason"] == "libvirt.invalid_state"


def test_console_rejects_foreign_hosts(
    config: Config, conn: LibvirtConnection, frontend_dir: Path
) -> None:
    client = make_client(config, conn, frontend_dir, echo_opener)
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            "ws://127.0.0.1/api/vms/x/console",
            subprotocols=PROTOCOLS,
            headers={"Host": "evil.example"},
        ),
    ):
        pass


def test_device_xml() -> None:
    graphics = etree.tostring(vnc_graphics()).decode()
    assert graphics == (
        '<graphics type="vnc" sharePolicy="allow-exclusive"><listen type="none"/></graphics>'
    )
    channel = vdagent_channel()
    assert channel.get("type") == "qemu-vdagent"
    assert channel.find("source/clipboard").get("copypaste") == "yes"  # type: ignore[union-attr]
    assert channel.find("target").get("name") == "com.redhat.spice.0"  # type: ignore[union-attr]
    isolated = vdagent_channel(clipboard=False)
    assert isolated.find("source/clipboard").get("copypaste") == "no"  # type: ignore[union-attr]


def test_token_is_found_in_an_unsplit_header() -> None:
    from kvmstudio.console.vnc import _has_token

    assert _has_token([f"binary, kvmstudio.{TOKEN}"], TOKEN)
    assert _has_token(["binary", f"kvmstudio.{TOKEN}"], TOKEN)
    assert not _has_token(["binary, kvmstudio.nope"], TOKEN)
