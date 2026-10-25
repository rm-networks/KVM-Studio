from __future__ import annotations

from typing import Any

import libvirt
from fastapi.testclient import TestClient

from .helpers import AUTH


def test_running_vms_and_close_actions(client: TestClient, conn: Any) -> None:
    # test:///default starts with one running domain, "test".
    names = [v["name"] for v in client.get("/api/session/running", headers=AUTH).json()]
    assert names == ["test"]

    r = client.post("/api/session/running/suspend", headers=AUTH).json()
    assert r == {"done": ["test"], "failed": []}
    dom = conn.run(lambda c: c.lookupByName("test"))
    assert not dom.isActive()
    assert dom.hasManagedSaveImage(0)
    assert client.get("/api/session/running", headers=AUTH).json() == []
    dom.create()

    assert client.post("/api/session/running/poweroff", headers=AUTH).json()["done"] == ["test"]
    assert not dom.isActive()
    dom.create()


def test_unknown_close_action(client: TestClient) -> None:
    assert client.post("/api/session/running/delete", headers=AUTH).status_code == 422


def test_failures_are_reported(client: TestClient, conn: Any, monkeypatch: Any) -> None:
    def refuse(self: libvirt.virDomain, flags: int = 0) -> int:
        raise libvirt.libvirtError("shutdown refused")

    monkeypatch.setattr(libvirt.virDomain, "shutdownFlags", refuse)
    r = client.post("/api/session/running/shutdown", headers=AUTH).json()
    assert r["done"] == []
    assert r["failed"][0]["name"] == "test"
    assert "refused" in r["failed"][0]["detail"]


def test_session_client_for_the_tray(monkeypatch: Any) -> None:
    from kvmstudio.shell.session_client import SessionClient

    client = SessionClient("http://127.0.0.1:60080/#token=abc")
    assert client._base == "http://127.0.0.1:60080/api"
    assert client._token == "abc"
    calls: list[tuple[str, str, Any]] = []
    config = {"workspace": {"on_close": "keep", "close_reminder": True}}

    def fake(method: str, path: str, body: Any = None) -> Any:
        calls.append((method, path, body))
        if path == "/preferences" and method == "GET":
            return {"config": config}
        if path == "/session/running":
            return [{"uuid": "u", "name": "fw"}]
        return {"done": [], "failed": [{"name": "fw", "code": "x", "detail": "y"}]}

    monkeypatch.setattr(client, "_call", fake)
    assert client.running() == ["fw"]
    assert client.workspace()["on_close"] == "keep"
    client.hide_reminder()
    assert calls[-1] == (
        "PUT",
        "/preferences",
        {"workspace": {"on_close": "keep", "close_reminder": False}},
    )
    assert client.act("shutdown") == ["fw"]
