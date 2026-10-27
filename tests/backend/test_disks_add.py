"""Add Hard Disk and Remove, on test:///default with real qemu-img images."""

from __future__ import annotations

import contextlib
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import libvirt
import pytest
from fastapi.testclient import TestClient
from lxml import etree

from kvmstudio.config import Config
from kvmstudio.errors import ApiException
from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.services import disks
from kvmstudio.services.create import NewVm, create_vm

from .helpers import AUTH, touch

pytestmark = pytest.mark.skipif(not shutil.which("qemu-img"), reason="no qemu-img")


@pytest.fixture
def vm(conn: LibvirtConnection, lib_config: Config) -> Iterator[str]:
    new = NewVm(
        name="disk-vm",
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
        nics=[],
        uefi=False,
        tpm=False,
    )
    uuid = create_vm(conn, lib_config, new)
    yield uuid
    for name in ("disk-vm", "other-vm"):
        with contextlib.suppress(libvirt.libvirtError):
            dom = conn.run(lambda c, n=name: c.lookupByName(n))  # type: ignore[misc]
            if dom.isActive():
                dom.destroy()
            dom.undefine()


def config_disks(conn: LibvirtConnection, uuid: str) -> list[etree._Element]:
    xml = conn.run(lambda c: c.lookupByUUIDString(uuid).XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))
    return list(etree.fromstring(xml.encode()).iterfind("devices/disk[@device='disk']"))


def test_new_disk_in_the_vm_folder(
    lib_client: TestClient, conn: LibvirtConnection, library: Path, vm: str
) -> None:
    folder = lib_client.get(f"/api/vms/{vm}/disks-folder", headers=AUTH).json()["path"]
    assert folder == str(library / "disk-vm")
    r = lib_client.post(f"/api/vms/{vm}/disks", headers=AUTH, json={"size_gib": 2})
    assert r.status_code == 201
    assert r.json() == {"target": "vdb", "path": str(library / "disk-vm" / "disk-vm-1.qcow2")}
    assert (library / "disk-vm" / "disk-vm-1.qcow2").is_file()
    added = config_disks(conn, vm)[-1]
    assert added.find("target").get("bus") == "virtio"  # type: ignore[union-attr]
    assert added.find("driver").get("type") == "qcow2"  # type: ignore[union-attr]
    size = lib_client.get(f"/api/vms/{vm}/disks/vdb", headers=AUTH).json()
    assert size["capacity"] == 2 * 1024**3
    assert size["deletable"] is True
    sata = lib_client.post(
        f"/api/vms/{vm}/disks", headers=AUTH, json={"size_gib": 1, "bus": "sata"}
    )
    assert sata.json()["target"] == "sdb"  # sda: the CD/DVD drive
    assert sata.json()["path"].endswith("disk-vm-2.qcow2")
    bad = lib_client.post(f"/api/vms/{vm}/disks", headers=AUTH, json={"size_gib": 0})
    assert bad.status_code == 422


def test_existing_disk_anywhere_for_the_owner(
    lib_client: TestClient, conn: LibvirtConnection, tmp_path: Path, vm: str
) -> None:
    outside = touch(tmp_path / "Downloads" / "data.img")
    body = {"existing": str(outside), "bus": "scsi"}
    r = lib_client.post(f"/api/vms/{vm}/disks", headers=AUTH, json=body)
    assert r.json() == {"target": "sdb", "path": str(outside)}
    xml = conn.run(lambda c: c.lookupByUUIDString(vm).XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))
    root = etree.fromstring(xml.encode())
    assert root.find("devices/controller[@type='scsi']").get("model") == "virtio-scsi"  # type: ignore[union-attr]
    assert config_disks(conn, vm)[-1].find("driver").get("type") == "raw"  # type: ignore[union-attr]
    # Outside the library: never deletable with the disk.
    assert lib_client.get(f"/api/vms/{vm}/disks/sdb", headers=AUTH).json()["deletable"] is False
    refused = lib_client.delete(f"/api/vms/{vm}/disks/sdb?delete_file=true", headers=AUTH)
    assert refused.status_code == 409
    assert len(config_disks(conn, vm)) == 2
    kept = lib_client.delete(f"/api/vms/{vm}/disks/sdb", headers=AUTH)
    assert kept.json() == {"deleted": []}
    assert outside.is_file()
    assert len(config_disks(conn, vm)) == 1


def test_guest_adds_existing_disks_from_the_library_only(
    conn: LibvirtConnection, lib_config: Config, tmp_path: Path, library: Path, vm: str
) -> None:
    outside = touch(tmp_path / "Downloads" / "data.img")
    with pytest.raises(ApiException) as err:
        disks.add(conn, lib_config, vm, bus="virtio", existing=str(outside), confined=True)
    assert err.value.status == 403
    inside = touch(library / "shared" / "data.img")
    added = disks.add(conn, lib_config, vm, bus="virtio", existing=str(inside), confined=True)
    assert added.path == str(inside)


def test_remove_and_delete_the_file(
    lib_client: TestClient, conn: LibvirtConnection, library: Path, vm: str
) -> None:
    path = lib_client.post(f"/api/vms/{vm}/disks", headers=AUTH, json={"size_gib": 1}).json()[
        "path"
    ]
    r = lib_client.delete(f"/api/vms/{vm}/disks/vdb?delete_file=true", headers=AUTH)
    assert r.json() == {"deleted": [path]}
    assert not Path(path).exists()
    assert len(config_disks(conn, vm)) == 1
    assert lib_client.delete(f"/api/vms/{vm}/disks/vdz", headers=AUTH).status_code == 404


def test_file_used_by_another_vm_is_not_deleted(
    lib_client: TestClient, conn: LibvirtConnection, vm: str
) -> None:
    path = lib_client.post(f"/api/vms/{vm}/disks", headers=AUTH, json={"size_gib": 1}).json()[
        "path"
    ]
    xml = (
        "<domain type='test'><name>other-vm</name><memory unit='MiB'>64</memory>"
        "<os><type>hvm</type></os><devices><disk type='file' device='disk'>"
        f"<source file='{path}'/><target dev='vda' bus='virtio'/></disk></devices></domain>"
    )
    conn.run(lambda c: c.defineXML(xml))
    assert lib_client.get(f"/api/vms/{vm}/disks/vdb", headers=AUTH).json()["deletable"] is False
    r = lib_client.delete(f"/api/vms/{vm}/disks/vdb?delete_file=true", headers=AUTH)
    assert r.status_code == 409
    assert Path(path).is_file()


def test_refused_hotplug_changes_nothing(
    lib_client: TestClient,
    conn: LibvirtConnection,
    library: Path,
    vm: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dom = conn.run(lambda c: c.lookupByUUIDString(vm))
    dom.create()

    def refuse(_self: Any, _xml: str, _flags: int) -> int:
        raise libvirt.libvirtError("Operation not supported: disk bus 'sata' cannot be hotplugged")

    monkeypatch.setattr(libvirt.virDomain, "attachDeviceFlags", refuse)
    r = lib_client.post(f"/api/vms/{vm}/disks", headers=AUTH, json={"size_gib": 1, "bus": "sata"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "disk.hotplug_refused"
    assert not (library / "disk-vm" / "disk-vm-1.qcow2").exists()
    assert len(config_disks(conn, vm)) == 1


def test_guest_keeping_the_disk_changes_nothing(
    lib_client: TestClient, conn: LibvirtConnection, vm: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = lib_client.post(f"/api/vms/{vm}/disks", headers=AUTH, json={"size_gib": 1}).json()[
        "path"
    ]
    conn.run(lambda c: c.lookupByUUIDString(vm)).create()
    # A guest that never acknowledges the unplug.
    monkeypatch.setattr(libvirt.virDomain, "detachDeviceFlags", lambda *_a: 0)
    monkeypatch.setattr(disks, "UNPLUG_WAIT", 0.1)
    r = lib_client.delete(f"/api/vms/{vm}/disks/vdb?delete_file=true", headers=AUTH)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "disk.unplug_refused"
    assert Path(path).is_file()
    assert len(config_disks(conn, vm)) == 2
