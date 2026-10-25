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


def test_people_on_a_console_are_counted(
    config: Config, conn: LibvirtConnection, frontend_dir: Path
) -> None:
    client = make_client(config, conn, frontend_dir, echo_opener)
    url = "ws://127.0.0.1/api/vms/u1/console"
    told: list[object] = []
    client.app.state.events.broadcast = told.append  # type: ignore[attr-defined]
    with client.websocket_connect(url, subprotocols=PROTOCOLS) as first:
        first.send_bytes(b"a")
        first.receive_bytes()
        with client.websocket_connect(url, subprotocols=PROTOCOLS) as second:
            second.send_bytes(b"b")
            second.receive_bytes()
            assert client.app.state.viewers == {"u1": 2}  # type: ignore[attr-defined]
    assert client.app.state.viewers == {}  # type: ignore[attr-defined]
    counts = [m["count"] for m in told if isinstance(m, dict)]
    assert counts[:2] == [1, 2]
    assert counts[-1] == 0


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
    from kvmstudio.auth.token import token_in_subprotocols as has

    assert has([f"binary, kvmstudio.{TOKEN}"], TOKEN)
    assert has(["binary", f"kvmstudio.{TOKEN}"], TOKEN)
    assert not has(["binary, kvmstudio.nope"], TOKEN)


SPICE_VM = (
    "<domain type='test'><name>spice-vm</name><memory>65536</memory>"
    "<os><type>hvm</type></os><devices>"
    "<graphics type='spice' autoport='yes'><listen type='address'/></graphics>"
    "<channel type='spicevmc'><target type='virtio' name='com.redhat.spice.0'/></channel>"
    "</devices></domain>"
)


def test_vm_without_vnc_is_explained(
    config: Config, conn: LibvirtConnection, frontend_dir: Path
) -> None:
    from kvmstudio.console.vnc import open_vnc_socket

    client = make_client(config, conn, frontend_dir, open_vnc_socket)
    uuid = conn.run(lambda c: c.lookupByName("test").UUIDString())
    with client.websocket_connect(
        f"ws://127.0.0.1/api/vms/{uuid}/console", subprotocols=PROTOCOLS
    ) as ws:
        message = ws.receive()
        assert message["code"] == 4409
        assert message["reason"] == "console.no_vnc"


def test_display_info_and_adding_vnc(
    config: Config, conn: LibvirtConnection, frontend_dir: Path
) -> None:
    client = make_client(config, conn, frontend_dir, echo_opener)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    dom = conn.run(lambda c: c.defineXML(SPICE_VM))
    try:
        uuid = dom.UUIDString()
        info = client.get(f"/api/vms/{uuid}/display", headers=auth).json()
        assert info == {
            "live": [],
            "config": ["spice"],
            "clipboard": False,
            "clipboard_config": False,
            "clipboard_isolated": False,
            "active": False,
        }
        result = client.post(f"/api/vms/{uuid}/display/vnc", headers=auth).json()
        assert result == {"restart_required": False}
        info = client.get(f"/api/vms/{uuid}/display", headers=auth).json()
        # SPICE stays; its agent channel gives way to QEMU's vdagent.
        assert info["config"] == ["spice", "vnc"]
        assert info["clipboard_config"] is True
        xml = dom.XMLDesc(0)
        assert "spicevmc" not in xml
        assert xml.count("com.redhat.spice.0") == 1
        # Adding twice changes nothing.
        client.post(f"/api/vms/{uuid}/display/vnc", headers=auth)
        assert client.get(f"/api/vms/{uuid}/display", headers=auth).json()["config"] == [
            "spice",
            "vnc",
        ]
    finally:
        dom.undefine()


def test_enable_clipboard_on_a_spice_only_vm(
    config: Config, conn: LibvirtConnection, frontend_dir: Path
) -> None:
    client = make_client(config, conn, frontend_dir, echo_opener)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    dom = conn.run(lambda c: c.defineXML(SPICE_VM))
    try:
        uuid = dom.UUIDString()
        result = client.post(f"/api/vms/{uuid}/display/clipboard", headers=auth).json()
        assert result == {"restart_required": False}
        info = client.get(f"/api/vms/{uuid}/display", headers=auth).json()
        # One action: the agent channel and the display the console uses.
        assert info["config"] == ["spice", "vnc"]
        assert info["clipboard_config"] is True
        assert "spicevmc" not in dom.XMLDesc(0)
    finally:
        dom.undefine()


def test_enable_clipboard_on_a_vm_that_has_vnc(
    config: Config, conn: LibvirtConnection, frontend_dir: Path
) -> None:
    client = make_client(config, conn, frontend_dir, echo_opener)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    xml = SPICE_VM.replace("spice-vm", "spice-vnc-vm").replace(
        "</devices>", "<graphics type='vnc'><listen type='none'/></graphics></devices>"
    )
    dom = conn.run(lambda c: c.defineXML(xml))
    try:
        uuid = dom.UUIDString()
        assert client.get(f"/api/vms/{uuid}/display", headers=auth).json()["clipboard"] is False
        result = client.post(f"/api/vms/{uuid}/display/clipboard", headers=auth).json()
        assert result == {"restart_required": False}
        info = client.get(f"/api/vms/{uuid}/display", headers=auth).json()
        assert info["clipboard"] is True
        assert info["config"] == ["spice", "vnc"]
    finally:
        dom.undefine()
