"""Install the guest tools from a small CD made by KVM Studio (F-64).

The CD goes into a CD/DVD drive of the VM; the user starts the installer in
the guest. Nothing depends on the guest keyboard layout.

- Linux: install.sh installs qemu-guest-agent and spice-vdagent with the
  package manager it finds.
- Windows: autorun.inf and Install-Tools.bat, which runs the virtio-win guest
  tools installer (drivers, qemu-guest-agent, spice-vdagent) from the
  virtio-win ISO of the Preferences, in a second drive.

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
from ..paths import LIBRARY_DIRNAME, confine, in_iso_library
from ..services import hardware
from ..services.library import metadata_values, set_metadata

Family = Literal["windows", "linux", "bsd", "other"]

LIBOSINFO_NS = "http://libosinfo.org/xmlns/libvirt/domain/1.0"
TOOLS_DIRNAME = "Tools"
VOLUME_ID = "KS_TOOLS"
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


def build_iso(family: Literal["windows", "linux"], dest: Path) -> Path:
    """Write the guest tools CD for this family (rebuilt each time, a few KiB)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kvmstudio-tools-") as tmp:
        content = Path(tmp) / "cd"
        shutil.copytree(FILES / family, content)
        if family == "linux":
            (content / "install.sh").chmod(0o755)
        partial = dest.with_suffix(".iso.part")
        # Rock Ridge (-r: owned by root, readable by all) keeps install.sh executable;
        # Joliet gives Windows its long names.
        command = ["xorriso", "-as", "mkisofs", "-quiet", "-V", VOLUME_ID, "-J", "-r"]
        try:
            subprocess.run(  # noqa: S603
                [*command, "-o", str(partial), str(content)],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except FileNotFoundError:
            raise ApiException(500, "guest.no_xorriso", "xorriso is not installed") from None
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode(errors="replace").strip()
            raise ApiException(500, "guest.iso_failed", detail) from None
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


def insert(
    conn: LibvirtConnection, config: Config, uuid: str, family: Family
) -> tuple[list[str], bool]:
    """Put the tools CD (and virtio-win for Windows) in drives; returns drives, restart flag."""
    if family not in ("windows", "linux"):
        raise ApiException(422, "guest.unsupported", f"no guest tools for {family} guests")
    images: list[str] = []
    if family == "windows":
        configured = config.defaults.virtio_win_iso
        if configured is None:
            raise ApiException(409, "guest.no_virtio_iso", "Set the virtio-win ISO in Preferences")
        virtio = str(confine(str(configured), config))
        if not in_iso_library(virtio, config):
            raise ApiException(403, "path.not_allowed", f"{virtio} is not in an ISO library")
        images.append(virtio)
    cd = build_iso(family, tools_dir(config) / f"kvmstudio-tools-{family}.iso")
    images.insert(0, str(cd))

    xml, active = _xml(conn, uuid)
    restart = False
    if not has_agent_channel(xml):
        _add_agent_channel(conn, uuid)
        restart = restart or active
    saved = _saved(xml)
    drives = _cdroms(xml)
    # Already ours first, then empty drives, then drives holding something.
    drives.sort(key=lambda d: (d[0] not in saved, d[1] is not None))
    chosen = [target for target, _path in drives[: len(images)]]
    previous = {target: path for target, path in drives}
    while len(chosen) < len(images):
        target, needs_restart = hardware.add_cdrom_drive(conn, uuid, None)
        restart = restart or needs_restart
        previous[target] = None
        chosen.append(target)

    for target in chosen:
        if target not in saved:
            saved[target] = previous[target] or ""
    for target, image in zip(chosen, images, strict=True):
        hardware.set_media(conn, uuid, target, image)
    conn.run(
        lambda c: set_metadata(
            c.lookupByUUIDString(uuid), tools_media=json.dumps(saved), family=family
        )
    )
    return chosen, restart


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
