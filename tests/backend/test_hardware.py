from __future__ import annotations

import uuid as uuidlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import libvirt
import pytest
from fastapi.testclient import TestClient
from lxml import etree

from kvmstudio.services.create import nic_target

from .helpers import AUTH, touch


@pytest.fixture
def vm(conn: Any) -> Iterator[libvirt.virDomain]:
    uuid = str(uuidlib.uuid4())
    xml = (
        f"<domain type='test'><name>hw-{uuid[:6]}</name><uuid>{uuid}</uuid>"
        "<memory unit='MiB'>2048</memory><vcpu>2</vcpu><os><type>hvm</type></os><devices>"
        "<disk type='file' device='disk'><driver name='qemu' type='qcow2'/>"
        "<source file='/x/disk.qcow2'/><target dev='vda' bus='virtio'/></disk>"
        "<disk type='file' device='cdrom'><target dev='sda' bus='sata'/><readonly/></disk>"
        "<interface type='network'><mac address='52:54:00:aa:bb:cc'/>"
        f"<source network='default'/><model type='virtio'/><target dev='{nic_target(uuid, 0)}'/>"
        "</interface></devices></domain>"
    )
    dom = conn.run(lambda c: c.defineXML(xml))
    yield dom
    dom.undefine()


def config_root(dom: libvirt.virDomain) -> etree._Element:
    return etree.fromstring(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE).encode())


def test_read_hardware(lib_client: TestClient, vm: libvirt.virDomain) -> None:
    hw: dict[str, Any] = lib_client.get(f"/api/vms/{vm.UUIDString()}/hardware", headers=AUTH).json()
    assert (hw["memory_mib"], hw["vcpus"], hw["active"]) == (2048, 2, False)
    assert hw["disks"] == [
        {"target": "vda", "bus": "virtio", "path": "/x/disk.qcow2", "format": "qcow2"}
    ]
    assert hw["cdroms"][0]["target"] == "sda"
    assert hw["nics"][0]["mac"] == "52:54:00:aa:bb:cc"
    assert hw["nics"][0]["connected"] is True


def test_memory_and_processors(lib_client: TestClient, vm: libvirt.virDomain) -> None:
    body = {"memory_mib": 4096, "vcpus": 4}
    result = lib_client.put(
        f"/api/vms/{vm.UUIDString()}/hardware/cpu-memory", headers=AUTH, json=body
    )
    assert result.json() == {"restart_required": False}
    hw = lib_client.get(f"/api/vms/{vm.UUIDString()}/hardware", headers=AUTH).json()
    assert (hw["memory_mib"], hw["vcpus"]) == (4096, 4)


def test_network_cards(lib_client: TestClient, vm: libvirt.virDomain) -> None:
    uuid = vm.UUIDString()
    created = lib_client.post(
        f"/api/vms/{uuid}/nics", headers=AUTH, json={"network": "default", "model": "e1000e"}
    ).json()
    assert created["mac"].startswith("52:54:00:")
    assert created["target"] == nic_target(uuid, 1)
    assert len(config_root(vm).findall("devices/interface")) == 2

    change = {"model": "rtl8139", "connected": False}
    response = lib_client.patch(f"/api/vms/{uuid}/nics/{created['mac']}", headers=AUTH, json=change)
    assert response.json() == {"restart_required": False}
    iface = next(
        i
        for i in config_root(vm).iterfind("devices/interface")
        if i.find("mac").get("address") == created["mac"]  # type: ignore[union-attr]
    )
    assert iface.find("model").get("type") == "rtl8139"  # type: ignore[union-attr]
    assert iface.find("link").get("state") == "down"  # type: ignore[union-attr]

    assert (
        lib_client.delete(f"/api/vms/{uuid}/nics/52:54:00:aa:bb:cc", headers=AUTH).status_code
        == 204
    )
    macs = [m.get("address") for m in config_root(vm).iterfind("devices/interface/mac")]
    assert macs == [created["mac"]]


def test_network_card_errors(lib_client: TestClient, vm: libvirt.virDomain) -> None:
    uuid = vm.UUIDString()
    missing = lib_client.post(f"/api/vms/{uuid}/nics", headers=AUTH, json={"network": "nope"})
    assert missing.status_code == 404
    unknown = lib_client.delete(f"/api/vms/{uuid}/nics/52:54:00:00:00:00", headers=AUTH)
    assert unknown.json()["error"]["code"] == "vm.no_nic"
    bad_model = lib_client.patch(
        f"/api/vms/{uuid}/nics/52:54:00:aa:bb:cc", headers=AUTH, json={"model": "ne2000"}
    )
    assert bad_model.status_code == 422


def test_cd_dvd_drives(lib_client: TestClient, vm: libvirt.virDomain, tmp_path: Path) -> None:
    uuid = vm.UUIDString()
    iso = touch(tmp_path / "iso" / "tools.iso")
    response = lib_client.post(f"/api/vms/{uuid}/cdroms", headers=AUTH, json={"path": str(iso)})
    assert response.json() == {"restart_required": False}
    drives = lib_client.get(f"/api/vms/{uuid}/hardware", headers=AUTH).json()["cdroms"]
    assert [(d["target"], d["path"]) for d in drives] == [("sda", None), ("sdb", str(iso))]
    rogue = touch(tmp_path / "rogue.iso")
    refused = lib_client.post(f"/api/vms/{uuid}/cdroms", headers=AUTH, json={"path": str(rogue)})
    assert refused.status_code == 403
    assert lib_client.delete(f"/api/vms/{uuid}/cdroms/sdb", headers=AUTH).status_code == 200
    assert lib_client.delete(f"/api/vms/{uuid}/cdroms/sdz", headers=AUTH).status_code == 404


def test_notes_in_the_description(lib_client: TestClient, vm: libvirt.virDomain) -> None:
    uuid = vm.UUIDString()
    put = lib_client.put(f"/api/vms/{uuid}/notes", headers=AUTH, json={"notes": "Lab <DNS> & DHCP"})
    assert put.status_code == 204
    assert config_root(vm).findtext("description") == "Lab <DNS> & DHCP"
    listed = lib_client.get("/api/vms", headers=AUTH).json()
    assert next(v for v in listed if v["uuid"] == uuid)["notes"] == "Lab <DNS> & DHCP"
    vm.create()
    try:
        lib_client.put(f"/api/vms/{uuid}/notes", headers=AUTH, json={"notes": "live"})
        assert etree.fromstring(vm.XMLDesc(0).encode()).findtext("description") == "live"
    finally:
        vm.destroy()
    lib_client.put(f"/api/vms/{uuid}/notes", headers=AUTH, json={"notes": ""})
    assert config_root(vm).find("description") is None
    too_long = {"notes": "x" * 10001}
    assert lib_client.put(f"/api/vms/{uuid}/notes", headers=AUTH, json=too_long).status_code == 422


def test_new_mac_address(lib_client: TestClient, vm: libvirt.virDomain, conn: Any) -> None:
    uuid = vm.UUIDString()
    url = f"/api/vms/{uuid}/nics/52:54:00:aa:bb:cc/new-mac"
    mac = lib_client.post(url, headers=AUTH).json()["mac"]
    assert mac.startswith("52:54:00:")
    assert mac != "52:54:00:aa:bb:cc"
    assert config_root(vm).find("devices/interface/mac").get("address") == mac  # type: ignore[union-attr]
    vm.create()
    try:
        running = lib_client.post(f"/api/vms/{uuid}/nics/{mac}/new-mac", headers=AUTH)
        assert running.status_code == 409
    finally:
        vm.destroy()
    missing = lib_client.post(f"/api/vms/{uuid}/nics/52:54:00:00:00:01/new-mac", headers=AUTH)
    assert missing.status_code == 404


def test_new_mac_skips_addresses_in_use(monkeypatch: pytest.MonkeyPatch) -> None:
    from kvmstudio.services import hardware

    draws = iter([0xAA, 0xBB, 0xCC, 0x01, 0x02, 0x03])
    monkeypatch.setattr("random.randint", lambda _a, _b: next(draws))
    assert hardware._new_mac({"52:54:00:aa:bb:cc"}) == "52:54:00:01:02:03"
