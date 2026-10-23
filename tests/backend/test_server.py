from __future__ import annotations

import http.client
import json

import pytest

from kvmstudio.app import create_app
from kvmstudio.config import Config
from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.shell.server import BackgroundServer, PortInUseError, bind_loopback


def test_background_server_serves_on_loopback(config: Config, conn: LibvirtConnection) -> None:
    app = create_app(config, conn, "tok", mode="desktop")
    server = BackgroundServer(app, bind_loopback(0))
    server.start()
    try:
        client = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
        client.request("GET", "/api/vms", headers={"Authorization": "Bearer tok"})
        response = client.getresponse()
        assert response.status == 200
        assert json.loads(response.read())[0]["name"] == "test"
    finally:
        server.stop()


def test_port_in_use_is_detected() -> None:
    sock = bind_loopback(0)
    sock.listen()
    try:
        with pytest.raises(PortInUseError):
            bind_loopback(sock.getsockname()[1])
    finally:
        sock.close()
