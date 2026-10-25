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
from kvmstudio.errors import ApiException
from kvmstudio.guesttools import tools
from kvmstudio.services import hardware
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


def fake_virtio(path: Path, *, installer: bool = True) -> Path:
    """A small ISO laid out like virtio-win (the installer at the root)."""
    content = path.parent / f"{path.stem}-content"
    (content / "guest-agent").mkdir(parents=True)
    if installer:
        (content / tools.WINDOWS_INSTALLER).write_bytes(b"MZ fake installer")
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603
        ["xorriso", "-as", "mkisofs", "-quiet", "-V", "virtio-win", "-J", "-r",  # noqa: S607
         "-o", str(path), str(content)],
        check=True,
        capture_output=True,
    )  # fmt: skip
    shutil.rmtree(content)
    return path


@needs_xorriso
def test_windows_cd(tmp_path: Path) -> None:
    virtio = fake_virtio(tmp_path / "iso" / "virtio-win.iso")
    before = virtio.read_bytes()
    iso = tools.build_iso("windows", tmp_path / "windows.iso", virtio)
    listing = iso_listing(iso)
    assert "Volume Id    : KS_TOOLS" in listing
    for name in ("autorun.inf", "Install-Tools.bat", tools.WINDOWS_INSTALLER):
        assert name in listing
    out = tmp_path / "out.exe"
    subprocess.run(  # noqa: S603
        ["xorriso", "-osirrox", "on", "-indev", str(iso), "-extract",  # noqa: S607
         f"/{tools.WINDOWS_INSTALLER}", str(out)],
        check=True,
        capture_output=True,
    )  # fmt: skip
    assert out.read_bytes() == b"MZ fake installer"
    # The virtio-win ISO is only read.
    assert virtio.read_bytes() == before
    bat = (tools.FILES / "windows" / "Install-Tools.bat").read_bytes()
    assert b"\r\n" in bat
    assert b"/quiet /norestart" in bat
    assert b"-Verb RunAs" in bat
    # Its own drive first, then the other drives.
    assert bat.index(b"%~dp0virtio-win-guest-tools.exe") < bat.index(b"for %%D in")
    assert b"/unattended" in bat
    assert b"open=Install-Tools.bat" in (tools.FILES / "windows" / "autorun.inf").read_bytes()


@needs_xorriso
def test_virtio_iso_without_installer(tmp_path: Path) -> None:
    virtio = fake_virtio(tmp_path / "iso" / "other.iso", installer=False)
    with pytest.raises(ApiException) as exc:
        tools.build_iso("windows", tmp_path / "windows.iso", virtio)
    assert exc.value.code == "guest.no_installer"
    assert not (tmp_path / "windows.iso").exists()


def make_vm(
    conn: Any, drives: list[str | None], *, start: bool, agent: bool = False
) -> libvirt.virDomain:
    disks = "".join(
        "<disk type='file' device='cdrom'><driver name='qemu' type='raw'/>"
        + (f"<source file='{path}'/>" if path else "")
        + f"<target dev='sd{chr(97 + i)}' bus='sata'/><readonly/></disk>"
        for i, path in enumerate(drives)
    )
    channel = (
        f"<channel type='unix'><target type='virtio' name='{tools.AGENT_CHANNEL}'/></channel>"
        if agent
        else ""
    )
    xml = (
        f"<domain type='test'><name>gt-{uuidlib.uuid4().hex[:6]}</name><memory>65536</memory>"
        f"<os><type>hvm</type></os><devices>{disks}{channel}</devices></domain>"
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
    assert result == {"drive": "sda", "restart_required": True, "installer": None}
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


WIN = "win11.iso"
VIRTIO = "drivers/virtio-win.iso"


@needs_xorriso
@pytest.mark.parametrize(
    ("drives", "start", "expected", "restart"),
    [
        # No drive: one is added; on a running VM it appears after a power cycle.
        ([], False, "sda", False),
        ([], True, "sda", True),
        # One drive, empty or still holding the Windows setup ISO.
        ([None], True, "sda", False),
        ([WIN], True, "sda", False),
        ([WIN], False, "sda", False),
        # Two drives: the empty one, the setup ISO stays.
        ([WIN, None], True, "sdb", False),
        # Two drives holding something (virtio-win inserted by hand).
        ([WIN, VIRTIO], True, "sda", False),
    ],
)
def test_windows_uses_one_drive(
    lib_client: TestClient,
    lib_config: Config,
    conn: Any,
    vms: list[libvirt.virDomain],
    tmp_path: Path,
    drives: list[str | None],
    start: bool,
    expected: str,
    restart: bool,
) -> None:
    iso = tmp_path / "iso"
    virtio = fake_virtio(iso / VIRTIO)
    touch(iso / WIN)
    lib_config.defaults.virtio_win_iso = virtio
    paths = [str(iso / d) if d else None for d in drives]
    dom = make_vm(conn, paths, start=start, agent=True)
    vms.append(dom)
    before = media(dom, libvirt.VIR_DOMAIN_XML_INACTIVE)
    url = f"/api/vms/{dom.UUIDString()}/guest-tools"
    result = lib_client.post(url, headers=AUTH, json={"family": "windows"}).json()
    assert result == {
        "drive": expected,
        "restart_required": restart,
        "installer": tools.WINDOWS_INSTALLER,
    }
    cd = str(tmp_path / "data" / "KVM-Studio" / "Tools" / "kvmstudio-tools-windows.iso")
    config = media(dom, libvirt.VIR_DOMAIN_XML_INACTIVE)
    assert config[expected] == cd
    assert [t for t, p in config.items() if p == cd] == [expected]
    if start and not restart:
        assert media(dom)[expected] == cd
    # Inserting again keeps the same drive and what it held first.
    again = lib_client.post(url, headers=AUTH, json={"family": "windows"}).json()
    assert again["drive"] == expected

    lib_client.post(f"{url}/eject", headers=AUTH)
    after = media(dom, libvirt.VIR_DOMAIN_XML_INACTIVE)
    # An added drive stays, empty; the others hold what they held before.
    assert after == {**{expected: None}, **before}


@needs_xorriso
def test_running_vm_prefers_a_live_drive(
    lib_client: TestClient,
    lib_config: Config,
    conn: Any,
    vms: list[libvirt.virDomain],
    tmp_path: Path,
) -> None:
    lib_config.defaults.virtio_win_iso = fake_virtio(tmp_path / "iso" / VIRTIO)
    win = touch(tmp_path / "iso" / WIN)
    dom = make_vm(conn, [str(win)], start=True, agent=True)
    vms.append(dom)
    # A drive added since the start exists only in the config.
    hardware.add_cdrom_drive(conn, dom.UUIDString(), None)
    url = f"/api/vms/{dom.UUIDString()}/guest-tools"
    result = lib_client.post(url, headers=AUTH, json={"family": "windows"}).json()
    assert (result["drive"], result["restart_required"]) == ("sda", False)


@pytest.mark.parametrize(
    ("setting", "code", "state"),
    [
        (None, "guest.no_virtio_iso", "unset"),
        ("iso/missing.iso", "guest.virtio_missing", "missing"),
        ("elsewhere/virtio-win.iso", "guest.virtio_outside", "outside"),
    ],
)
def test_windows_virtio_iso_errors(
    lib_client: TestClient,
    lib_config: Config,
    conn: Any,
    vms: list[libvirt.virDomain],
    tmp_path: Path,
    setting: str | None,
    code: str,
    state: str,
) -> None:
    if setting:
        lib_config.defaults.virtio_win_iso = tmp_path / setting
        if setting.startswith("elsewhere"):
            touch(tmp_path / setting)
    dom = make_vm(conn, [None], start=False)
    vms.append(dom)
    url = f"/api/vms/{dom.UUIDString()}/guest-tools"
    info = lib_client.get(url, headers=AUTH).json()
    assert info["virtio_state"] == state
    assert info["virtio_win"] == (str(tmp_path / setting) if setting else None)
    response = lib_client.post(url, headers=AUTH, json={"family": "windows"})
    assert response.json()["error"]["code"] == code
    # Nothing changed in the VM.
    assert media(dom, libvirt.VIR_DOMAIN_XML_INACTIVE) == {"sda": None}
    assert not tools.has_agent_channel(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))


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
