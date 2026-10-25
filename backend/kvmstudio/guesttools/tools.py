"""Install the guest tools from a small CD made by KVM Studio (F-64).

The CD goes into a CD/DVD drive of the VM; the user starts the installer in
the guest. Nothing depends on the guest keyboard layout.

- Linux: install.sh installs qemu-guest-agent and spice-vdagent with the
  package manager it finds.
- Windows: autorun.inf, Install-Tools.bat and virtio-win-guest-tools.exe
  (drivers, qemu-guest-agent, spice-vdagent), copied from the virtio-win ISO
  of the Preferences, which is only read. One drive is enough: a running VM
  cannot get a new SATA drive before it is powered off.

The CD lives in <location>/KVM-Studio/Tools, KVM Studio's own folder that QEMU
can already reach, never in a user ISO library. What the drives held before is
written in the VM <metadata> and put back on eject.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

import libvirt
from lxml import etree

from ..config import Config
from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection
from ..paths import LIBRARY_DIRNAME, in_iso_library, resolve
from ..services import hardware
from ..services.library import metadata_values, set_metadata

Family = Literal["windows", "linux", "bsd", "other"]
VirtioState = Literal["ok", "unset", "missing", "outside"]

LIBOSINFO_NS = "http://libosinfo.org/xmlns/libvirt/domain/1.0"
TOOLS_DIRNAME = "Tools"
VOLUME_ID = "KS_TOOLS"
WINDOWS_INSTALLER = "virtio-win-guest-tools.exe"
FILES = Path(__file__).parent / "files"
AGENT_CHANNEL = "org.qemu.guest_agent.0"
# Shown in the dialog with a Copy button. No root needed here: the CD is
# found where the desktop mounted it, or mounted with udisksctl; install.sh
# asks for elevation itself.
LINUX_COMMAND = (
    "d=$(findmnt -nro TARGET -S LABEL=KS_TOOLS) || { udisksctl mount -b "
    "/dev/disk/by-label/KS_TOOLS >/dev/null && d=$(findmnt -nro TARGET -S LABEL=KS_TOOLS); }; "
    'sh "$d/install.sh"'
)
_PARSER = etree.XMLParser(resolve_entities=False)


def guess_family(xml: str) -> Family | None:
    """From our profile, or from the libosinfo id virt-manager records."""
    profile = metadata_values(xml).get("profile", "")
    if profile.startswith("windows"):
        return "windows"
    if profile in ("linux", "nested"):
        return "linux"
    if profile == "firewall":
        return "bsd"
    root = etree.fromstring(xml.encode(), parser=_PARSER)
    os_el = root.find(f"metadata/{{{LIBOSINFO_NS}}}libosinfo/{{{LIBOSINFO_NS}}}os")
    os_id = os_el.get("id", "") if os_el is not None else ""
    if "microsoft.com/win" in os_id:
        return "windows"
    if "freebsd" in os_id or "opnsense" in os_id or "pfsense" in os_id:
        return "bsd"
    if any(
        name in os_id
        for name in ("debian", "ubuntu", "fedoraproject", "redhat", "centos", "rocky", "alma",
                     "suse", "archlinux", "linux")
    ):  # fmt: skip
        return "linux"
    return None


def agent_responds(dom: libvirt.virDomain) -> bool:
    import libvirt_qemu

    try:
        answer = libvirt_qemu.qemuAgentCommand(dom, json.dumps({"execute": "guest-ping"}), 3, 0)
    except libvirt.libvirtError:
        return False
    return "return" in json.loads(answer or "{}")


def has_agent_channel(xml: str) -> bool:
    root = etree.fromstring(xml.encode(), parser=_PARSER)
    return root.find(f"devices/channel/target[@name='{AGENT_CHANNEL}']") is not None


def tools_dir(config: Config) -> Path:
    location = config.storage.vm_default_location
    if location is None:
        raise ApiException(409, "library.no_root", "Choose a VM folder in Preferences first")
    return location / LIBRARY_DIRNAME / TOOLS_DIRNAME


def virtio_iso(config: Config) -> tuple[VirtioState, Path | None]:
    """State of the virtio-win ISO of the Preferences, and its path (resolved when ok)."""
    configured = config.defaults.virtio_win_iso
    if configured is None:
        return "unset", None
    path = resolve(str(configured))
    if not path.is_file():
        return "missing", configured
    if not in_iso_library(path, config):
        return "outside", configured
    return "ok", path


def _checked_virtio_iso(config: Config) -> Path:
    state, path = virtio_iso(config)
    if state == "unset":
        raise ApiException(409, "guest.no_virtio_iso", "Set the virtio-win ISO in Preferences")
    if state == "missing":
        raise ApiException(404, "guest.virtio_missing", f"{path} does not exist")
    if state == "outside" or path is None:
        raise ApiException(403, "guest.virtio_outside", f"{path} is not in an ISO library")
    return path


def _xorriso(args: list[str]) -> None:
    try:
        subprocess.run(  # noqa: S603
            ["xorriso", *args],  # noqa: S607
            check=True,
            capture_output=True,
            timeout=300,
        )
    except FileNotFoundError:
        raise ApiException(500, "guest.no_xorriso", "xorriso is not installed") from None
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace").strip()
        raise ApiException(500, "guest.iso_failed", detail) from None


def extract_installer(virtio: Path, dest: Path) -> None:
    """Copy the guest tools installer out of the virtio-win ISO, which is only read."""
    try:
        _xorriso(["-osirrox", "on", "-indev", str(virtio), "-extract", f"/{WINDOWS_INSTALLER}",
                  str(dest)])  # fmt: skip
    except ApiException as exc:
        if exc.code != "guest.iso_failed":
            raise
        raise ApiException(
            422, "guest.no_installer", f"{WINDOWS_INSTALLER} is not in {virtio}: {exc.detail}"
        ) from None
    dest.chmod(0o644)


def build_iso(family: Literal["windows", "linux"], dest: Path, virtio: Path | None = None) -> Path:
    """Write the guest tools CD for this family (rebuilt each time)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kvmstudio-tools-") as tmp:
        content = Path(tmp) / "cd"
        shutil.copytree(FILES / family, content)
        if family == "linux":
            (content / "install.sh").chmod(0o755)
        if virtio is not None:
            extract_installer(virtio, content / WINDOWS_INSTALLER)
        partial = dest.with_suffix(".iso.part")
        # Rock Ridge (-r: owned by root, readable by all) keeps install.sh executable;
        # Joliet gives Windows its long names.
        try:
            _xorriso(["-as", "mkisofs", "-quiet", "-V", VOLUME_ID, "-J", "-r",
                      "-o", str(partial), str(content)])  # fmt: skip
        except ApiException:
            partial.unlink(missing_ok=True)
            raise
        partial.chmod(0o644)
        partial.replace(dest)
    return dest


def _cdroms(xml: str) -> list[tuple[str, str | None]]:
    root = etree.fromstring(xml.encode(), parser=_PARSER)
    drives = []
    for disk in root.iterfind("devices/disk[@device='cdrom']"):
        target = disk.find("target")
        source = disk.find("source")
        if target is not None and target.get("dev"):
            drives.append(
                (target.get("dev", ""), source.get("file") if source is not None else None)
            )
    return drives


def _xml(conn: LibvirtConnection, uuid: str) -> tuple[str, bool]:
    def op(c: libvirt.virConnect) -> tuple[str, bool]:
        dom = c.lookupByUUIDString(uuid)
        return dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE), bool(dom.isActive())

    return conn.run(op)


def _add_agent_channel(conn: LibvirtConnection, uuid: str) -> None:
    def op(c: libvirt.virConnect) -> None:
        dom = c.lookupByUUIDString(uuid)
        root = etree.fromstring(
            dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE).encode(), parser=_PARSER
        )
        devices = root.find("devices")
        if devices is None:
            return
        channel = etree.SubElement(devices, "channel", type="unix")
        etree.SubElement(channel, "target", type="virtio", name=AGENT_CHANNEL)
        c.defineXML(etree.tostring(root).decode())

    conn.run(op)


def _saved(xml: str) -> dict[str, str]:
    try:
        value = json.loads(metadata_values(xml).get("tools_media", "") or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def inserted(xml: str) -> bool:
    return bool(_saved(xml))


def insert(conn: LibvirtConnection, config: Config, uuid: str, family: Family) -> tuple[str, bool]:
    """Put the tools CD in one drive; returns the drive and whether a power cycle is due.

    The drive is one that already holds the CD, else an empty one, else one
    holding something else (put back at eject). On a running VM a drive that
    is only in the config comes last, and a drive is added only when there is
    none: SATA drives appear after the VM is powered off and started again.
    """
    if family not in ("windows", "linux"):
        raise ApiException(422, "guest.unsupported", f"no guest tools for {family} guests")
    virtio = _checked_virtio_iso(config) if family == "windows" else None
    cd = build_iso(family, tools_dir(config) / f"kvmstudio-tools-{family}.iso", virtio)

    xml, active = _xml(conn, uuid)
    live = None
    if active:
        live_xml = conn.run(lambda c: c.lookupByUUIDString(uuid).XMLDesc(0))
        live = {target for target, _path in _cdroms(live_xml)}
    restart = False
    if not has_agent_channel(xml):
        _add_agent_channel(conn, uuid)
        restart = active
    saved = _saved(xml)
    drives = _cdroms(xml)
    drives.sort(
        key=lambda d: (live is not None and d[0] not in live, d[0] not in saved, d[1] is not None)
    )
    if drives:
        target, previous = drives[0]
        restart = restart or (live is not None and target not in live)
    else:
        target, added_live = hardware.add_cdrom_drive(conn, uuid, None)
        previous = None
        restart = restart or added_live
    if target not in saved:
        saved[target] = previous or ""
    hardware.set_media(conn, uuid, target, str(cd))
    conn.run(
        lambda c: set_metadata(
            c.lookupByUUIDString(uuid), tools_media=json.dumps(saved), family=family
        )
    )
    return target, restart


def eject(conn: LibvirtConnection, uuid: str) -> list[str]:
    """Put back what the drives held before; returns the drives touched."""
    xml, _active = _xml(conn, uuid)
    saved = _saved(xml)
    present = {target for target, _path in _cdroms(xml)}
    for target, path in saved.items():
        if target in present:
            hardware.set_media(conn, uuid, target, path or None)
    conn.run(lambda c: set_metadata(c.lookupByUUIDString(uuid), tools_media=""))
    return sorted(t for t in saved if t in present)
