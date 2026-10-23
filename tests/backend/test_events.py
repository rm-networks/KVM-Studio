from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import libvirt
import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from kvmstudio.app import create_app
from kvmstudio.config import Config
from kvmstudio.libvirt_conn import LibvirtConnection

from .conftest import TOKEN

PROTOCOLS = ["kvmstudio.events", f"kvmstudio.{TOKEN}"]
TRANSIENT_XML = (
    "<domain type='test'><name>{name}</name><memory>65536</memory>"
    "<os><type>hvm</type></os></domain>"
)


@pytest.fixture
def client(config: Config, conn: LibvirtConnection, frontend_dir: Path) -> Iterator[TestClient]:
    app = create_app(config, conn, TOKEN, mode="web", frontend_dir=frontend_dir)
    with TestClient(app, base_url="http://127.0.0.1") as c:  # runs the lifespan
        yield c


def next_event(ws: WebSocketTestSession, kind: str) -> dict[str, Any]:
    for _ in range(10):
        message: dict[str, Any] = json.loads(ws.receive_text())
        if message["type"] == kind:
            return message
    raise AssertionError(f"no {kind} event")


def test_state_changes_are_pushed(client: TestClient, conn: LibvirtConnection) -> None:
    with client.websocket_connect("ws://127.0.0.1/ws/events", subprotocols=PROTOCOLS) as ws:
        assert ws.accepted_subprotocol == "kvmstudio.events"
        dom = conn.run(lambda c: c.lookupByName("test"))
        dom.suspend()
        try:
            event = next_event(ws, "vm.changed")
            assert event["vm"]["name"] == "test"
            assert event["vm"]["state"] == "paused"
        finally:
            dom.resume()
        assert next_event(ws, "vm.changed")["vm"]["state"] == "running"


def test_transient_domains_appear_and_disappear(
    client: TestClient, conn: LibvirtConnection
) -> None:
    with client.websocket_connect("ws://127.0.0.1/ws/events", subprotocols=PROTOCOLS) as ws:
        dom = conn.run(lambda c: c.createXML(TRANSIENT_XML.format(name="ephemeral")))
        started = next_event(ws, "vm.changed")
        assert started["vm"]["name"] == "ephemeral"
        assert started["vm"]["state"] == "running"
        uuid = dom.UUIDString()
        dom.destroy()
        assert next_event(ws, "vm.removed")["uuid"] == uuid


@pytest.mark.parametrize(
    "protocols", [["kvmstudio.events"], [f"kvmstudio.{TOKEN}"], ["kvmstudio.events", "x"]]
)
def test_events_require_token_and_protocol(client: TestClient, protocols: list[str]) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("ws://127.0.0.1/ws/events", subprotocols=protocols),
    ):
        pass
    assert exc.value.code == 4401


def test_hub_hook_runs_on_an_already_open_connection(conn: LibvirtConnection) -> None:
    conn.list_domains()
    seen: list[libvirt.virConnect] = []
    conn.add_connect_hook(seen.append)
    assert len(seen) == 1
