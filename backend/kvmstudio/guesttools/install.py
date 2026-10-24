"""Install the guest tools by typing the command in the guest (F-64).

Windows: the virtio-win ISO goes into a CD/DVD drive, then Win+R runs its
installer elevated (the user accepts the UAC prompt). Linux: the package
manager command is typed in the terminal that has the focus (the user types
the sudo password). Afterwards qemu-guest-agent should answer pings.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Literal

import libvirt
from lxml import etree

from ..config import Config
from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection
from ..paths import confine, in_iso_library
from ..services.library import metadata_values, set_metadata
from .keymaps import KEY, Layout, UnsupportedCharacter, strokes

Family = Literal["windows", "linux", "bsd", "other"]

LIBOSINFO_NS = "http://libosinfo.org/xmlns/libvirt/domain/1.0"
KEY_DELAY = 0.03  # between keystrokes, so slow guests keep up
HOLD_MS = 30

LINUX_COMMAND = (
    "sudo sh -c '"
    "(command -v apt-get >/dev/null && apt-get update -q && "
    "apt-get install -y qemu-guest-agent spice-vdagent) || "
    "(command -v dnf >/dev/null && dnf install -y qemu-guest-agent spice-vdagent) || "
    "zypper -n install qemu-guest-agent spice-vdagent; "
    "systemctl enable --now qemu-guest-agent'\n"
)
WINDOWS_COMMAND = (
    'powershell -NoProfile -Command "Start-Process -Verb RunAs '
    "((Get-Volume -FileSystemLabel 'virtio-win*').DriveLetter + "
    "':\\virtio-win-guest-tools.exe')\"\n"
)

SendKeys = Callable[[list[int]], None]


def guess_family(xml: str) -> Family | None:
    """From our profile, or from the libosinfo id virt-manager records."""
    profile = metadata_values(xml).get("profile", "")
    if profile.startswith("windows"):
        return "windows"
    if profile in ("linux", "nested"):
        return "linux"
    if profile == "firewall":
        return "bsd"
    root = etree.fromstring(xml.encode(), parser=etree.XMLParser(resolve_entities=False))
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


def type_text(send: SendKeys, text: str, layout: Layout, sleep: Callable[[float], None]) -> None:
    for stroke in strokes(text, layout):
        send(list(stroke))
        sleep(KEY_DELAY)


def _insert_iso(dom: libvirt.virDomain, iso: str) -> str:
    """Put the ISO in an empty drive, or in the first one; returns the drive name."""
    root = etree.fromstring(dom.XMLDesc(0).encode(), parser=etree.XMLParser(resolve_entities=False))
    drives = root.findall("devices/disk[@device='cdrom']")
    if not drives:
        raise ApiException(
            409, "guest.no_cdrom", "Add a CD/DVD drive (VM powered off) to insert virtio-win"
        )
    drive = next((d for d in drives if d.find("source") is None), drives[0])
    for old in drive.findall("source"):
        drive.remove(old)
    driver = drive.find("driver")
    source = etree.Element("source", file=iso)
    drive.insert(list(drive).index(driver) + 1 if driver is not None else 0, source)
    flags = libvirt.VIR_DOMAIN_AFFECT_LIVE
    if dom.isPersistent():
        flags |= libvirt.VIR_DOMAIN_AFFECT_CONFIG
    dom.updateDeviceFlags(etree.tostring(drive).decode(), flags)
    target = drive.find("target")
    return target.get("dev", "") if target is not None else ""


def install(
    conn: LibvirtConnection,
    config: Config,
    uuid: str,
    family: Family,
    layout: Layout,
    sleep: Callable[[float], None] | None = None,
) -> str | None:
    """Type the install command; returns the drive that received virtio-win, if any."""
    pause = sleep or time.sleep
    if family not in ("windows", "linux"):
        raise ApiException(422, "guest.unsupported", f"no automatic install for {family} guests")
    iso: str | None = None
    if family == "windows":
        configured = config.defaults.virtio_win_iso
        if configured is None:
            raise ApiException(409, "guest.no_virtio_iso", "Set the virtio-win ISO in Preferences")
        iso = str(confine(str(configured), config))
        if not in_iso_library(iso, config):
            raise ApiException(403, "path.not_allowed", f"{iso} is not in an ISO library")
    command = WINDOWS_COMMAND if family == "windows" else LINUX_COMMAND
    try:
        strokes(command, layout)  # refuse before touching the VM
    except UnsupportedCharacter as exc:
        raise ApiException(422, "guest.layout", str(exc)) from exc

    def op(c: libvirt.virConnect) -> str | None:
        dom = c.lookupByUUIDString(uuid)
        if not dom.isActive():
            raise ApiException(409, "vm.not_running", "Start the virtual machine first")

        def send(keys: list[int]) -> None:
            dom.sendKey(libvirt.VIR_KEYCODE_SET_LINUX, HOLD_MS, keys, len(keys), 0)

        drive = None
        if iso is not None:
            drive = _insert_iso(dom, iso)
            pause(3)  # let Windows notice the disc
            send([KEY["LEFTMETA"], KEY["R"]])
            pause(1.5)
        type_text(send, command, layout, pause)
        set_metadata(dom, keyboard=layout, family=family)
        return drive

    return conn.run(op)
