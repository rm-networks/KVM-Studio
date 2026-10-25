from __future__ import annotations

from pathlib import Path

import libvirt
import pytest
from fastapi.testclient import TestClient

from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.services import domain_xml, folder_order

from .helpers import AUTH, add_domain, needs_qemu_img, qcow2, touch
from .helpers import domain_xml as make_xml


def disk_paths(conn: LibvirtConnection, uuid: str) -> list[str]:
    xml = conn.run(lambda c: c.lookupByUUIDString(uuid).XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))
    return [d.path for d in domain_xml.disks(xml) if d.path]


def plan(client: TestClient, path: str, parent: str) -> dict[str, object]:
    r = client.get(
        "/api/library/folders/move-plan", headers=AUTH, params={"path": path, "parent": parent}
    )
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def test_move_folder_under_another_moves_the_vm_files(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    disk = touch(library / "Labs" / "Net" / "R1" / "R1.raw")
    dom = add_domain(conn, define, make_xml("R1", [("disk", str(disk))]))
    (library / "Formation" / "2026").mkdir(parents=True)

    assert plan(lib_client, "Labs", "Formation/2026") == {
        "folder": "Labs",
        "target": "Formation/2026/Labs",
        "vms": ["R1"],
        "running": [],
        "blockers": [],
    }
    r = lib_client.post(
        "/api/library/folders/move",
        headers=AUTH,
        json={"path": "Labs", "parent": "Formation/2026"},
    )
    assert r.json() == {"path": "Formation/2026/Labs"}
    moved = library / "Formation" / "2026" / "Labs" / "Net" / "R1" / "R1.raw"
    assert moved.exists()
    assert not (library / "Labs").exists()
    assert disk_paths(conn, dom.UUIDString()) == [str(moved)]

    # And back to the top level.
    r = lib_client.post(
        "/api/library/folders/move",
        headers=AUTH,
        json={"path": "Formation/2026/Labs", "parent": ""},
    )
    assert r.json() == {"path": "Labs"}
    assert disk_paths(conn, dom.UUIDString()) == [str(library / "Labs" / "Net" / "R1" / "R1.raw")]


@pytest.mark.parametrize(("path", "parent"), [("Labs", "Labs"), ("Labs", "Labs/Net"), ("", "X")])
def test_a_folder_cannot_go_inside_itself(
    lib_client: TestClient, library: Path, path: str, parent: str
) -> None:
    (library / "Labs" / "Net").mkdir(parents=True)
    (library / "X").mkdir()
    r = lib_client.post(
        "/api/library/folders/move", headers=AUTH, json={"path": path, "parent": parent}
    )
    assert r.status_code in (409, 422)
    assert (library / "Labs" / "Net").is_dir()


def test_move_refuses_running_vms_and_outside_linked_clones(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    disk = touch(library / "Labs" / "R2" / "R2.raw")
    dom = add_domain(conn, define, make_xml("R2", [("disk", str(disk))]))
    (library / "Other").mkdir()
    dom.create()
    assert plan(lib_client, "Labs", "Other")["running"] == ["R2"]
    r = lib_client.post(
        "/api/library/folders/move", headers=AUTH, json={"path": "Labs", "parent": "Other"}
    )
    assert r.status_code == 409
    assert (library / "Labs" / "R2" / "R2.raw").exists()


@needs_qemu_img
def test_move_blocked_by_a_linked_clone_outside(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    base = qcow2(library / "Masters" / "BASE" / "BASE.qcow2")
    add_domain(conn, define, make_xml("BASE", [("disk", str(base))]))
    clone = qcow2(library / "Labs" / "CL" / "CL.qcow2", backing=base)
    add_domain(conn, define, make_xml("CL", [("disk", str(clone))]))
    (library / "Archive").mkdir()
    assert plan(lib_client, "Masters", "Archive")["blockers"] == [str(clone)]
    r = lib_client.post(
        "/api/library/folders/move", headers=AUTH, json={"path": "Masters", "parent": "Archive"}
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "library.backing_in_use"


def test_display_order_is_kept_in_a_state_file(
    lib_client: TestClient, library: Path, tmp_path: Path
) -> None:
    for name in ("A", "B", "C"):
        (library / name).mkdir()
    r = lib_client.put(
        "/api/library/order", headers=AUTH, json={"parent": "", "names": ["C", "A", "B"]}
    )
    assert r.status_code == 204
    assert lib_client.get("/api/library", headers=AUTH).json()["order"] == {"": ["C", "A", "B"]}
    assert folder_order.order_path() == tmp_path / "state" / "kvm-studio" / "library-order.json"
    assert not any(p.name.endswith(".json") for p in library.rglob("*"))

    # Moving B under C before nothing: last in C, gone from the top level.
    lib_client.post("/api/library/folders/move", headers=AUTH, json={"path": "B", "parent": "C"})
    assert folder_order.load() == {"": ["C", "A"], "C": ["B"]}
    # Reordering in place (same parent) moves no file.
    lib_client.post(
        "/api/library/folders/move", headers=AUTH, json={"path": "A", "parent": "", "before": "C"}
    )
    assert folder_order.load()[""] == ["A", "C"]
    lib_client.post("/api/library/folders/rename", headers=AUTH, json={"path": "C", "name": "D"})
    assert folder_order.load() == {"": ["A", "D"], "D": ["B"]}
    assert (library / "D" / "B").is_dir()


def test_order_names_are_checked(lib_client: TestClient) -> None:
    r = lib_client.put("/api/library/order", headers=AUTH, json={"parent": "../x", "names": ["a"]})
    assert r.status_code == 422
