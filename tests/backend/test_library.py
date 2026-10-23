from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import libvirt
import pytest
from fastapi.testclient import TestClient

from kvmstudio.config import Config
from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.services import domain_xml
from kvmstudio.services.library import metadata_folder, placement

from .helpers import AUTH, add_domain, needs_qemu_img, qcow2, touch
from .helpers import domain_xml as make_xml


def inactive_xml(conn: LibvirtConnection, uuid: str) -> str:
    return conn.run(lambda c: c.lookupByUUIDString(uuid).XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))


def disk_paths(conn: LibvirtConnection, uuid: str) -> list[str]:
    return [d.path for d in domain_xml.disks(inactive_xml(conn, uuid)) if d.path]


def vm(client: TestClient, uuid: str) -> dict[str, Any]:
    return next(v for v in client.get("/api/vms", headers=AUTH).json() if v["uuid"] == uuid)


def backing_of(path: Path) -> str | None:
    out = subprocess.run(  # noqa: S603
        ["qemu-img", "info", "--output=json", "-U", str(path)],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    value = json.loads(out).get("backing-filename")
    return str(value) if value else None


# Placement


def test_managed_vm_is_placed_by_its_files(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    disk = touch(library / "Labs" / "Sub" / "SRV" / "SRV.raw")
    dom = add_domain(conn, define, make_xml("SRV", [("disk", str(disk))]))
    entry = vm(lib_client, dom.UUIDString())
    assert entry["folder"] == "Labs/Sub"
    assert entry["managed"] is True
    assert entry["drift"] == []


def test_outside_vm_is_placed_by_metadata(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], tmp_path: Path
) -> None:
    disk = touch(tmp_path / "virt-manager" / "fw.qcow2")
    dom = add_domain(conn, define, make_xml("FW", [("disk", str(disk))]))
    uuid = dom.UUIDString()
    assert vm(lib_client, uuid)["folder"] == ""
    assert (
        lib_client.post("/api/library/folders", headers=AUTH, json={"path": "Labs"}).status_code
        == 201
    )
    assert (
        lib_client.post(f"/api/vms/{uuid}/move", headers=AUTH, json={"folder": "Labs"}).status_code
        == 204
    )
    entry = vm(lib_client, uuid)
    assert entry["folder"] == "Labs"
    assert entry["managed"] is False
    assert disk.exists()
    assert disk_paths(conn, uuid) == [str(disk)]
    assert metadata_folder(inactive_xml(conn, uuid)) == "Labs"


def test_hand_moved_files_are_reported_not_fixed(
    lib_client: TestClient,
    conn: LibvirtConnection,
    define: list[libvirt.virDomain],
    library: Path,
    lib_config: Config,
) -> None:
    disk = touch(library / "Labs" / "SRV" / "SRV.raw")
    dom = add_domain(conn, define, make_xml("SRV", [("disk", str(disk))]))
    uuid = dom.UUIDString()
    lib_client.post(f"/api/vms/{uuid}/move", headers=AUTH, json={"folder": "Labs"})
    (library / "Masters").mkdir()
    shutil.move(library / "Labs" / "SRV", library / "Masters" / "SRV")

    entry = vm(lib_client, uuid)
    assert entry["folder"] == "Labs"  # rebuilt from <metadata>
    assert "missing_files" in entry["drift"]
    assert disk_paths(conn, uuid) == [str(disk)]  # nothing rewritten behind the user's back
    response = lib_client.post(f"/api/vms/{uuid}/move", headers=AUTH, json={"folder": "Masters"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "library.drift"


def test_folder_mismatch_is_detected(library: Path, lib_config: Config) -> None:
    disk = touch(library / "A" / "VM" / "VM.raw")
    xml = make_xml("VM", [("disk", str(disk))]).replace(
        "</os>",
        "</os><metadata><kvmstudio:vm xmlns:kvmstudio="
        "'https://github.com/rm-networks/kvm-studio/ns/1.0'>"
        "<kvmstudio:folder>B</kvmstudio:folder></kvmstudio:vm></metadata>",
    )
    place = placement(xml, lib_config)
    assert place.folder == "A"
    assert place.drift == ("folder_mismatch",)


# Folders


def test_folders_mirror_the_disk(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    for folder in ("Labs", "Labs/Réseau", "Masters"):
        response = lib_client.post("/api/library/folders", headers=AUTH, json={"path": folder})
        assert response.status_code == 201
    assert (library / "Labs" / "Réseau").is_dir()
    disk = touch(library / "Labs" / "SRV" / "SRV.raw")
    add_domain(conn, define, make_xml("SRV", [("disk", str(disk))]))

    info = lib_client.get("/api/library", headers=AUTH).json()
    assert info["root"] == str(library)
    # The VM's own folder (Labs/SRV) is not a library folder.
    assert info["folders"] == ["Labs", "Labs/Réseau", "Masters"]


@pytest.mark.parametrize("path", ["", "..", "a/../b", "a//b/..", ".cache", "x/" * 9, "bad\\name"])
def test_invalid_folder_names(lib_client: TestClient, path: str) -> None:
    response = lib_client.post("/api/library/folders", headers=AUTH, json={"path": path})
    assert response.status_code in (403, 422)


def test_existing_folder_conflicts(lib_client: TestClient) -> None:
    lib_client.post("/api/library/folders", headers=AUTH, json={"path": "Labs"})
    response = lib_client.post("/api/library/folders", headers=AUTH, json={"path": "Labs"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "library.exists"


def test_folders_need_a_location(lib_client: TestClient, lib_config: Config) -> None:
    lib_config.storage.vm_default_location = None
    response = lib_client.post("/api/library/folders", headers=AUTH, json={"path": "Labs"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "library.no_location"


def test_symlinked_folder_cannot_escape(
    lib_client: TestClient, library: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (library / "Escape").symlink_to(outside)
    response = lib_client.post("/api/library/folders", headers=AUTH, json={"path": "Escape/x"})
    assert response.status_code == 403
    assert not (outside / "x").exists()


# Moving


def test_move_vm_moves_its_files(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    vm_dir = library / "Labs" / "SRV-WS22"
    disk, disk2 = touch(vm_dir / "SRV-WS22.raw"), touch(vm_dir / "SRV-WS22-2.raw")
    nvram = touch(vm_dir / "SRV-WS22_VARS.fd")
    dom = add_domain(
        conn,
        define,
        make_xml("SRV-WS22", [("disk", str(disk)), ("disk", str(disk2))], nvram=str(nvram)),
    )
    uuid = dom.UUIDString()
    (library / "Masters").mkdir()

    response = lib_client.post(f"/api/vms/{uuid}/move", headers=AUTH, json={"folder": "Masters"})
    assert response.status_code == 204
    new_dir = library / "Masters" / "SRV-WS22"
    assert not vm_dir.exists()
    assert sorted(p.name for p in new_dir.iterdir()) == [
        "SRV-WS22-2.raw",
        "SRV-WS22.raw",
        "SRV-WS22_VARS.fd",
    ]
    xml = inactive_xml(conn, uuid)
    assert disk_paths(conn, uuid) == [
        str(new_dir / "SRV-WS22.raw"),
        str(new_dir / "SRV-WS22-2.raw"),
    ]
    assert domain_xml.nvram_path(xml) == str(new_dir / "SRV-WS22_VARS.fd")
    assert vm(lib_client, uuid)["folder"] == "Masters"


def test_move_refuses_running_vm_and_missing_target(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    disk = touch(library / "RUN" / "RUN.raw")
    dom = add_domain(conn, define, make_xml("RUN", [("disk", str(disk))]))
    uuid = dom.UUIDString()
    response = lib_client.post(f"/api/vms/{uuid}/move", headers=AUTH, json={"folder": "Nowhere"})
    assert response.status_code == 404
    (library / "Labs").mkdir()
    dom.create()
    response = lib_client.post(f"/api/vms/{uuid}/move", headers=AUTH, json={"folder": "Labs"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "vm.not_shut_off"
    assert disk.exists()


@needs_qemu_img
def test_move_is_blocked_when_a_linked_clone_depends_on_it(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    base = qcow2(library / "Masters" / "BASE" / "BASE.qcow2")
    master = add_domain(conn, define, make_xml("BASE", [("disk", str(base))]))
    clone = qcow2(library / "Labs" / "CLONE" / "CLONE.qcow2", backing=base)
    add_domain(conn, define, make_xml("CLONE", [("disk", str(clone))]))

    response = lib_client.post(
        f"/api/vms/{master.UUIDString()}/move", headers=AUTH, json={"folder": "Labs"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "library.backing_in_use"
    assert str(clone) in response.json()["error"]["detail"]
    assert base.exists()


@needs_qemu_img
def test_move_updates_a_chain_inside_the_vm_folder(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    vm_dir = library / "Labs" / "CHAIN"
    base = qcow2(vm_dir / "CHAIN-base.qcow2")
    top = qcow2(vm_dir / "CHAIN.qcow2", backing=base)  # absolute backing path
    dom = add_domain(conn, define, make_xml("CHAIN", [("disk", str(top))]))
    (library / "Masters").mkdir()

    response = lib_client.post(
        f"/api/vms/{dom.UUIDString()}/move", headers=AUTH, json={"folder": "Masters"}
    )
    assert response.status_code == 204
    new_top = library / "Masters" / "CHAIN" / "CHAIN.qcow2"
    assert backing_of(new_top) == str(library / "Masters" / "CHAIN" / "CHAIN-base.qcow2")


# Renaming and deleting folders


def test_rename_folder_follows_vms(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    disk = touch(library / "Labs" / "Net" / "R1" / "R1.raw")
    dom = add_domain(conn, define, make_xml("R1", [("disk", str(disk))]))
    uuid = dom.UUIDString()
    response = lib_client.post(
        "/api/library/folders/rename", headers=AUTH, json={"path": "Labs", "name": "Formation"}
    )
    assert response.json() == {"path": "Formation"}
    assert (library / "Formation" / "Net" / "R1" / "R1.raw").exists()
    assert disk_paths(conn, uuid) == [str(library / "Formation" / "Net" / "R1" / "R1.raw")]
    assert vm(lib_client, uuid)["folder"] == "Formation/Net"


def test_rename_folder_refuses_running_vms(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    disk = touch(library / "Labs" / "R2" / "R2.raw")
    dom = add_domain(conn, define, make_xml("R2", [("disk", str(disk))]))
    dom.create()
    response = lib_client.post(
        "/api/library/folders/rename", headers=AUTH, json={"path": "Labs", "name": "X"}
    )
    assert response.status_code == 409
    assert "R2" in response.json()["error"]["detail"]
    assert (library / "Labs").is_dir()


def test_delete_folder_lists_then_deletes_exactly(
    lib_client: TestClient,
    conn: LibvirtConnection,
    define: list[libvirt.virDomain],
    library: Path,
    tmp_path: Path,
) -> None:
    a = touch(library / "Old" / "A" / "A.raw")
    b = touch(library / "Old" / "Sub" / "B" / "B.raw")
    shared = touch(library / "Old" / "shared.raw")
    note = touch(library / "Old" / "notes.txt")
    iso = touch(library / "Old" / "setup.iso")
    outside = touch(tmp_path / "ext" / "ext.raw")
    vm_a = add_domain(conn, define, make_xml("A", [("disk", str(a)), ("disk", str(outside))]))
    vm_b = add_domain(conn, define, make_xml("B", [("disk", str(b))]))
    add_domain(conn, define, make_xml("KEEPER", [("disk", str(shared))]))
    (library / "Elsewhere").mkdir()
    lib_client.post(
        f"/api/vms/{define[-1].UUIDString()}/move", headers=AUTH, json={"folder": "Elsewhere"}
    )

    plan = lib_client.get("/api/library/folders/deletion-plan?path=Old", headers=AUTH).json()
    assert sorted(v["name"] for v in plan["vms"]) == ["A", "B"]
    assert sorted(p for v in plan["vms"] for p in v["delete"]) == sorted([str(a), str(b)])
    assert plan["extra_files"] == [str(note)]
    reasons = {Path(k["path"]).name: k["reason"] for k in plan["keep"]}
    assert reasons == {"shared.raw": "shared", "setup.iso": "iso"}

    result = lib_client.delete("/api/library/folders?path=Old", headers=AUTH).json()
    assert result == {"failed": []}
    for gone in (a, b, note):
        assert not gone.exists()
    for kept in (shared, iso, outside):
        assert kept.exists()
    assert not (library / "Old" / "Sub").exists()  # emptied folders are gone
    for dom in (vm_a, vm_b):
        with pytest.raises(libvirt.libvirtError):
            conn.domain_summary(dom.UUIDString())


def test_delete_folder_refuses_running_vms(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    disk = touch(library / "Busy" / "R" / "R.raw")
    add_domain(conn, define, make_xml("R", [("disk", str(disk))])).create()
    response = lib_client.delete("/api/library/folders?path=Busy", headers=AUTH)
    assert response.status_code == 409
    assert disk.exists()


def test_deleting_a_vm_removes_its_empty_folder(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    disk = touch(library / "Labs" / "GONE" / "GONE.raw")
    dom = add_domain(conn, define, make_xml("GONE", [("disk", str(disk))]))
    lib_client.delete(f"/api/vms/{dom.UUIDString()}?files=true", headers=AUTH)
    assert not (library / "Labs" / "GONE").exists()
    assert (library / "Labs").is_dir()  # the library folder stays


# Bringing outside VMs in


@needs_qemu_img
def test_import_copies_outside_disks_and_keeps_originals(
    lib_client: TestClient,
    conn: LibvirtConnection,
    define: list[libvirt.virDomain],
    library: Path,
    tmp_path: Path,
) -> None:
    original = qcow2(tmp_path / "images" / "fw.qcow2")
    dom = add_domain(conn, define, make_xml("FW-OPN", [("disk", str(original))]))
    uuid = dom.UUIDString()
    (library / "Labs").mkdir()

    result = lib_client.post(
        f"/api/vms/{uuid}/import", headers=AUTH, json={"folder": "Labs"}
    ).json()
    copy = library / "Labs" / "FW-OPN" / "FW-OPN.qcow2"
    assert result == {"copied": [str(copy)], "originals": [str(original)]}
    assert copy.exists()
    assert original.exists()
    assert disk_paths(conn, uuid) == [str(copy)]
    entry = vm(lib_client, uuid)
    assert entry["managed"] is True
    assert entry["folder"] == "Labs"


def test_transient_vm_can_be_filed(
    lib_client: TestClient, conn: LibvirtConnection, library: Path
) -> None:
    dom = conn.run(
        lambda c: c.createXML(
            "<domain type='test'><name>transient</name><memory>65536</memory>"
            "<os><type>hvm</type></os></domain>"
        )
    )
    try:
        (library / "Labs").mkdir()
        uuid = dom.UUIDString()
        response = lib_client.post(f"/api/vms/{uuid}/move", headers=AUTH, json={"folder": "Labs"})
        assert response.status_code == 204
        assert vm(lib_client, uuid)["folder"] == "Labs"
    finally:
        dom.destroy()
