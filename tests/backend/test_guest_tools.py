from __future__ import annotations

import json
import shutil
import subprocess
import uuid as uuidlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import libvirt
import pytest
from fastapi.testclient import TestClient
from lxml import etree

from kvmstudio.config import Config
from kvmstudio.guesttools import tools
from kvmstudio.services.library import metadata_values

from .helpers import AUTH, touch

needs_xorriso = pytest.mark.skipif(shutil.which("xorriso") is None, reason="needs xorriso")


def test_family_guesses() -> None:
    ours = (
        "<domain><metadata><kvmstudio:vm xmlns:kvmstudio="
        "'https://github.com/rm-networks/kvm-studio/ns/1.0'><kvmstudio:profile>windows11"
        "</kvmstudio:profile></kvmstudio:vm></metadata></domain>"
    )
    assert tools.guess_family(ours) == "windows"
    virt_manager = (
        "<domain><metadata><libosinfo:libosinfo xmlns:libosinfo="
        "'http://libosinfo.org/xmlns/libvirt/domain/1.0'><libosinfo:os "
        "id='http://debian.org/debian/13'/></libosinfo:libosinfo></metadata></domain>"
    )
    assert tools.guess_family(virt_manager) == "linux"
    assert tools.guess_family("<domain/>") is None


def iso_listing(iso: Path) -> str:
    out = subprocess.run(  # noqa: S603
        ["xorriso", "-indev", str(iso), "-pvd_info", "-lsl", "/"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout + out.stderr


@needs_xorriso
def test_linux_cd(tmp_path: Path) -> None:
    iso = tools.build_iso("linux", tmp_path / "Tools" / "linux.iso")
    listing = iso_listing(iso)
    assert "Volume Id    : KS_TOOLS" in listing
    assert "-r-xr-xr-x" in listing
    assert "install.sh" in listing
    # The script reaches every supported package manager.
    script = (tools.FILES / "linux" / "install.sh").read_text()
    for manager in ("apt-get", "dnf", "zypper", "pacman"):
        assert manager in script
    assert "qemu-guest-agent spice-vdagent" in script


@needs_xorriso
def test_windows_cd(tmp_path: Path) -> None:
    listing = iso_listing(tools.build_iso("windows", tmp_path / "windows.iso"))
    assert "autorun.inf" in listing
    assert "Install-Tools.bat" in listing
    bat = (tools.FILES / "windows" / "Install-Tools.bat").read_bytes()
    assert b"\r\n" in bat
    assert b"/quiet /norestart" in bat
    assert b"-Verb RunAs" in bat
    assert b"open=Install-Tools.bat" in (tools.FILES / "windows" / "autorun.inf").read_bytes()


def make_vm(conn: Any, drives: list[str | None], *, start: bool) -> libvirt.virDomain:
    disks = "".join(
        "<disk type='file' device='cdrom'><driver name='qemu' type='raw'/>"
        + (f"<source file='{path}'/>" if path else "")
        + f"<target dev='sd{chr(97 + i)}' bus='sata'/><readonly/></disk>"
        for i, path in enumerate(drives)
    )
    xml = (
        f"<domain type='test'><name>gt-{uuidlib.uuid4().hex[:6]}</name><memory>65536</memory>"
        f"<os><type>hvm</type></os><devices>{disks}</devices></domain>"
    )
    dom: libvirt.virDomain = conn.run(lambda c: c.defineXML(xml))
    if start:
        dom.create()
    return dom


@pytest.fixture
def vms(conn: Any) -> Iterator[list[libvirt.virDomain]]:
    created: list[libvirt.virDomain] = []
    yield created
    for dom in created:
        if dom.isActive():
            dom.destroy()
        dom.undefine()


def media(dom: libvirt.virDomain, flags: int = 0) -> dict[str, str | None]:
    root = etree.fromstring(dom.XMLDesc(flags).encode())
    result: dict[str, str | None] = {}
    for disk in root.iterfind("devices/disk[@device='cdrom']"):
        source = disk.find("source")
        target = disk.find("target")
        assert target is not None
        result[target.get("dev", "")] = source.get("file") if source is not None else None
    return result


@needs_xorriso
def test_linux_insert_and_eject(
    lib_client: TestClient, conn: Any, vms: list[libvirt.virDomain], tmp_path: Path
) -> None:
    previous = touch(tmp_path / "iso" / "debian.iso")
    dom = make_vm(conn, [str(previous)], start=True)
    vms.append(dom)
    url = f"/api/vms/{dom.UUIDString()}/guest-tools"
    result = lib_client.post(url, headers=AUTH, json={"family": "linux"}).json()
    # No agent channel: added to the config, so a restart is due.
    assert result == {"drives": ["sda"], "restart_required": True}
    cd = tmp_path / "data" / "KVM-Studio" / "Tools" / "kvmstudio-tools-linux.iso"
    assert media(dom) == {"sda": str(cd)}
    assert tools.has_agent_channel(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))
    info = lib_client.get(url, headers=AUTH).json()
    assert info["inserted"] is True
    assert "LABEL=KS_TOOLS" in info["linux_command"]
    assert json.loads(metadata_values(dom.XMLDesc(0))["tools_media"]) == {"sda": str(previous)}

    assert lib_client.post(f"{url}/eject", headers=AUTH).json() == {"drives": ["sda"]}
    assert media(dom) == {"sda": str(previous)}
    assert lib_client.get(url, headers=AUTH).json()["inserted"] is False


@needs_xorriso
def test_windows_adds_a_second_drive_for_virtio_win(
    lib_client: TestClient,
    lib_config: Config,
    conn: Any,
    vms: list[libvirt.virDomain],
    tmp_path: Path,
) -> None:
    virtio = touch(tmp_path / "iso" / "drivers" / "virtio-win.iso")
    lib_config.defaults.virtio_win_iso = virtio
    dom = make_vm(conn, [None], start=False)
    vms.append(dom)
    url = f"/api/vms/{dom.UUIDString()}/guest-tools"
    result = lib_client.post(url, headers=AUTH, json={"family": "windows"}).json()
    assert result == {"drives": ["sda", "sdb"], "restart_required": False}
    cd = tmp_path / "data" / "KVM-Studio" / "Tools" / "kvmstudio-tools-windows.iso"
    assert media(dom) == {"sda": str(cd), "sdb": str(virtio)}
    lib_client.post(f"{url}/eject", headers=AUTH)
    # The added drive stays, empty.
    assert media(dom) == {"sda": None, "sdb": None}


def test_windows_needs_the_virtio_iso(
    lib_client: TestClient, conn: Any, vms: list[libvirt.virDomain]
) -> None:
    dom = make_vm(conn, [None], start=False)
    vms.append(dom)
    response = lib_client.post(
        f"/api/vms/{dom.UUIDString()}/guest-tools", headers=AUTH, json={"family": "windows"}
    )
    assert response.json()["error"]["code"] == "guest.no_virtio_iso"


def test_unsupported_family(
    lib_client: TestClient, conn: Any, vms: list[libvirt.virDomain]
) -> None:
    dom = make_vm(conn, [None], start=False)
    vms.append(dom)
    response = lib_client.post(
        f"/api/vms/{dom.UUIDString()}/guest-tools", headers=AUTH, json={"family": "bsd"}
    )
    assert response.json()["error"]["code"] == "guest.unsupported"


def test_agent_status_without_agent(lib_client: TestClient, conn: Any) -> None:
    uuid = conn.run(lambda c: c.lookupByName("test").UUIDString())
    assert lib_client.get(f"/api/vms/{uuid}/agent", headers=AUTH).json() == {"responding": False}
