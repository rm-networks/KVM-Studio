from __future__ import annotations

import shutil
import subprocess
import uuid as uuidlib
from pathlib import Path
from typing import Any

import libvirt
import pytest
from fastapi.testclient import TestClient
from lxml import etree

from kvmstudio.services import create as create_module
from kvmstudio.services.create import nic_target
from kvmstudio.services.library import metadata_folder
from kvmstudio.xml.domain import DiskSpec, DomainSpec, NicSpec, build_domain
from kvmstudio.xml.profiles import PROFILES, guess_profile

from .helpers import AUTH, needs_qemu_img, touch

VALIDATOR = shutil.which("virt-xml-validate")


def windows11_xml(tmp_path: Path) -> str:
    uuid = str(uuidlib.uuid4())
    return build_domain(
        DomainSpec(
            name="WIN11",
            uuid=uuid,
            profile=PROFILES["windows11"],
            memory_mib=4096,
            vcpus=2,
            disks=[DiskSpec(tmp_path / "WIN11.qcow2", "qcow2", "sata")],
            iso=tmp_path / "Win11.iso",
            nics=[NicSpec("kvmnet8", "e1000e", nic_target(uuid, 0))],
            uefi=True,
            secure_boot=True,
            tpm=True,
            nvram=tmp_path / "WIN11_VARS.fd",
            folder="Labs",
        )
    )


def test_profile_guesses() -> None:
    assert guess_profile("Win11_24H2_French_x64.iso") == "windows11"
    assert guess_profile("SW_DVD9_Win_Server_STD_CORE_2025.iso") == "windows-server"
    assert guess_profile("ubuntu-24.04.1-live-server-amd64.iso") == "linux"
    assert guess_profile("OPNsense-25.7-dvd-amd64.iso") == "firewall"
    assert guess_profile("proxmox-ve_8.4-1.iso") == "nested"
    assert guess_profile("mystery.iso") == "other"


def test_windows11_xml(tmp_path: Path) -> None:
    root = etree.fromstring(windows11_xml(tmp_path).encode())
    os_el = root.find("os")
    assert os_el is not None
    assert os_el.get("firmware") == "efi"
    assert os_el.find("loader").get("secure") == "yes"  # type: ignore[union-attr]
    assert os_el.findtext("nvram") == str(tmp_path / "WIN11_VARS.fd")
    assert root.find("features/smm").get("state") == "on"  # type: ignore[union-attr]
    assert root.find("features/hyperv") is not None
    assert root.find("devices/tpm/backend").get("version") == "2.0"  # type: ignore[union-attr]
    assert root.find("clock").get("offset") == "localtime"  # type: ignore[union-attr]
    disk, cdrom = root.findall("devices/disk")
    assert disk.find("target").attrib == {"dev": "sda", "bus": "sata"}  # type: ignore[union-attr]
    assert cdrom.find("target").attrib == {"dev": "sdb", "bus": "sata"}  # type: ignore[union-attr]
    assert cdrom.find("source").get("file") == str(tmp_path / "Win11.iso")  # type: ignore[union-attr]
    nic = root.find("devices/interface")
    assert nic is not None
    target = nic.find("target").get("dev")  # type: ignore[union-attr]
    assert target is not None
    assert target.startswith("ks-")
    assert len(target) <= 15
    assert root.find("devices/graphics/listen").get("type") == "none"  # type: ignore[union-attr]
    assert root.find("devices/channel[@type='qemu-vdagent']") is not None
    assert metadata_folder(etree.tostring(root).decode()) == "Labs"


def test_firewall_xml_has_three_nics_and_a_serial_console(tmp_path: Path) -> None:
    uuid = str(uuidlib.uuid4())
    xml = build_domain(
        DomainSpec(
            name="FW",
            uuid=uuid,
            profile=PROFILES["firewall"],
            memory_mib=2048,
            vcpus=2,
            disks=[DiskSpec(tmp_path / "FW.qcow2", "qcow2", "virtio")],
            iso=None,
            nics=[NicSpec(n, "virtio", nic_target(uuid, i)) for i, n in enumerate(["a", "b", "c"])],
            uefi=False,
            secure_boot=False,
            tpm=False,
            nvram=None,
            folder="",
        )
    )
    root = etree.fromstring(xml.encode())
    assert [n.find("target").get("dev")[-1] for n in root.findall("devices/interface")] == [  # type: ignore[union-attr,index]
        "0",
        "1",
        "2",
    ]
    assert root.find("devices/serial") is not None
    assert root.find("devices/console/target").get("type") == "serial"  # type: ignore[union-attr]
    assert root.find("devices/disk/target").get("dev") == "vda"  # type: ignore[union-attr]
    assert root.find("os").get("firmware") is None  # type: ignore[union-attr]


@pytest.mark.skipif(VALIDATOR is None, reason="needs virt-xml-validate")
@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_xml_follows_the_libvirt_schema(tmp_path: Path, profile: str) -> None:
    """What virt-manager and virsh accept (rule 2)."""
    p = PROFILES[profile]
    uuid = str(uuidlib.uuid4())
    xml = build_domain(
        DomainSpec(
            name="VM",
            uuid=uuid,
            profile=p,
            memory_mib=p.memory_mib,
            vcpus=p.vcpus,
            disks=[DiskSpec(tmp_path / "VM.qcow2", "qcow2", p.disk_bus)],
            iso=tmp_path / "x.iso",
            nics=[NicSpec("kvmnet8", p.nic_model, nic_target(uuid, i)) for i in range(p.nics)],
            uefi=p.uefi,
            secure_boot=p.secure_boot,
            tpm=p.tpm,
            nvram=tmp_path / "VM_VARS.fd" if p.uefi else None,
            folder="Labs",
        )
    )
    path = tmp_path / "domain.xml"
    path.write_text(xml)
    assert VALIDATOR is not None
    result = subprocess.run(  # noqa: S603
        [VALIDATOR, str(path), "domain"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


# Creating through the API (test driver: BIOS only, no firmware selection)


def new_vm(**extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "SRV-WS22",
        "folder": "Labs",
        "profile": "linux",
        "disk_gib": 1,
        "disk_bus": "virtio",
        "disk_format": "qcow2",
        "memory_mib": 1024,
        "vcpus": 1,
        "nics": [{"network": "default", "model": "virtio"}],
        "uefi": False,
    }
    body.update(extra)
    return body


@pytest.fixture
def labs(library: Path) -> Path:
    (library / "Labs").mkdir()
    return library / "Labs"


@pytest.fixture
def cleanup_domains(conn: Any) -> Any:
    yield

    def op(c: libvirt.virConnect) -> None:
        for dom in c.listAllDomains():
            if dom.name() in {"SRV-WS22", "FW-OPN"}:
                if dom.isActive():
                    dom.destroy()
                dom.undefine()

    conn.run(op)


@needs_qemu_img
def test_create_vm(lib_client: TestClient, conn: Any, labs: Path, cleanup_domains: None) -> None:
    response = lib_client.post("/api/vms", headers=AUTH, json=new_vm(start=True))
    assert response.status_code == 201
    uuid = response.json()["uuid"]
    disk = labs / "SRV-WS22" / "SRV-WS22.qcow2"
    assert disk.exists()
    dom = conn.run(lambda c: c.lookupByUUIDString(uuid))
    assert dom.isActive()
    xml = dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)
    assert str(disk) in xml
    assert nic_target(uuid, 0) in xml
    vm = next(v for v in lib_client.get("/api/vms", headers=AUTH).json() if v["uuid"] == uuid)
    assert (vm["folder"], vm["managed"]) == ("Labs", True)


@needs_qemu_img
def test_preallocated_raw_disk(lib_client: TestClient, labs: Path, cleanup_domains: None) -> None:
    body = new_vm(disk_format="raw", preallocate=True)
    assert lib_client.post("/api/vms", headers=AUTH, json=body).status_code == 201
    disk = labs / "SRV-WS22" / "SRV-WS22.raw"
    assert disk.stat().st_blocks * 512 >= 1024**3  # space really reserved


@needs_qemu_img
@pytest.mark.parametrize(
    ("extra", "status", "code"),
    [
        ({"name": "bad/name"}, 422, "vm.bad_name"),
        ({"folder": "Nowhere"}, 404, "library.no_folder"),
        ({"nics": [{"network": "nope", "model": "virtio"}]}, 404, "libvirt.no_network"),
        ({"profile": "amiga"}, 422, "vm.bad_profile"),
        ({"secure_boot": True}, 422, "vm.secure_boot_needs_uefi"),
        ({"name": "test"}, 409, "vm.exists"),
    ],
)
def test_create_is_validated(
    lib_client: TestClient, labs: Path, extra: dict[str, Any], status: int, code: str
) -> None:
    response = lib_client.post("/api/vms", headers=AUTH, json=new_vm(**extra))
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert list(labs.iterdir()) == []


@needs_qemu_img
def test_iso_must_come_from_a_library(
    lib_client: TestClient, labs: Path, tmp_path: Path, cleanup_domains: None
) -> None:
    rogue = touch(tmp_path / "rogue.iso")
    response = lib_client.post("/api/vms", headers=AUTH, json=new_vm(iso=str(rogue)))
    assert response.status_code == 403
    iso = touch(tmp_path / "iso" / "debian.iso")
    assert lib_client.post("/api/vms", headers=AUTH, json=new_vm(iso=str(iso))).status_code == 201


@needs_qemu_img
def test_failed_definition_leaves_nothing_behind(
    lib_client: TestClient, labs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    monkeypatch.setattr(create_module, "build_domain", lambda _spec: "<domain/>")
    response = lib_client.post("/api/vms", headers=AUTH, json=new_vm())
    assert response.status_code >= 400
    assert not (labs / "SRV-WS22").exists()


def test_profiles_and_host_endpoints(lib_client: TestClient) -> None:
    profiles = {p["id"]: p for p in lib_client.get("/api/profiles", headers=AUTH).json()}
    assert profiles["windows11"]["tpm"] is True
    assert profiles["firewall"]["nics"] == 3
    host = lib_client.get("/api/host", headers=AUTH).json()
    assert host["cpus"] >= 1
    assert "virtio" in host["disk_buses"]
    guess = lib_client.get("/api/profiles/guess?iso=/srv/iso/Win11.iso", headers=AUTH).json()
    assert guess == {"profile": "windows11"}


@pytest.mark.parametrize(("vendor", "flag"), [("intel", "vmx"), ("amd", "svm"), (None, None)])
def test_nested_profile_asks_for_the_host_extension(
    tmp_path: Path, vendor: str | None, flag: str | None
) -> None:
    xml = build_domain(
        DomainSpec(
            name="ESX",
            uuid=str(uuidlib.uuid4()),
            profile=PROFILES["nested"],
            memory_mib=8192,
            vcpus=4,
            disks=[],
            iso=None,
            nics=[],
            uefi=False,
            secure_boot=False,
            tpm=False,
            nvram=None,
            folder="",
            machine="pc-q35-10.2",
            cpu_vendor=vendor,
        )
    )
    root = etree.fromstring(xml.encode())
    assert root.find("os/type").get("machine") == "pc-q35-10.2"  # type: ignore[union-attr]
    assert [f.get("name") for f in root.iterfind("cpu/feature")] == ([flag] if flag else [])


def test_machine_type_is_the_versioned_name() -> None:
    class Conn:
        def __init__(self, xml: str) -> None:
            self.xml = xml

        def run(self, op: Any) -> str:
            return self.xml

    caps = "<domainCapabilities><machine>pc-q35-10.2</machine></domainCapabilities>"
    assert create_module.machine_type(Conn(caps)) == "pc-q35-10.2"  # type: ignore[arg-type]
    assert create_module.machine_type(Conn("<domainCapabilities/>")) == "q35"  # type: ignore[arg-type]
