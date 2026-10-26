from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import libvirt
import pytest
from fastapi.testclient import TestClient

from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.services import clone, snapshots
from kvmstudio.services.tasks import Cancelled, Task

from .helpers import AUTH, add_domain, touch
from .helpers import domain_xml as make_xml


def url(dom: libvirt.virDomain, rest: str = "") -> str:
    return f"/api/vms/{dom.UUIDString()}/snapshots{rest}"


def take(client: TestClient, dom: libvirt.virDomain, **body: Any) -> dict[str, Any]:
    """Starts the snapshot task and waits for its end."""
    r = client.post(url(dom), headers=AUTH, json=body)
    assert r.status_code == 202, r.text
    task: dict[str, Any] = r.json()
    for _ in range(200):
        if task["state"] != "running":
            return task
        time.sleep(0.02)
        task = client.get(f"/api/tasks/{task['id']}", headers=AUTH).json()
    raise AssertionError("the snapshot task did not end")


def test_take_list_revert_delete(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    disk = touch(library / "SNAP" / "SNAP.qcow2")
    dom = add_domain(conn, define, make_xml("SNAP", [("disk", str(disk))]))
    task = take(lib_client, dom, name="Clean", description="fresh")
    assert (task["state"], task["result"]["name"]) == ("done", "Clean")
    assert take(lib_client, dom, name="Later")["state"] == "done"
    snaps = lib_client.get(url(dom), headers=AUTH).json()
    assert [(s["name"], s["parent"], s["current"]) for s in snaps] == [
        ("Clean", None, False),
        ("Later", "Clean", True),
    ]
    assert snaps[0]["description"] == "fresh"
    assert lib_client.post(url(dom), headers=AUTH, json={"name": "Clean"}).status_code == 409
    # QEMU's job name rule (a running VM's snapshot), and no leading dot (libvirt).
    for bad in ("a/b", "Snapshot 1", "été", "a:b", ".x", "a" * 101):
        r = lib_client.post(url(dom), headers=AUTH, json={"name": bad})
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "snapshot.bad_name"

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


def test_running_vm_needs_its_memory(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    disk = touch(library / "RUN" / "RUN.qcow2")
    dom = add_domain(conn, define, make_xml("RUN", [("disk", str(disk))]))
    dom.create()
    try:
        r = lib_client.post(url(dom), headers=AUTH, json={"name": "x", "memory": False})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "snapshot.memory_required"
        assert take(lib_client, dom, name="x", memory=True)["state"] == "done"
    finally:
        dom.destroy()


def test_limits_name_what_libvirt_refuses(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    disk = touch(library / "OLD" / "OLD.img")
    dom = add_domain(
        conn, define, make_xml("OLD", [("disk", str(disk))], nvram=str(library / "OLD" / "V.fd"))
    )
    r = lib_client.get(url(dom, "/limits"), headers=AUTH)
    assert r.json() == {"running": False, "raw_disks": ["vda"], "raw_nvram": True, "tpm": False}


def test_cancel_deletes_the_snapshot_once_written(
    conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    disk = touch(library / "CAN" / "CAN.qcow2")
    dom = add_domain(conn, define, make_xml("CAN", [("disk", str(disk))]))
    task = Task(id="t", kind="snapshot")
    task.cancel.set()
    with pytest.raises(Cancelled):
        snapshots.take(conn, dom.UUIDString(), "gone", "", task)
    assert dom.snapshotListNames(0) == []
