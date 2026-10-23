"""End to end: browser-side WebSocket -> KVM Studio -> libvirt -> QEMU VNC.

A transient, diskless domain is started in qemu:///session (nothing persists),
then two console clients exchange UTF-8 text through the QEMU clipboard.
KVMSTUDIO_QEMU_TESTS=1 pytest tests/backend/test_qemu_console.py
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import libvirt
import pytest
from lxml import etree
from websockets.sync.client import ClientConnection, connect

from kvmstudio.app import create_app
from kvmstudio.config import Config, LibvirtSettings
from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.shell.server import BackgroundServer, bind_loopback
from kvmstudio.xml.devices import vdagent_channel, vnc_graphics

from .rfb_client import ACTION_CAPS, ACTION_NOTIFY, ACTION_PROVIDE, ACTION_REQUEST, RfbClient
from .test_qemu_clipboard import SAMPLE

pytestmark = pytest.mark.skipif(
    os.environ.get("KVMSTUDIO_QEMU_TESTS") != "1",
    reason="set KVMSTUDIO_QEMU_TESTS=1 (needs libvirt session and QEMU)",
)

SESSION_URI = "qemu:///session"


def domain_xml(name: str) -> str:
    domain = etree.Element("domain", type="kvm" if os.access("/dev/kvm", os.W_OK) else "qemu")
    etree.SubElement(domain, "name").text = name
    etree.SubElement(domain, "uuid").text = str(uuid.uuid4())
    etree.SubElement(domain, "memory", unit="MiB").text = "128"
    os_el = etree.SubElement(domain, "os")
    etree.SubElement(os_el, "type", machine="q35").text = "hvm"
    devices = etree.SubElement(domain, "devices")
    devices.append(vnc_graphics())
    devices.append(vdagent_channel())
    return etree.tostring(domain).decode()


@pytest.fixture
def running_domain() -> Iterator[str]:
    conn = libvirt.open(SESSION_URI)
    dom = conn.createXML(domain_xml(f"kvmstudio-test-{uuid.uuid4().hex[:8]}"))
    try:
        yield dom.UUIDString()
    finally:
        dom.destroy()
        conn.close()


class WsTransport:
    """Byte-stream view of a WebSocket, so RfbClient can run over it."""

    def __init__(self, ws: ClientConnection) -> None:
        self.ws = ws
        self.buffer = b""

    def settimeout(self, _t: float) -> None:
        pass

    def recv(self, n: int) -> bytes:
        if not self.buffer:
            message = self.ws.recv(timeout=5)
            self.buffer = message if isinstance(message, bytes) else message.encode()
        chunk, self.buffer = self.buffer[:n], self.buffer[n:]
        return chunk

    def sendall(self, data: bytes) -> None:
        self.ws.send(data)

    def close(self) -> None:
        self.ws.close()


def open_console(port: int, token: str, dom_uuid: str) -> RfbClient:
    ws = connect(  # closed through RfbClient.close()
        f"ws://127.0.0.1:{port}/api/vms/{dom_uuid}/console",
        subprotocols=["binary", f"kvmstudio.{token}"],  # type: ignore[list-item]
    )
    client = RfbClient(WsTransport(ws))  # type: ignore[arg-type]
    flags, _ = client.read_clipboard_message()
    assert flags & ACTION_CAPS
    assert flags & ACTION_NOTIFY
    client.send_caps()
    return client


def test_utf8_clipboard_through_the_console_proxy(running_domain: str) -> None:
    config = Config(libvirt=LibvirtSettings(uri=SESSION_URI))
    conn = LibvirtConnection(SESSION_URI)
    server = BackgroundServer(create_app(config, conn, "tok", mode="web"), bind_loopback(0))
    server.start()
    try:
        sender = open_console(server.port, "tok", running_domain)
        receiver = open_console(server.port, "tok", running_domain)

        sender.notify_text()
        flags, _ = receiver.read_clipboard_message()
        assert flags & ACTION_NOTIFY
        receiver.request_text()
        flags, _ = sender.read_clipboard_message()
        assert flags & ACTION_REQUEST
        sender.provide_text(SAMPLE)
        flags, payload = receiver.read_clipboard_message()
        assert flags & ACTION_PROVIDE
        assert RfbClient.decode_text(payload) == SAMPLE

        sender.close()
        receiver.close()
    finally:
        server.stop()
        conn.close()
