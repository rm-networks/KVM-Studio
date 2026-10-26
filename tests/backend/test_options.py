from __future__ import annotations

import uuid as uuidlib
from collections.abc import Iterator
from typing import Any

import libvirt
import pytest
from fastapi.testclient import TestClient
from lxml import etree

from kvmstudio.services import options
from kvmstudio.services.library import metadata_values

from .helpers import AUTH

DEVICES = (
    "<disk type='file' device='disk'><driver name='qemu' type='qcow2'/>"
    "<source file='/x/disk.qcow2'/><target dev='vda' bus='virtio'/></disk>"
    "<disk type='file' device='cdrom'><source file='/iso/setup.iso'/>"
    "<target dev='sda' bus='sata'/><readonly/></disk>"
    "<interface type='network'><mac address='52:54:00:aa:bb:cc'/>"
    "<source network='default'/><model type='virtio'/></interface>"
    "<channel type='qemu-vdagent'><source><clipboard copypaste='yes'/></source>"
    "<target type='virtio' name='com.redhat.spice.0'/></channel>"
)


def domain_xml(uuid: str, os_inner: str, devices: str = DEVICES, extra: str = "") -> str:
    return (
        f"<domain type='test'><name>opt-{uuid[:6]}</name><uuid>{uuid}</uuid>"
        "<metadata><kvmstudio:vm xmlns:kvmstudio='https://github.com/rm-networks/kvm-studio/ns/1.0'>"
        "<kvmstudio:folder></kvmstudio:folder><kvmstudio:profile>linux</kvmstudio:profile>"
        "</kvmstudio:vm></metadata>"
        f"<memory unit='MiB'>1024</memory><vcpu>1</vcpu><os>{os_inner}</os>"
        f"<features><acpi/></features>{extra}<devices>{devices}</devices></domain>"
    )


@pytest.fixture
def vm(conn: Any) -> Iterator[libvirt.virDomain]:
    uuid = str(uuidlib.uuid4())
    xml = domain_xml(
        uuid,
        "<type>hvm</type><boot dev='hd'/><boot dev='cdrom'/>"
        "<bootmenu enable='yes' timeout='3000'/>",
    )
    dom = conn.run(lambda c: c.defineXML(xml))
    yield dom
    dom.undefine()


def config(dom: libvirt.virDomain) -> etree._Element:
    return etree.fromstring(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE).encode())


def node(root: etree._Element, path: str) -> etree._Element:
    found = root.find(path)
    assert found is not None, path
    return found


def attr(root: etree._Element, path: str, name: str) -> str | None:
    return node(root, path).get(name)


def url(dom: libvirt.virDomain) -> str:
    return f"/api/vms/{dom.UUIDString()}/options"


def test_read_options(lib_client: TestClient, vm: libvirt.virDomain) -> None:
    got = lib_client.get(url(vm), headers=AUTH).json()
    assert got["profile"] == "linux"
    assert (got["firmware"], got["secure_boot"], got["tpm"]) == ("bios", False, False)
    assert got["boot_menu"] is True
    assert got["clipboard"] is True
    # <os><boot dev=hd/cdrom>: the first disk, then the first CD; the card is off.
    assert [(b["kind"], b["id"], b["enabled"]) for b in got["boot"]] == [
        ("disk", "vda", True),
        ("cdrom", "sda", True),
        ("nic", "52:54:00:aa:bb:cc", False),
    ]
    assert got["boot"][1]["detail"] == "setup.iso"


def test_boot_order_per_device(lib_client: TestClient, vm: libvirt.virDomain) -> None:
    order = [
        {"kind": "nic", "id": "52:54:00:aa:bb:cc", "enabled": True},
        {"kind": "cdrom", "id": "sda", "enabled": False},
        {"kind": "disk", "id": "vda", "enabled": True},
    ]
    body = {"boot": order, "boot_menu": False}
    assert lib_client.put(url(vm), headers=AUTH, json=body).json() == {"restart_required": False}
    root = config(vm)
    assert root.find("os/boot") is None
    assert attr(root, "devices/interface/boot", "order") == "1"
    assert attr(root, "devices/disk[@device='disk']/boot", "order") == "2"
    assert root.find("devices/disk[@device='cdrom']/boot") is None
    assert attr(root, "os/bootmenu", "enable") == "no"
    got = lib_client.get(url(vm), headers=AUTH).json()
    assert [(b["id"], b["enabled"]) for b in got["boot"]] == [
        ("52:54:00:aa:bb:cc", True),
        ("vda", True),
        ("sda", False),
    ]


def test_boot_order_must_list_every_device(lib_client: TestClient, vm: libvirt.virDomain) -> None:
    body = {"boot": [{"kind": "disk", "id": "vda", "enabled": True}]}
    r = lib_client.put(url(vm), headers=AUTH, json=body)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "options.boot_devices_changed"


def test_power_profile_and_isolation(lib_client: TestClient, vm: libvirt.virDomain) -> None:
    body = {
        "profile": "firewall",
        "autostart": True,
        "on_reboot": "destroy",
        "on_crash": "preserve",
        "clipboard": False,
    }
    lib_client.put(url(vm), headers=AUTH, json=body).raise_for_status()
    root = config(vm)
    assert root.findtext("on_reboot") == "destroy"
    assert root.findtext("on_crash") == "preserve"
    assert attr(root, "devices/channel[@type='qemu-vdagent']/source/clipboard", "copypaste") == "no"
    assert metadata_values(vm.XMLDesc(0))["profile"] == "firewall"
    assert metadata_values(vm.XMLDesc(0))["folder"] == ""
    got = lib_client.get(url(vm), headers=AUTH).json()
    assert (got["autostart"], got["clipboard"]) == (True, False)
    assert lib_client.put(url(vm), headers=AUTH, json={"profile": "dos"}).status_code == 422


def test_firmware_and_tpm(lib_client: TestClient, vm: libvirt.virDomain) -> None:
    body = {"firmware": "uefi", "secure_boot": True, "tpm": True}
    lib_client.put(url(vm), headers=AUTH, json=body).raise_for_status()
    root = config(vm)
    assert attr(root, "os", "firmware") == "efi"
    assert attr(root, "os/firmware/feature[@name='secure-boot']", "enabled") == "yes"
    assert attr(root, "os/loader", "secure") == "yes"
    assert node(root, "os/nvram").text == f"/x/{vm.name()}_VARS.fd"
    assert attr(root, "features/smm", "state") == "on"
    assert attr(root, "devices/tpm/backend", "version") == "2.0"
    assert metadata_values(vm.XMLDesc(0))["reset-nvram"] == "yes"
    assert options.start_flags(vm.XMLDesc(0)) == libvirt.VIR_DOMAIN_START_RESET_NVRAM
    options.started(vm)
    assert options.start_flags(vm.XMLDesc(0)) == 0

    lib_client.put(url(vm), headers=AUTH, json={"firmware": "bios", "tpm": False})
    root = config(vm)
    assert attr(root, "os", "firmware") is None
    assert root.find("os/nvram") is None
    assert root.find("os/loader") is None
    assert root.find("devices/tpm") is None


def test_secure_boot_rebuilds_the_uefi_variables() -> None:
    xml = domain_xml(
        str(uuidlib.uuid4()),
        "<type>hvm</type><firmware><feature enabled='no' name='secure-boot'/></firmware>"
        "<loader readonly='yes' type='pflash'>/usr/share/edk2/ovmf/OVMF_CODE_4M.qcow2</loader>"
        "<nvram template='/usr/share/edk2/ovmf/OVMF_VARS_4M.qcow2' format='qcow2'>/x/v.fd</nvram>",
    ).replace("<os>", "<os firmware='efi'>")
    root = etree.fromstring(xml.encode())
    assert options.read(xml, active=False, autostart=False).firmware == "uefi"
    options._set_uefi(root, True, "/x/other.fd")
    os_el = node(root, "os")
    # The old loader and template go, so libvirt picks the Secure Boot ones.
    assert node(os_el, "loader").text is None
    assert attr(os_el, "nvram", "template") is None
    assert node(os_el, "nvram").text == "/x/v.fd"
    assert [c.tag for c in os_el] == ["type", "firmware", "loader", "nvram"]


def test_installed_vm_needs_a_confirmation(
    lib_client: TestClient, vm: libvirt.virDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(options, "_installed", lambda root: True)
    r = lib_client.put(url(vm), headers=AUTH, json={"firmware": "uefi"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "options.confirm"
    # Adding a TPM is harmless, removing one is not.
    assert lib_client.put(url(vm), headers=AUTH, json={"tpm": True}).status_code == 200
    r = lib_client.put(url(vm), headers=AUTH, json={"tpm": False})
    assert r.json()["error"]["code"] == "options.confirm"
    body = {"firmware": "uefi", "tpm": False, "confirmed": True}
    assert lib_client.put(url(vm), headers=AUTH, json=body).status_code == 200


def test_running_vm(lib_client: TestClient, vm: libvirt.virDomain) -> None:
    vm.create()
    try:
        r = lib_client.put(url(vm), headers=AUTH, json={"tpm": True})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "options.must_be_off"
        r = lib_client.put(url(vm), headers=AUTH, json={"on_crash": "restart"})
        assert r.json() == {"restart_required": True}
        r = lib_client.put(url(vm), headers=AUTH, json={"autostart": True})
        assert r.json() == {"restart_required": False}
    finally:
        vm.destroy()


def test_clipboard_channel_added_when_missing(conn: Any) -> None:
    uuid = str(uuidlib.uuid4())
    xml = domain_xml(uuid, "<type>hvm</type>", devices="")
    root = etree.fromstring(xml.encode())
    options._set_clipboard(root, True)
    assert root.find("devices/channel[@type='qemu-vdagent']") is not None
    assert options.read(etree.tostring(root).decode(), active=False, autostart=False).clipboard


def boot_order(root: etree._Element) -> list[tuple[str, str, bool]]:
    return [(d.kind, d.id, d.enabled) for d in options.boot_devices(root)]


@pytest.fixture
def cd_first(conn: Any) -> Iterator[libvirt.virDomain]:
    uuid = str(uuidlib.uuid4())
    xml = domain_xml(uuid, "<type>hvm</type><boot dev='cdrom'/><boot dev='hd'/>")
    dom = conn.run(lambda c: c.defineXML(xml))
    yield dom
    if dom.isActive():
        dom.destroy()
    dom.undefine()


def test_reboot_after_an_install_puts_the_disk_first(
    conn: Any, cd_first: libvirt.virDomain
) -> None:
    cd_first.create()
    assert options.after_install_reboot(conn, cd_first.UUIDString())
    # The CD stays, second; the VM runs again, now with the disk first.
    assert boot_order(config(cd_first)) == [
        ("disk", "vda", True),
        ("cdrom", "sda", True),
        ("nic", "52:54:00:aa:bb:cc", False),
    ]
    assert cd_first.isActive()
    live = etree.fromstring(cd_first.XMLDesc(0).encode())
    assert boot_order(live)[0] == ("disk", "vda", True)
    assert attr(live, "devices/disk[@device='cdrom']/source", "file") == "/iso/setup.iso"
    # The next reboots change nothing.
    assert not options.after_install_reboot(conn, cd_first.UUIDString())


def test_reboot_leaves_a_disk_first_or_an_empty_cd_alone(conn: Any, vm: libvirt.virDomain) -> None:
    vm.create()
    before = boot_order(config(vm))
    assert not options.after_install_reboot(conn, vm.UUIDString())
    assert boot_order(config(vm)) == before
    vm.destroy()
    empty = etree.fromstring(
        domain_xml(
            "0" * 32,
            "<boot dev='cdrom'/><boot dev='hd'/>",
            DEVICES.replace("<source file='/iso/setup.iso'/>", ""),
        ).encode()
    )
    assert options.disk_before_cd(empty) is None
