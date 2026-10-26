from __future__ import annotations

from pathlib import Path
from typing import Any

import libvirt
import pytest
from fastapi.testclient import TestClient

from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.services import disks, qemu_img

from .helpers import AUTH, add_domain, needs_qemu_img
from .helpers import domain_xml as make_xml

GIB = 1024**3


def qcow2(path: Path, gib: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    qemu_img.create(path, "qcow2", gib, preallocate=False)
    return path


@needs_qemu_img
def test_expand_a_powered_off_disk(
    lib_client: TestClient,
    conn: LibvirtConnection,
    define: list[libvirt.virDomain],
    library: Path,
    monkeypatch: Any,
) -> None:
    # libvirt resizes the volume as root; the test driver has no real pools.
    resized: list[tuple[Path, int]] = []

    def resize_volume(_c: libvirt.virConnect, path: Path, wanted: int) -> None:
        resized.append((path, wanted))
        qemu_img._run(["resize", str(path), str(wanted)])

    monkeypatch.setattr(disks, "_resize_volume", resize_volume)
    disk = qcow2(library / "BIG" / "BIG.qcow2", 2)
    dom = add_domain(conn, define, make_xml("BIG", [("disk", str(disk))]))
    url = f"/api/vms/{dom.UUIDString()}/disks/vda"
    info = lib_client.get(url, headers=AUTH).json()
    assert (info["capacity"], info["expandable"]) == (2 * GIB, True)

    r = lib_client.post(f"{url}/expand", headers=AUTH, json={"gib": 2})
    assert r.json()["error"]["code"] == "disk.not_larger"
    r = lib_client.post(f"{url}/expand", headers=AUTH, json={"gib": 5})
    assert r.status_code == 200, r.text
    assert r.json()["capacity"] == 5 * GIB
    assert resized == [(disk, 5 * GIB)]


@needs_qemu_img
def test_only_disks_in_the_library(
    lib_client: TestClient,
    conn: LibvirtConnection,
    define: list[libvirt.virDomain],
    tmp_path: Path,
) -> None:
    disk = qcow2(tmp_path / "elsewhere" / "OUT.qcow2", 1)
    dom = add_domain(conn, define, make_xml("OUT", [("disk", str(disk))]))
    url = f"/api/vms/{dom.UUIDString()}/disks/vda"
    assert lib_client.get(url, headers=AUTH).json()["expandable"] is False
    r = lib_client.post(f"{url}/expand", headers=AUTH, json={"gib": 4})
    assert r.status_code == 403


@needs_qemu_img
def test_not_under_linked_clones(
    lib_client: TestClient,
    conn: LibvirtConnection,
    define: list[libvirt.virDomain],
    library: Path,
    monkeypatch: Any,
) -> None:
    disk = qcow2(library / "BASE" / "BASE.qcow2", 1)
    dom = add_domain(conn, define, make_xml("BASE", [("disk", str(disk))]))
    monkeypatch.setattr("kvmstudio.services.disks.linked_clones", lambda c, u: ["CLONE"])
    r = lib_client.post(
        f"/api/vms/{dom.UUIDString()}/disks/vda/expand", headers=AUTH, json={"gib": 4}
    )
    assert r.json()["error"]["code"] == "disk.linked_clones"


def test_unknown_disk(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain]
) -> None:
    dom = add_domain(conn, define, make_xml("NONE", []))
    r = lib_client.get(f"/api/vms/{dom.UUIDString()}/disks/vdz", headers=AUTH)
    assert r.status_code == 404


@pytest.mark.parametrize("gib", [0, -1])
def test_size_must_be_positive(lib_client: TestClient, gib: int) -> None:
    r = lib_client.post("/api/vms/x/disks/vda/expand", headers=AUTH, json={"gib": gib})
    assert r.status_code == 422
