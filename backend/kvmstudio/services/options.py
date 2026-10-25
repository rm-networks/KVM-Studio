"""VM settings, Options tab: general, power, firmware and boot, isolation (F-55, F-61).

Everything is written to the persistent definition (inactive XML). Firmware,
Secure Boot and TPM changes need the VM powered off; the others apply at the
next start of a running VM.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import libvirt
from lxml import etree

from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection
from ..xml.devices import SPICE_AGENT_PORT, vdagent_channel
from ..xml.profiles import PROFILES
from .library import metadata_values, set_metadata

_PARSER = etree.XMLParser(resolve_entities=False, remove_blank_text=True)

Firmware = Literal["uefi", "bios"]
RebootAction = Literal["restart", "destroy"]
CrashAction = Literal["destroy", "restart", "preserve"]
BootKind = Literal["disk", "cdrom", "nic"]

# A disk holding more than this is taken as an installed system.
INSTALLED_BYTES = 256 * 1024 * 1024
# Set when the UEFI variables must be rebuilt from the right template at the
# next start (Secure Boot turned on or off).
RESET_NVRAM_KEY = "reset-nvram"


@dataclass(frozen=True, slots=True)
class BootDevice:
    kind: BootKind
    id: str  # disk target ("vda", "sdb") or MAC address
    detail: str  # file name or network
    enabled: bool


@dataclass(slots=True)
class Options:
    name: str
    profile: str | None
    active: bool
    installed: bool
    autostart: bool
    on_reboot: str
    on_crash: str
    firmware: Firmware
    secure_boot: bool
    tpm: bool
    boot_menu: bool
    boot: list[BootDevice] = field(default_factory=list)
    clipboard: bool = True
    reset_nvram_pending: bool = False


@dataclass(slots=True)
class OptionsChange:
    profile: str | None = None
    autostart: bool | None = None
    on_reboot: RebootAction | None = None
    on_crash: CrashAction | None = None
    firmware: Firmware | None = None
    secure_boot: bool | None = None
    tpm: bool | None = None
    boot_menu: bool | None = None
    # Every bootable device in order; the enabled ones get a <boot order>.
    boot: list[tuple[BootKind, str, bool]] | None = None
    clipboard: bool | None = None
    # Changing the firmware or removing the TPM of an installed VM may leave it
    # unable to start: the interface asks first and says so here.
    confirmed: bool = False


def _parse(xml: str) -> etree._Element:
    return etree.fromstring(xml.encode(), parser=_PARSER)


def _file_name(path: str | None) -> str:
    return path.rsplit("/", 1)[-1] if path else ""


def _device_id(el: etree._Element) -> tuple[BootKind, str, str] | None:
    if el.tag == "disk":
        target = el.find("target")
        if target is None or el.get("device", "disk") not in ("disk", "cdrom"):
            return None
        source = el.find("source")
        path = (source.get("file") or source.get("dev")) if source is not None else None
        kind: BootKind = "cdrom" if el.get("device") == "cdrom" else "disk"
        return kind, target.get("dev", ""), _file_name(path)
    if el.tag == "interface":
        mac = el.find("mac")
        source = el.find("source")
        detail = (source.get("network") or source.get("bridge") or "") if source is not None else ""
        return ("nic", mac.get("address", ""), detail) if mac is not None else None
    return None


def _bootable(root: etree._Element) -> list[tuple[etree._Element, tuple[BootKind, str, str]]]:
    devices = root.find("devices")
    if devices is None:
        return []
    found = ((el, _device_id(el)) for el in devices if el.tag in ("disk", "interface"))
    return [(el, ident) for el, ident in found if ident is not None]


def boot_devices(root: etree._Element) -> list[BootDevice]:
    """Bootable devices in boot order: the enabled ones first."""
    items = []
    for index, (el, ident) in enumerate(_bootable(root)):
        boot = el.find("boot")
        order = int(boot.get("order", "0")) if boot is not None else 0
        items.append((order, index, BootDevice(ident[0], ident[1], ident[2], order > 0)))
    per_device = any(order for order, _, _ in items)
    if not per_device:
        # Old style <os><boot dev=.../>: the first device of each kind, in that order.
        legacy = [b.get("dev") for b in root.iterfind("os/boot")]
        kinds = {"hd": "disk", "cdrom": "cdrom", "network": "nic"}
        ranks = {kinds[d]: n + 1 for n, d in enumerate(legacy) if d in kinds}
        seen: set[str] = set()
        rebuilt = []
        for _, index, dev in items:
            rank = ranks.get(dev.kind, 0) if dev.kind not in seen else 0
            seen.add(dev.kind)
            rebuilt.append((rank, index, BootDevice(dev.kind, dev.id, dev.detail, rank > 0)))
        items = rebuilt
    enabled = sorted((o, i, d) for o, i, d in items if o > 0)
    disabled = [(o, i, d) for o, i, d in items if o == 0]
    return [d for _, _, d in enabled + disabled]


def _clipboard(root: etree._Element) -> bool:
    channel = root.find("devices/channel[@type='qemu-vdagent']")
    if channel is None:
        return False
    clip = channel.find("source/clipboard")
    return clip is not None and clip.get("copypaste") == "yes"


def _installed(root: etree._Element) -> bool:
    for disk in root.iterfind("devices/disk[@device='disk']"):
        source = disk.find("source")
        path = (source.get("file") or source.get("dev")) if source is not None else None
        if not path:
            continue
        try:
            if os.stat(path).st_blocks * 512 > INSTALLED_BYTES:
                return True
        except FileNotFoundError:
            continue
        except OSError:
            # Not readable from here (another owner): assume a system is there.
            return True
    return False


def read(xml: str, *, active: bool, autostart: bool) -> Options:
    root = _parse(xml)
    meta = metadata_values(xml)
    os_el = root.find("os")
    loader = os_el.find("loader") if os_el is not None else None
    uefi = os_el is not None and (
        os_el.get("firmware") == "efi" or (loader is not None and loader.get("type") == "pflash")
    )
    secure = False
    if os_el is not None and uefi:
        feature = os_el.find("firmware/feature[@name='secure-boot']")
        secure = (feature is not None and feature.get("enabled") == "yes") or (
            loader is not None and loader.get("secure") == "yes"
        )
    menu = os_el.find("bootmenu") if os_el is not None else None
    profile = meta.get("profile") or None
    return Options(
        name=root.findtext("name", ""),
        profile=profile if profile in PROFILES else None,
        active=active,
        installed=_installed(root),
        autostart=autostart,
        on_reboot=root.findtext("on_reboot", "restart"),
        on_crash=root.findtext("on_crash", "destroy"),
        firmware="uefi" if uefi else "bios",
        secure_boot=secure,
        tpm=root.find("devices/tpm") is not None,
        boot_menu=menu is not None and menu.get("enable") == "yes",
        boot=boot_devices(root),
        clipboard=_clipboard(root),
        reset_nvram_pending=meta.get(RESET_NVRAM_KEY) == "yes",
    )


def get(conn: LibvirtConnection, uuid: str) -> Options:
    def op(c: libvirt.virConnect) -> Options:
        dom = c.lookupByUUIDString(uuid)
        return read(
            dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE),
            active=bool(dom.isActive()),
            autostart=bool(dom.autostart()),
        )

    return conn.run(op)


# Editing


def _set_text(root: etree._Element, tag: str, value: str, before: str) -> None:
    el = root.find(tag)
    if el is None:
        el = etree.Element(tag)
        anchor = root.find(before)
        if anchor is not None:
            anchor.addprevious(el)
        else:
            root.append(el)
    el.text = value


def _os(root: etree._Element) -> etree._Element:
    os_el = root.find("os")
    if os_el is None:
        raise ApiException(409, "options.no_os", "The definition has no <os> element")
    return os_el


def _insert_os_child(os_el: etree._Element, el: etree._Element) -> None:
    """Keep libvirt's order: type, firmware, loader, nvram, then boot entries."""
    after = None
    for tag in ("type", "firmware", "loader", "nvram"):
        if (found := os_el.find(tag)) is not None:
            after = found
        if tag == el.tag:
            break
    if after is not None:
        after.addnext(el)
    else:
        os_el.insert(0, el)


def _features(root: etree._Element) -> etree._Element:
    features = root.find("features")
    if features is None:
        features = etree.Element("features")
        anchors = (root.find(tag) for tag in ("cpu", "clock", "devices"))
        anchor = next((a for a in anchors if a is not None), None)
        if anchor is not None:
            anchor.addprevious(features)
        else:
            root.append(features)
    return features


def _forget_firmware_paths(os_el: etree._Element) -> None:
    """Let libvirt pick the firmware files again from the requested features."""
    loader = os_el.find("loader")
    if loader is not None:
        os_el.remove(loader)
    nvram = os_el.find("nvram")
    if nvram is not None:
        for attr in ("template", "templateFormat", "format"):
            nvram.attrib.pop(attr, "")


def _set_uefi(root: etree._Element, secure: bool, nvram: str | None) -> None:
    os_el = _os(root)
    os_el.set("firmware", "efi")
    firmware = os_el.find("firmware")
    if firmware is None:
        firmware = etree.Element("firmware")
        _insert_os_child(os_el, firmware)
    for child in list(firmware):
        firmware.remove(child)
    value = "yes" if secure else "no"
    etree.SubElement(firmware, "feature", enabled=value, name="enrolled-keys")
    etree.SubElement(firmware, "feature", enabled=value, name="secure-boot")
    _forget_firmware_paths(os_el)
    if secure:
        loader = etree.Element("loader", secure="yes")
        _insert_os_child(os_el, loader)
    if os_el.find("nvram") is None and nvram:
        el = etree.Element("nvram")
        el.text = nvram
        _insert_os_child(os_el, el)
    features = _features(root)
    smm = features.find("smm")
    if secure and smm is None:
        etree.SubElement(features, "smm", state="on")


def _set_bios(root: etree._Element) -> None:
    os_el = _os(root)
    os_el.attrib.pop("firmware", "")
    for tag in ("firmware", "loader", "nvram"):
        if (el := os_el.find(tag)) is not None:
            os_el.remove(el)


def _set_tpm(root: etree._Element, on: bool) -> None:
    devices = root.find("devices")
    if devices is None:
        return
    current = devices.find("tpm")
    if on and current is None:
        tpm = etree.SubElement(devices, "tpm", model="tpm-crb")
        etree.SubElement(tpm, "backend", type="emulator", version="2.0")
    elif not on and current is not None:
        devices.remove(current)


def _set_boot(root: etree._Element, order: list[tuple[BootKind, str, bool]]) -> None:
    os_el = _os(root)
    by_id = {(kind, name): el for el, (kind, name, _) in _bootable(root)}
    if sorted(by_id) != sorted((k, i) for k, i, _ in order):
        raise ApiException(409, "options.boot_devices_changed", "The devices changed meanwhile")
    # Per-device boot order cannot be mixed with <os><boot dev=.../>.
    for el in os_el.findall("boot"):
        os_el.remove(el)
    for el in by_id.values():
        for boot in el.findall("boot"):
            el.remove(boot)
    rank = 0
    for kind, name, enabled in order:
        if enabled:
            rank += 1
            etree.SubElement(by_id[(kind, name)], "boot", order=str(rank))


def _set_boot_menu(root: etree._Element, on: bool) -> None:
    os_el = _os(root)
    menu = os_el.find("bootmenu")
    if menu is None:
        menu = etree.SubElement(os_el, "bootmenu")
    menu.attrib.clear()
    menu.set("enable", "yes" if on else "no")
    if on:
        menu.set("timeout", "3000")


def _set_clipboard(root: etree._Element, on: bool) -> None:
    devices = root.find("devices")
    if devices is None:
        return
    channel = devices.find("channel[@type='qemu-vdagent']")
    if channel is None:
        if not on:
            return
        for other in devices.findall("channel"):
            target = other.find("target")
            if target is not None and target.get("name") == SPICE_AGENT_PORT:
                devices.remove(other)
        devices.append(vdagent_channel())
        return
    source = channel.find("source")
    if source is None:
        source = etree.SubElement(channel, "source")
    clip = source.find("clipboard")
    if clip is None:
        clip = etree.SubElement(source, "clipboard")
    clip.set("copypaste", "yes" if on else "no")


def _nvram_for(root: etree._Element, dom: libvirt.virDomain) -> str | None:
    """New UEFI variables next to the first disk, as at creation (spec 6.1.1)."""
    for disk in root.iterfind("devices/disk[@device='disk']"):
        source = disk.find("source")
        path = source.get("file") if source is not None else None
        if path:
            return str(Path(path).parent / f"{dom.name()}_VARS.fd")
    return None


def update(conn: LibvirtConnection, uuid: str, change: OptionsChange) -> bool:
    """Apply the change; returns True when a running VM gets it at next start."""

    def op(c: libvirt.virConnect) -> bool:
        dom = c.lookupByUUIDString(uuid)
        active = bool(dom.isActive())
        xml = dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)
        root = _parse(xml)
        now = read(xml, active=active, autostart=bool(dom.autostart()))

        firmware = change.firmware or now.firmware
        secure = change.secure_boot if change.secure_boot is not None else now.secure_boot
        if firmware == "bios":
            secure = False
        firmware_changed = firmware != now.firmware
        secure_changed = secure != now.secure_boot
        tpm_changed = change.tpm is not None and change.tpm != now.tpm
        if (firmware_changed or secure_changed or tpm_changed) and active:
            raise ApiException(
                409, "options.must_be_off", "Power off the virtual machine to change this"
            )
        risky = firmware_changed or (tpm_changed and not change.tpm)
        if risky and now.installed and not change.confirmed:
            raise ApiException(
                409, "options.confirm", "This change may stop the installed system from starting"
            )
        if change.profile is not None and change.profile not in PROFILES:
            raise ApiException(422, "options.unknown_profile", "Unknown guest system")

        if firmware_changed and firmware == "bios":
            _set_bios(root)
        elif firmware_changed or secure_changed:
            _set_uefi(root, secure, _nvram_for(root, dom))
        if change.tpm is not None and tpm_changed:
            _set_tpm(root, change.tpm)
        if change.on_reboot is not None:
            _set_text(root, "on_reboot", change.on_reboot, before="on_crash")
        if change.on_crash is not None:
            _set_text(root, "on_crash", change.on_crash, before="devices")
        if change.boot is not None:
            _set_boot(root, change.boot)
        if change.boot_menu is not None:
            _set_boot_menu(root, change.boot_menu)
        if change.clipboard is not None and change.clipboard != now.clipboard:
            _set_clipboard(root, change.clipboard)

        defined = c.defineXML(etree.tostring(root).decode())
        if change.autostart is not None and change.autostart != now.autostart:
            defined.setAutostart(1 if change.autostart else 0)
        values: dict[str, str] = {}
        if change.profile is not None:
            values["profile"] = change.profile
        if (secure_changed and firmware == "uefi") or (firmware_changed and firmware == "uefi"):
            # Variables built from the other template keep the previous keys.
            values[RESET_NVRAM_KEY] = "yes"
        elif firmware_changed:
            values[RESET_NVRAM_KEY] = ""
        if values:
            set_metadata(defined, **values)
        config_only = any(
            v is not None
            for v in (
                change.on_reboot,
                change.on_crash,
                change.boot,
                change.boot_menu,
                change.clipboard,
            )
        )
        return active and config_only

    return conn.run(op)


def start_flags(xml: str) -> int:
    """Flags for virDomainCreateWithFlags: rebuild the UEFI variables when asked."""
    if metadata_values(xml).get(RESET_NVRAM_KEY) == "yes":
        return int(getattr(libvirt, "VIR_DOMAIN_START_RESET_NVRAM", 32))
    return 0


def started(dom: libvirt.virDomain) -> None:
    """Forget the pending NVRAM reset once the VM started with it."""
    if metadata_values(dom.XMLDesc(0)).get(RESET_NVRAM_KEY):
        set_metadata(dom, **{RESET_NVRAM_KEY: ""})
