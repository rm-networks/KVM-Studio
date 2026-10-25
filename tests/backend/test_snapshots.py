from __future__ import annotations

from pathlib import Path
from typing import Any

import libvirt
from fastapi.testclient import TestClient

from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.services import clone

from .helpers import AUTH, add_domain, touch
from .helpers import domain_xml as make_xml


def url(dom: libvirt.virDomain, rest: str = "") -> str:
    return f"/api/vms/{dom.UUIDString()}/snapshots{rest}"


def test_take_list_revert_delete(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    disk = touch(library / "SNAP" / "SNAP.qcow2")
    dom = add_domain(conn, define, make_xml("SNAP", [("disk", str(disk))]))
    r = lib_client.post(url(dom), headers=AUTH, json={"name": "Clean", "description": "fresh"})
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "Clean"
    lib_client.post(url(dom), headers=AUTH, json={"name": "Later"}).raise_for_status()
    snaps = lib_client.get(url(dom), headers=AUTH).json()
    assert [(s["name"], s["parent"], s["current"]) for s in snaps] == [
        ("Clean", None, False),
        ("Later", "Clean", True),
    ]
    assert snaps[0]["description"] == "fresh"
    assert lib_client.post(url(dom), headers=AUTH, json={"name": "Clean"}).status_code == 409
    assert lib_client.post(url(dom), headers=AUTH, json={"name": "a/b"}).status_code == 422

    assert lib_client.post(url(dom, "/Clean/revert"), headers=AUTH).status_code == 204
    current = [s["name"] for s in lib_client.get(url(dom), headers=AUTH).json() if s["current"]]
    assert current == ["Clean"]

    # A VM with snapshots does not move: libvirt keeps the old paths in them.
    (library / "Other").mkdir()
    r = lib_client.post(f"/api/vms/{dom.UUIDString()}/move", headers=AUTH, json={"folder": "Other"})
    assert r.json()["error"]["code"] == "library.has_snapshots"

    assert lib_client.delete(url(dom, "/Clean"), headers=AUTH).status_code == 204
    assert [s["name"] for s in lib_client.get(url(dom), headers=AUTH).json()] == ["Later"]


def test_linked_clones_block_snapshots(
    lib_client: TestClient,
    conn: LibvirtConnection,
    define: list[libvirt.virDomain],
    library: Path,
    monkeypatch: Any,
) -> None:
    disk = touch(library / "BASE" / "BASE.qcow2")
    dom = add_domain(conn, define, make_xml("BASE", [("disk", str(disk))]))
    monkeypatch.setattr("kvmstudio.services.snapshots.linked_clones", lambda c, u: ["CLONE-1"])
    assert clone.linked_clones is not None
    r = lib_client.post(url(dom), headers=AUTH, json={"name": "x"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "snapshot.linked_clones"
    assert "CLONE-1" in r.json()["error"]["detail"]
    assert lib_client.post(url(dom, "/x/revert"), headers=AUTH).status_code == 409
