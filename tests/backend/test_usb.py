"""USB storage of the host: listing from a fake sysfs, connection checks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import libvirt
import pytest
from fastapi.testclient import TestClient
from lxml import etree

from kvmstudio.services import usb

from .helpers import AUTH

PCI = "devices/pci0000:00/0000:00:14.0"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n")


def _usb_device(sys: Path, port: str, busnum: int, devnum: int, cls: str, product: str) -> Path:
    dev = sys / PCI / f"usb{busnum}" / port
    for name, value in (
        ("busnum", str(busnum)),
        ("devnum", str(devnum)),
        ("idVendor", "0781"),
        ("idProduct", "556b"),
        ("manufacturer", "SanDisk"),
        ("product", product),
    ):
        _write(dev / name, value)
    _write(dev / f"{port}:1.0" / "bInterfaceClass", cls)
    links = sys / "bus" / "usb" / "devices"
    links.mkdir(parents=True, exist_ok=True)
    os.symlink(dev, links / port)
    return dev


def _disk(sys: Path, parent: Path, name: str, dev: str, sectors: int, parts: int = 0) -> Path:
    block = parent / "block" / name
    _write(block / "dev", dev)
    _write(block / "size", str(sectors))
    (block / "holders").mkdir(parents=True, exist_ok=True)
    for i in range(1, parts + 1):
        part = block / f"{name}{i}"
        _write(part / "partition", str(i))
        major, minor = dev.split(":")
        _write(part / "dev", f"{major}:{int(minor) + i}")
        (part / "holders").mkdir(parents=True, exist_ok=True)
    links = sys / "class" / "block"
    links.mkdir(parents=True, exist_ok=True)
    os.symlink(block, links / name)
    for i in range(1, parts + 1):
        os.symlink(block / f"{name}{i}", links / f"{name}{i}")
    return block


@pytest.fixture
def host(tmp_path: Path) -> tuple[Path, Path, Path]:
    sys = tmp_path / "sys"
    key = _usb_device(sys, "2-2", 2, 11, "08", "Cruzer Edge")
    _disk(sys, key / "2-2:1.0" / "host6" / "target6:0:0" / "6:0:0:0", "sdc", "8:32", 62521344, 1)
    _usb_device(sys, "2-6", 2, 4, "03", "Keyboard")  # HID, never listed
    # An internal SATA disk, removable or not, is not on the USB bus.
    _disk(sys, sys / PCI / "ata1" / "host0" / "target0:0:0" / "0:0:0:0", "sda", "8:0", 1000, 2)
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "36 1 8:2 / / rw - ext4 /dev/sda2 rw\n"
        "90 36 8:33 / /run/media/romain/USB\\040DISK rw - vfat /dev/sdc1 rw\n"
    )
    swaps = tmp_path / "swaps"
    swaps.write_text("Filename Type Size Used Priority\n")
    return sys, mountinfo, swaps


def test_lists_usb_storage_only(host: tuple[Path, Path, Path]) -> None:
    sys, mountinfo, swaps = host
    found = usb.host_devices(sys, mountinfo, swaps)
    assert len(found) == 1
    key = found[0]
    assert (key.bus, key.device, key.name, key.disks) == (2, 11, "SanDisk Cruzer Edge", ["sdc"])
    assert key.size == 62521344 * 512
    assert key.mountpoints == ["/run/media/romain/USB DISK"]


def test_swap_and_device_mapper_count_as_in_use(host: tuple[Path, Path, Path]) -> None:
    sys, mountinfo, swaps = host
    mountinfo.write_text("")
    swaps.write_text("Filename Type Size Used Priority\n/dev/sdc1 partition 100 0 -2\n")
    (sys / "class" / "block" / "sdc" / "sdc1" / "holders" / "dm-0").mkdir()
    key = usb.host_devices(sys, mountinfo, swaps)[0]
    assert key.mountpoints == []
    assert key.in_use == ["swap (sdc1)", "dm-0"]


def _key(**overrides: Any) -> usb.UsbStorage:
    values: dict[str, Any] = {
        "bus": 2,
        "device": 11,
        "vendor_id": "0781",
        "product_id": "556b",
        "name": "SanDisk Cruzer Edge",
        "size": 32 * 1000**3,
    }
    return usb.UsbStorage(**{**values, **overrides})


@pytest.fixture
def running(conn: Any) -> Any:
    xml = (
        "<domain type='test'><name>usb-vm</name><memory unit='MiB'>64</memory>"
        "<os><type>hvm</type></os><devices/></domain>"
    )
    dom = conn.run(lambda c: c.defineXML(xml))
    dom.create()
    yield dom
    if dom.isActive():
        dom.destroy()
    dom.undefine()


def test_mounted_device_is_refused_with_its_mount_point(
    lib_client: TestClient, running: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(usb, "host_devices", lambda: [_key(mountpoints=["/run/media/r/USB"])])
    r = lib_client.post(
        f"/api/vms/{running.UUIDString()}/usb", headers=AUTH, json={"bus": 2, "device": 11}
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "usb.mounted"
    assert "/run/media/r/USB" in r.json()["error"]["detail"]
    other = lib_client.post(
        f"/api/vms/{running.UUIDString()}/usb", headers=AUTH, json={"bus": 1, "device": 2}
    )
    assert other.status_code == 404


def test_connects_live_with_a_usb_controller(
    lib_client: TestClient, running: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(usb, "host_devices", lambda: [_key()])
    attached: list[str] = []

    def attach(_dom: Any, xml: str, _flags: int) -> int:
        attached.append(xml)
        return 0

    monkeypatch.setattr(libvirt.virDomain, "attachDeviceFlags", attach)
    uuid = running.UUIDString()
    r = lib_client.post(f"/api/vms/{uuid}/usb", headers=AUTH, json={"bus": 2, "device": 11})
    assert r.status_code == 200
    controller, hostdev = (etree.fromstring(x) for x in attached)
    assert (controller.get("type"), controller.get("model")) == ("usb", "qemu-xhci")
    assert hostdev.find("source/address").attrib == {"bus": "2", "device": "11"}  # type: ignore[union-attr]
    # The controller stays in the config; the device does not (live only).
    config = etree.fromstring(running.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE).encode())
    assert config.find("devices/controller[@type='usb']") is not None
    assert config.find("devices/hostdev") is None


def test_powered_off_vm_is_refused(
    lib_client: TestClient, running: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(usb, "host_devices", lambda: [_key()])
    running.destroy()
    r = lib_client.post(
        f"/api/vms/{running.UUIDString()}/usb", headers=AUTH, json={"bus": 2, "device": 11}
    )
    assert r.json()["error"]["code"] == "usb.vm_off"


def test_disconnect_of_a_device_not_connected(
    lib_client: TestClient, running: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(usb, "host_devices", lambda: [_key()])
    r = lib_client.delete(f"/api/vms/{running.UUIDString()}/usb/2/11", headers=AUTH)
    assert r.status_code == 404
