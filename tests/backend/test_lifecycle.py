from __future__ import annotations

import shutil
import subprocess
import uuid as uuidlib
from collections.abc import Iterator
from pathlib import Path

import libvirt
import pytest
from fastapi.testclient import TestClient

from kvmstudio.app import create_app
from kvmstudio.config import Config, IsoLibrary, LibvirtSettings, StorageSettings
from kvmstudio.libvirt_conn import LibvirtConnection

from .conftest import TEST_URI, TOKEN

AUTH = {"Authorization": f"Bearer {TOKEN}"}
needs_qemu_img = pytest.mark.skipif(shutil.which("qemu-img") is None, reason="needs qemu-img")


def domain_xml(name: str, disks: list[tuple[str, str]], nvram: str | None = None) -> str:
    """Test-driver domain; disks are (device, path) pairs."""
    devices = "".join(
        f"<disk type='file' device='{device}'><source file='{path}'/>"
        f"<target dev='vd{chr(97 + i)}'/></disk>"
        for i, (device, path) in enumerate(disks)
    )
    loader = (
        f"<loader readonly='yes' type='pflash'>/usr/share/edk2/ovmf/OVMF_CODE.fd</loader>"
        f"<nvram>{nvram}</nvram>"
        if nvram
        else ""
    )
    return (
        f"<domain type='test'><name>{name}</name><uuid>{uuidlib.uuid4()}</uuid>"
        f"<memory>65536</memory><os><type>hvm</type>{loader}</os>"
        f"<devices>{devices}</devices></domain>"
    )


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "data" / "KVM-Studio" / "VM"
    root.mkdir(parents=True)
    return root


@pytest.fixture
def lib_config(tmp_path: Path, library: Path) -> Config:
    iso = tmp_path / "iso"
    iso.mkdir()
    return Config(
        libvirt=LibvirtSettings(uri=TEST_URI),
        storage=StorageSettings(vm_default_location=tmp_path / "data"),
        iso_libraries=[IsoLibrary(name="ISO", path=iso)],
    )


@pytest.fixture
def client(lib_config: Config, conn: LibvirtConnection, frontend_dir: Path) -> TestClient:
    app = create_app(lib_config, conn, TOKEN, mode="web", frontend_dir=frontend_dir)
    return TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture
def define(conn: LibvirtConnection) -> Iterator[list[libvirt.virDomain]]:
    created: list[libvirt.virDomain] = []
    yield created
    for dom in created:
        try:
            if dom.isActive():
                dom.destroy()
            dom.undefine()
        except libvirt.libvirtError:
            pass


def add_domain(
    conn: LibvirtConnection, created: list[libvirt.virDomain], xml: str
) -> libvirt.virDomain:
    dom = conn.run(lambda c: c.defineXML(xml))
    created.append(dom)
    return dom


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * 512)
    return path


def qcow2(path: Path, backing: Path | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["qemu-img", "create", "-q", "-f", "qcow2"]
    if backing:
        cmd += ["-b", str(backing), "-F", "qcow2"]
    subprocess.run([*cmd, str(path), "16M"], check=True)  # noqa: S603
    return path


def test_power_cycle_of_the_test_domain(client: TestClient, conn: LibvirtConnection) -> None:
    uuid = conn.run(lambda c: c.lookupByName("test").UUIDString())
    try:
        assert client.post(f"/api/vms/{uuid}/power/poweroff", headers=AUTH).status_code == 204
        assert conn.domain_summary(uuid).state == "shutoff"
        response = client.post(f"/api/vms/{uuid}/power/shutdown", headers=AUTH)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "libvirt.invalid_state"
        assert client.post(f"/api/vms/{uuid}/power/start", headers=AUTH).status_code == 204
        assert conn.domain_summary(uuid).state == "running"
        assert client.post(f"/api/vms/{uuid}/power/reboot", headers=AUTH).status_code == 204
        assert client.post(f"/api/vms/{uuid}/power/reset", headers=AUTH).status_code == 204
    finally:
        dom = conn.run(lambda c: c.lookupByUUIDString(uuid))
        if not dom.isActive():
            dom.create()


def test_unknown_power_action_is_rejected(client: TestClient) -> None:
    response = client.post("/api/vms/x/power/explode", headers=AUTH)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request.invalid"


def test_unknown_vm_is_a_404(client: TestClient) -> None:
    response = client.post(f"/api/vms/{uuidlib.uuid4()}/power/start", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "libvirt.no_domain"


def test_rename(
    client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain]
) -> None:
    dom = add_domain(conn, define, domain_xml("old-name", []))
    uuid = dom.UUIDString()
    response = client.patch(f"/api/vms/{uuid}", headers=AUTH, json={"name": "Nouveau nom 2"})
    assert response.status_code == 204
    assert conn.domain_summary(uuid).name == "Nouveau nom 2"


@pytest.mark.parametrize("name", ["", "a/b", ".hidden", "trailing ", "x" * 65, "tab\there"])
def test_rename_rejects_unsafe_names(client: TestClient, name: str) -> None:
    response = client.patch("/api/vms/x", headers=AUTH, json={"name": name})
    assert response.status_code == 422


@needs_qemu_img
def test_deletion_plan_respects_every_rule(
    client: TestClient,
    conn: LibvirtConnection,
    define: list[libvirt.virDomain],
    library: Path,
    tmp_path: Path,
) -> None:
    vm_dir = library / "Labs" / "SRV"
    own = qcow2(vm_dir / "SRV.qcow2")
    base = qcow2(library / "Masters" / "base.qcow2")
    clone = qcow2(vm_dir / "SRV-2.qcow2", backing=base)
    shared = touch(library / "shared.raw")
    overlaid = qcow2(vm_dir / "SRV-3.qcow2")
    qcow2(library / "Other" / "overlay.qcow2", backing=overlaid)  # someone else's clone
    outside = touch(tmp_path / "elsewhere" / "disk.raw")
    iso = touch(tmp_path / "iso" / "debian.iso")
    nvram = touch(vm_dir / "SRV_VARS.fd")

    dom = add_domain(
        conn,
        define,
        domain_xml(
            "SRV",
            [
                ("disk", str(own)),
                ("disk", str(clone)),
                ("disk", str(shared)),
                ("disk", str(overlaid)),
                ("disk", str(outside)),
                ("cdrom", str(iso)),
            ],
            nvram=str(nvram),
        ),
    )
    add_domain(conn, define, domain_xml("OTHER", [("disk", str(shared))]))

    plan = client.get(f"/api/vms/{dom.UUIDString()}/deletion-plan", headers=AUTH).json()
    assert sorted(plan["delete"]) == sorted([str(own), str(clone), str(nvram)])
    reasons = {Path(k["path"]).name: k["reason"] for k in plan["keep"]}
    assert reasons == {
        "base.qcow2": "backing",
        "shared.raw": "shared",
        "SRV-3.qcow2": "shared",
        "disk.raw": "outside_library",
        "debian.iso": "iso",
    }


def test_delete_refuses_a_running_vm(client: TestClient, conn: LibvirtConnection) -> None:
    uuid = conn.run(lambda c: c.lookupByName("test").UUIDString())
    response = client.delete(f"/api/vms/{uuid}?files=true", headers=AUTH)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "vm.not_shut_off"


def test_delete_with_files(
    client: TestClient,
    conn: LibvirtConnection,
    define: list[libvirt.virDomain],
    library: Path,
    tmp_path: Path,
) -> None:
    disk = touch(library / "DEL" / "DEL.raw")
    outside = touch(tmp_path / "keep-me.raw")
    dom = add_domain(conn, define, domain_xml("DEL", [("disk", str(disk)), ("disk", str(outside))]))
    uuid = dom.UUIDString()

    result = client.delete(f"/api/vms/{uuid}?files=true", headers=AUTH).json()
    assert result["deleted"] == [str(disk)]
    assert result["failed"] == []
    assert not disk.exists()
    assert outside.exists()
    with pytest.raises(libvirt.libvirtError):
        conn.domain_summary(uuid)


def test_unregister_only_keeps_files(
    client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    disk = touch(library / "KEEP" / "KEEP.raw")
    dom = add_domain(conn, define, domain_xml("KEEP", [("disk", str(disk))]))
    result = client.delete(f"/api/vms/{dom.UUIDString()}", headers=AUTH).json()
    assert result["deleted"] == []
    assert disk.exists()


def test_symlink_escaping_the_library_is_not_deleted(
    client: TestClient,
    conn: LibvirtConnection,
    define: list[libvirt.virDomain],
    library: Path,
    tmp_path: Path,
) -> None:
    target = touch(tmp_path / "precious.raw")
    link = library / "LINK" / "LINK.raw"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    dom = add_domain(conn, define, domain_xml("LINK", [("disk", str(link))]))
    plan = client.get(f"/api/vms/{dom.UUIDString()}/deletion-plan", headers=AUTH).json()
    assert plan["delete"] == []
    assert plan["keep"] == [{"path": str(target), "reason": "outside_library"}]


def test_nothing_is_deleted_without_a_library(
    conn: LibvirtConnection, define: list[libvirt.virDomain], frontend_dir: Path, tmp_path: Path
) -> None:
    disk = touch(tmp_path / "x.raw")
    config = Config(libvirt=LibvirtSettings(uri=TEST_URI))
    app = create_app(config, conn, TOKEN, mode="web", frontend_dir=frontend_dir)
    dom = add_domain(conn, define, domain_xml("NOLIB", [("disk", str(disk))]))
    client = TestClient(app, base_url="http://127.0.0.1")
    plan = client.get(f"/api/vms/{dom.UUIDString()}/deletion-plan", headers=AUTH).json()
    assert plan == {"delete": [], "keep": [{"path": str(disk), "reason": "no_library"}]}
