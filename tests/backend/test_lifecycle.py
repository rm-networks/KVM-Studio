from __future__ import annotations

import uuid as uuidlib
from pathlib import Path

import libvirt
import pytest
from fastapi.testclient import TestClient

from kvmstudio.app import create_app
from kvmstudio.config import Config, LibvirtSettings
from kvmstudio.libvirt_conn import LibvirtConnection

from .conftest import TEST_URI, TOKEN
from .helpers import AUTH, add_domain, domain_xml, needs_qemu_img, qcow2, touch


def test_power_cycle_of_the_test_domain(lib_client: TestClient, conn: LibvirtConnection) -> None:
    uuid = conn.run(lambda c: c.lookupByName("test").UUIDString())
    try:
        assert lib_client.post(f"/api/vms/{uuid}/power/poweroff", headers=AUTH).status_code == 204
        assert conn.domain_summary(uuid).state == "shutoff"
        response = lib_client.post(f"/api/vms/{uuid}/power/shutdown", headers=AUTH)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "libvirt.invalid_state"
        assert lib_client.post(f"/api/vms/{uuid}/power/start", headers=AUTH).status_code == 204
        assert conn.domain_summary(uuid).state == "running"
        assert lib_client.post(f"/api/vms/{uuid}/power/reboot", headers=AUTH).status_code == 204
        assert lib_client.post(f"/api/vms/{uuid}/power/reset", headers=AUTH).status_code == 204
    finally:
        dom = conn.run(lambda c: c.lookupByUUIDString(uuid))
        if not dom.isActive():
            dom.create()


def test_unknown_power_action_is_rejected(lib_client: TestClient) -> None:
    response = lib_client.post("/api/vms/x/power/explode", headers=AUTH)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request.invalid"


def test_unknown_vm_is_a_404(lib_client: TestClient) -> None:
    response = lib_client.post(f"/api/vms/{uuidlib.uuid4()}/power/start", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "libvirt.no_domain"


def test_rename(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain]
) -> None:
    dom = add_domain(conn, define, domain_xml("old-name", []))
    uuid = dom.UUIDString()
    response = lib_client.patch(f"/api/vms/{uuid}", headers=AUTH, json={"name": "Nouveau nom 2"})
    assert response.status_code == 204
    assert conn.domain_summary(uuid).name == "Nouveau nom 2"


@pytest.mark.parametrize("name", ["", "a/b", ".hidden", "trailing ", "x" * 65, "tab\there"])
def test_rename_rejects_unsafe_names(lib_client: TestClient, name: str) -> None:
    response = lib_client.patch("/api/vms/x", headers=AUTH, json={"name": name})
    assert response.status_code == 422


@needs_qemu_img
def test_deletion_plan_respects_every_rule(
    lib_client: TestClient,
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

    plan = lib_client.get(f"/api/vms/{dom.UUIDString()}/deletion-plan", headers=AUTH).json()
    assert sorted(plan["delete"]) == sorted([str(own), str(clone), str(nvram)])
    reasons = {Path(k["path"]).name: k["reason"] for k in plan["keep"]}
    assert reasons == {
        "base.qcow2": "backing",
        "shared.raw": "shared",
        "SRV-3.qcow2": "shared",
        "disk.raw": "outside_library",
        "debian.iso": "iso",
    }


def test_delete_refuses_a_running_vm(lib_client: TestClient, conn: LibvirtConnection) -> None:
    uuid = conn.run(lambda c: c.lookupByName("test").UUIDString())
    response = lib_client.delete(f"/api/vms/{uuid}?files=true", headers=AUTH)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "vm.not_shut_off"


def test_delete_with_files(
    lib_client: TestClient,
    conn: LibvirtConnection,
    define: list[libvirt.virDomain],
    library: Path,
    tmp_path: Path,
) -> None:
    disk = touch(library / "DEL" / "DEL.raw")
    outside = touch(tmp_path / "keep-me.raw")
    dom = add_domain(conn, define, domain_xml("DEL", [("disk", str(disk)), ("disk", str(outside))]))
    uuid = dom.UUIDString()

    result = lib_client.delete(f"/api/vms/{uuid}?files=true", headers=AUTH).json()
    assert result["deleted"] == [str(disk)]
    assert result["failed"] == []
    assert not disk.exists()
    assert outside.exists()
    with pytest.raises(libvirt.libvirtError):
        conn.domain_summary(uuid)


def test_unregister_only_keeps_files(
    lib_client: TestClient, conn: LibvirtConnection, define: list[libvirt.virDomain], library: Path
) -> None:
    disk = touch(library / "KEEP" / "KEEP.raw")
    dom = add_domain(conn, define, domain_xml("KEEP", [("disk", str(disk))]))
    result = lib_client.delete(f"/api/vms/{dom.UUIDString()}", headers=AUTH).json()
    assert result["deleted"] == []
    assert disk.exists()


def test_symlink_escaping_the_library_is_not_deleted(
    lib_client: TestClient,
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
    plan = lib_client.get(f"/api/vms/{dom.UUIDString()}/deletion-plan", headers=AUTH).json()
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
