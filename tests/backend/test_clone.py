"""Cloning on the libvirt test driver, with real (small) disk images."""

from __future__ import annotations

import contextlib
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import libvirt
import pytest
from fastapi.testclient import TestClient
from lxml import etree

from kvmstudio import helper_client
from kvmstudio.config import Config
from kvmstudio.errors import ApiException
from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.services import clone, qemu_img
from kvmstudio.services.create import NewVm, NicChoice, create_vm
from kvmstudio.services.library import metadata_values
from kvmstudio.services.tasks import Task, TaskRegistry

from .helpers import AUTH

pytestmark = pytest.mark.skipif(not shutil.which("qemu-img"), reason="no qemu-img")


@pytest.fixture
def source(conn: LibvirtConnection, lib_config: Config) -> Iterator[str]:
    vm = NewVm(
        name="src-vm",
        folder="",
        profile="linux",
        iso=None,
        existing_disk=None,
        disk_gib=1,
        disk_bus="virtio",
        disk_format="qcow2",
        preallocate=False,
        memory_mib=512,
        vcpus=1,
        nics=[NicChoice("default", "virtio"), NicChoice("default", "e1000e")],
        uefi=True,
        tpm=True,
    )
    uuid = create_vm(conn, lib_config, vm)
    yield uuid
    for name in ("src-vm", "copy", "linked", "linked-2", "copy-of-linked"):
        with contextlib.suppress(libvirt.libvirtError):
            dom = conn.run(lambda c, n=name: c.lookupByName(n))  # type: ignore[misc]
            if dom.isActive():
                dom.destroy()
            dom.undefine()


def domain(conn: LibvirtConnection, name: str) -> etree._Element:
    xml = conn.run(lambda c: c.lookupByName(name).XMLDesc(0))
    return etree.fromstring(xml.encode())


def wait(client: TestClient, task: dict[str, Any]) -> dict[str, Any]:
    for _ in range(200):
        task = client.get(f"/api/tasks/{task['id']}", headers=AUTH).json()
        if task["state"] != "running":
            return task
        time.sleep(0.05)
    raise AssertionError("the task did not end")


def clone_request(client: TestClient, uuid: str, **body: Any) -> dict[str, Any]:
    response = client.post(f"/api/vms/{uuid}/clone", headers=AUTH, json=body)
    assert response.status_code == 202, response.json()
    return wait(client, response.json())


def test_full_clone(
    lib_client: TestClient, conn: LibvirtConnection, source: str, library: Path
) -> None:
    done = clone_request(lib_client, source, kind="full", name="copy")
    assert done["state"] == "done", done
    assert done["progress"] == 1
    # Without a helper the firmware variables and TPM start afresh: reported.
    assert done["result"]["warnings"] == ["state_not_copied"]
    disk = library / "copy" / "copy.qcow2"
    assert disk.is_file()
    assert qemu_img.backing_files(disk) == []
    root = domain(conn, "copy")
    src = domain(conn, "src-vm")
    assert root.findtext("uuid") == done["result"]["uuid"] != src.findtext("uuid")
    assert root.find("devices/disk/source").get("file") == str(disk)  # type: ignore[union-attr]
    assert root.findtext("os/nvram") == str(library / "copy" / "copy_VARS.fd")
    assert root.find("devices/tpm") is not None
    # Same hardware, new MAC addresses, card names from the new UUID.
    assert root.findtext("memory") == src.findtext("memory")
    macs = [m.get("address") for m in root.iterfind("devices/interface/mac")]
    old = [m.get("address") for m in src.iterfind("devices/interface/mac")]
    assert len(macs) == 2
    assert not set(macs) & set(old)
    targets = [t.get("dev", "") for t in root.iterfind("devices/interface/target")]
    assert all(t.startswith(f"ks-{done['result']['uuid'][:6]}") for t in targets)
    meta = metadata_values(etree.tostring(root).decode())
    assert meta["folder"] == ""
    assert "linked_to" not in meta


def test_linked_clone_blocks_its_source(
    lib_client: TestClient, conn: LibvirtConnection, source: str, library: Path
) -> None:
    done = clone_request(lib_client, source, kind="linked", name="linked")
    assert done["state"] == "done", done
    overlay = library / "linked" / "linked.qcow2"
    assert qemu_img.backing_files(overlay) == [str(library / "src-vm" / "src-vm.qcow2")]
    assert metadata_values(etree.tostring(domain(conn, "linked")).decode())["linked_to"] == source

    clones = lib_client.get(f"/api/vms/{source}/linked-clones", headers=AUTH).json()
    assert clones == {"names": ["linked"]}
    # Starting the source would change the disks under its clone.
    refused = lib_client.post(f"/api/vms/{source}/power/start", headers=AUTH)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "vm.has_linked_clones"
    assert "linked" in refused.json()["error"]["detail"]
    # Deleting or moving it is refused as well; only the explicit start goes.
    plan = lib_client.get(f"/api/vms/{source}/deletion-plan", headers=AUTH)
    assert plan.json()["error"]["code"] == "vm.has_linked_clones"
    gone = lib_client.delete(f"/api/vms/{source}?files=true", headers=AUTH)
    assert gone.json()["error"]["code"] == "vm.has_linked_clones"
    assert (library / "src-vm" / "src-vm.qcow2").exists()
    lib_client.post("/api/library/folders", headers=AUTH, json={"path": "Lab"})
    moved = lib_client.post(f"/api/vms/{source}/move", headers=AUTH, json={"folder": "Lab"})
    assert moved.status_code == 409
    forced = lib_client.post(f"/api/vms/{source}/power/start?force=true", headers=AUTH)
    assert forced.status_code == 204
    conn.run(lambda c: c.lookupByUUIDString(source).destroy())


def test_a_full_copy_of_a_linked_clone_stands_alone(
    lib_client: TestClient, conn: LibvirtConnection, source: str, library: Path
) -> None:
    linked = clone_request(lib_client, source, kind="linked", name="linked-2")
    copy = clone_request(lib_client, linked["result"]["uuid"], kind="full", name="copy-of-linked")
    assert copy["state"] == "done", copy
    assert qemu_img.backing_files(library / "copy-of-linked" / "copy-of-linked.qcow2") == []
    meta = metadata_values(etree.tostring(domain(conn, "copy-of-linked")).decode())
    assert "linked_to" not in meta


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"kind": "full", "name": "src-vm"}, 409, "vm.exists"),
        ({"kind": "full", "name": "bad/name"}, 422, "vm.bad_name"),
        ({"kind": "full", "name": "x", "folder": "Missing"}, 404, "library.no_folder"),
        ({"kind": "full", "name": "x", "folder": "../.."}, 422, "library.invalid_name"),
    ],
)
def test_refusals(
    lib_client: TestClient, source: str, body: dict[str, Any], status: int, code: str
) -> None:
    response = lib_client.post(f"/api/vms/{source}/clone", headers=AUTH, json=body)
    assert (response.status_code, response.json()["error"]["code"]) == (status, code)


def test_the_source_must_be_off(
    lib_client: TestClient, conn: LibvirtConnection, source: str
) -> None:
    conn.run(lambda c: c.lookupByUUIDString(source).create())
    try:
        response = lib_client.post(
            f"/api/vms/{source}/clone", headers=AUTH, json={"kind": "full", "name": "copy"}
        )
        assert response.json()["error"]["code"] == "vm.not_shut_off"
    finally:
        conn.run(lambda c: c.lookupByUUIDString(source).destroy())


def test_cancel_removes_everything(
    conn: LibvirtConnection, lib_config: Config, source: str, library: Path
) -> None:
    plan = clone.prepare(conn, lib_config, source, "full", "copy", "")
    task = Task(id="t", kind="clone")
    task.cancel.set()
    registry = TaskRegistry()
    started = registry.start("clone", lambda _t: clone.run(conn, plan, task))
    for _ in range(100):
        if started.state != "running":
            break
        time.sleep(0.02)
    assert started.state == "cancelled"
    assert not (library / "copy").exists()
    names = conn.run(lambda c: [d.name() for d in c.listAllDomains()])
    assert "copy" not in names


def test_a_failure_removes_everything(
    conn: LibvirtConnection,
    lib_config: Config,
    source: str,
    library: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refused(op: str, params: dict[str, Any]) -> dict[str, Any]:
        raise ApiException(500, "helper.failed", "copy failed")

    monkeypatch.setattr(helper_client, "call", refused)
    plan = clone.prepare(conn, lib_config, source, "full", "copy", "")
    with pytest.raises(ApiException):
        clone.run(conn, plan, Task(id="t", kind="clone"))
    assert not (library / "copy").exists()
    names = conn.run(lambda c: [d.name() for d in c.listAllDomains()])
    assert "copy" not in names


def test_state_is_copied_by_the_helper(
    conn: LibvirtConnection,
    lib_config: Config,
    source: str,
    library: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (library / "src-vm" / "src-vm_VARS.fd").write_bytes(b"vars")
    calls: list[tuple[str, dict[str, Any]]] = []

    def helper(op: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append((op, params))
        Path(params["nvram_target"]).write_bytes(b"vars")
        return {"nvram": True, "tpm": True}

    monkeypatch.setattr(helper_client, "call", helper)
    plan = clone.prepare(conn, lib_config, source, "linked", "linked", "")
    result = clone.run(conn, plan, Task(id="t", kind="clone"))
    assert result["warnings"] == []
    assert calls == [
        (
            "clone_vm_state",
            {
                "source_uuid": source,
                "target_uuid": result["uuid"],
                "nvram_source": str(library / "src-vm" / "src-vm_VARS.fd"),
                "nvram_target": str(library / "linked" / "linked_VARS.fd"),
            },
        )
    ]
