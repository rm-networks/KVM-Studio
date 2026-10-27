"""VM settings: memory, processors, CD/DVD drives and network cards (F-52, F-53).

The persistent definition is always edited by rewriting the inactive XML. When
the VM runs, the change is also applied live where QEMU allows it (network
cards: plug, unplug, cable, network); otherwise it waits for the next boot.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

import libvirt
from lxml import etree

from ..config import Config
from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection
from ..paths import confine, in_iso_library
from ..xml.profiles import NicModel
from .create import nic_target

_PARSER = etree.XMLParser(resolve_entities=False, remove_blank_text=True)
MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")
MAX_NICS = 10
MAX_NOTES = 10000


@dataclass(frozen=True, slots=True)
class Nic:
    mac: str
    network: str | None
    model: str
    target: str | None
    connected: bool


@dataclass(frozen=True, slots=True)
class Drive:
    target: str
    bus: str
    path: str | None
    device: str
    format: str | None


@dataclass(slots=True)
class Hardware:
    memory_mib: int
    vcpus: int
    active: bool
    disks: list[Drive] = field(default_factory=list)
    cdroms: list[Drive] = field(default_factory=list)
    nics: list[Nic] = field(default_factory=list)


def _memory_mib(el: etree._Element | None) -> int:
    if el is None or not el.text:
        return 0
    value = int(el.text)
    unit = el.get("unit", "KiB")
    factor = {"b": 1 / 1024**2, "bytes": 1 / 1024**2, "KiB": 1 / 1024, "k": 1 / 1024,
              "MiB": 1, "M": 1, "GiB": 1024, "G": 1024}.get(unit, 1 / 1024)  # fmt: skip
    return int(value * factor)


def read(xml: str, active: bool) -> Hardware:
    root = etree.fromstring(xml.encode(), parser=_PARSER)
    hw = Hardware(
        memory_mib=_memory_mib(root.find("memory")),
        vcpus=int(root.findtext("vcpu", "1")),
        active=active,
    )
    for disk in root.iterfind("devices/disk"):
        target = disk.find("target")
        source = disk.find("source")
        driver = disk.find("driver")
        drive = Drive(
            target=target.get("dev", "") if target is not None else "",
            bus=target.get("bus", "") if target is not None else "",
            path=(source.get("file") or source.get("dev")) if source is not None else None,
            device=disk.get("device", "disk"),
            format=driver.get("type") if driver is not None else None,
        )
        (hw.cdroms if drive.device == "cdrom" else hw.disks).append(drive)
    for iface in root.iterfind("devices/interface"):
        mac = iface.find("mac")
        source = iface.find("source")
        model = iface.find("model")
        target = iface.find("target")
        link = iface.find("link")
        hw.nics.append(
            Nic(
                mac=mac.get("address", "") if mac is not None else "",
                network=source.get("network") if source is not None else None,
                model=model.get("type", "") if model is not None else "",
                target=target.get("dev") if target is not None else None,
                connected=link is None or link.get("state") != "down",
            )
        )
    return hw


def _domain(c: libvirt.virConnect, uuid: str) -> tuple[libvirt.virDomain, etree._Element]:
    dom = c.lookupByUUIDString(uuid)
    return dom, etree.fromstring(
        dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE).encode(), parser=_PARSER
    )


def get(conn: LibvirtConnection, uuid: str) -> Hardware:
    def op(c: libvirt.virConnect) -> Hardware:
        dom = c.lookupByUUIDString(uuid)
        active = bool(dom.isActive())
        # Live XML when running: it shows what the guest has right now.
        return read(dom.XMLDesc(0 if active else libvirt.VIR_DOMAIN_XML_INACTIVE), active)

    return conn.run(op)


def set_cpu_memory(conn: LibvirtConnection, uuid: str, memory_mib: int, vcpus: int) -> bool:
    """New memory and vCPU count for the next boot; True if a restart is needed."""

    def op(c: libvirt.virConnect) -> bool:
        dom, root = _domain(c, uuid)
        for tag in ("memory", "currentMemory"):
            el = root.find(tag)
            if el is None:
                el = etree.SubElement(root, tag)
            el.text = str(memory_mib)
            el.set("unit", "MiB")
        vcpu = root.find("vcpu")
        if vcpu is None:
            vcpu = etree.SubElement(root, "vcpu")
        vcpu.text = str(vcpus)
        if "current" in vcpu.attrib:
            del vcpu.attrib["current"]
        topology = root.find("cpu/topology")
        if topology is not None:
            # A fixed topology must match the new count: let libvirt derive it.
            topology.getparent().remove(topology)  # type: ignore[union-attr]
        c.defineXML(etree.tostring(root).decode())
        return bool(dom.isActive())

    return conn.run(op)


def set_notes(conn: LibvirtConnection, uuid: str, notes: str) -> None:
    """The VM notes, in libvirt's own description element (virt-manager shows it too)."""

    def op(c: libvirt.virConnect) -> None:
        dom, root = _domain(c, uuid)
        el = root.find("description")
        if notes and el is None:
            el = etree.Element("description")
            # Right after the name, uuid or title, where libvirt writes it.
            anchor = next(
                (root.find(tag) for tag in ("title", "uuid", "name") if root.find(tag) is not None),
                None,
            )
            if anchor is not None:
                anchor.addnext(el)
            else:
                root.insert(0, el)
        if el is not None:
            if notes:
                el.text = notes
            else:
                root.remove(el)
        c.defineXML(etree.tostring(root).decode())
        if dom.isActive():
            dom.setMetadata(
                libvirt.VIR_DOMAIN_METADATA_DESCRIPTION,
                notes or None,
                None,
                None,
                libvirt.VIR_DOMAIN_AFFECT_LIVE,
            )

    conn.run(op)


def _new_mac(taken: set[str]) -> str:
    while True:
        # 52:54:00 is the prefix QEMU and libvirt use for virtual cards.
        mac = "52:54:00:" + ":".join(f"{random.randint(0, 255):02x}" for _ in range(3))  # noqa: S311
        if mac not in taken:
            return mac


def _all_macs(c: libvirt.virConnect) -> set[str]:
    macs: set[str] = set()
    for dom in c.listAllDomains():
        root = etree.fromstring(
            dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE).encode(), parser=_PARSER
        )
        macs.update(m.get("address", "") for m in root.iterfind("devices/interface/mac"))
    return macs


def add_nic(conn: LibvirtConnection, uuid: str, network: str, model: NicModel) -> Nic:
    def op(c: libvirt.virConnect) -> Nic:
        if network not in {n.name() for n in c.listAllNetworks()}:
            raise ApiException(404, "libvirt.no_network", f"network {network} not found")
        dom, root = _domain(c, uuid)
        devices = root.find("devices")
        if devices is None:
            devices = etree.SubElement(root, "devices")
        interfaces = devices.findall("interface")
        if len(interfaces) >= MAX_NICS:
            raise ApiException(422, "vm.too_many_nics", f"at most {MAX_NICS} network cards")
        used = {t.get("dev") for t in devices.iterfind("interface/target")}
        index = next(i for i in range(64) if nic_target(uuid, i) not in used)
        mac = _new_mac(_all_macs(c))
        iface = etree.Element("interface", type="network")
        etree.SubElement(iface, "mac", address=mac)
        etree.SubElement(iface, "source", network=network)
        etree.SubElement(iface, "model", type=model)
        etree.SubElement(iface, "target", dev=nic_target(uuid, index))
        xml = etree.tostring(iface).decode()
        if dom.isActive():
            dom.attachDeviceFlags(xml, libvirt.VIR_DOMAIN_AFFECT_LIVE)
        anchor = interfaces[-1] if interfaces else None
        if anchor is not None:
            anchor.addnext(iface)
        else:
            devices.append(iface)
        c.defineXML(etree.tostring(root).decode())
        return Nic(mac, network, model, nic_target(uuid, index), True)

    return conn.run(op)


def _find_nic(root: etree._Element, mac: str) -> etree._Element:
    for iface in root.iterfind("devices/interface"):
        m = iface.find("mac")
        if m is not None and m.get("address", "").lower() == mac.lower():
            return iface
    raise ApiException(404, "vm.no_nic", f"No network card {mac}")


def remove_nic(conn: LibvirtConnection, uuid: str, mac: str) -> None:
    def op(c: libvirt.virConnect) -> None:
        dom, root = _domain(c, uuid)
        iface = _find_nic(root, mac)
        if dom.isActive():
            live = etree.fromstring(dom.XMLDesc(0).encode(), parser=_PARSER)
            dom.detachDeviceFlags(
                etree.tostring(_find_nic(live, mac)).decode(), libvirt.VIR_DOMAIN_AFFECT_LIVE
            )
        iface.getparent().remove(iface)  # type: ignore[union-attr]
        c.defineXML(etree.tostring(root).decode())

    conn.run(op)


def new_mac(conn: LibvirtConnection, uuid: str, mac: str) -> str:
    """Give a card a new address, unused by every VM; the VM must be off."""

    def op(c: libvirt.virConnect) -> str:
        dom, root = _domain(c, uuid)
        if dom.isActive():
            # The card would keep its old address until a cold restart.
            raise ApiException(409, "vm.not_shut_off", "Power the virtual machine off first")
        el = _find_nic(root, mac).find("mac")
        address = _new_mac(_all_macs(c))
        el.set("address", address)  # type: ignore[union-attr]
        c.defineXML(etree.tostring(root).decode())
        return address

    return conn.run(op)


def _edit_nic(
    iface: etree._Element,
    network: str | None,
    model: str | None,
    connected: bool | None,
) -> None:
    if network is not None:
        iface.set("type", "network")
        source = iface.find("source")
        if source is None:
            source = etree.SubElement(iface, "source")
        source.attrib.clear()
        source.set("network", network)
    if model is not None:
        el = iface.find("model")
        if el is None:
            el = etree.SubElement(iface, "model")
        el.set("type", model)
    if connected is not None:
        link = iface.find("link")
        if link is None:
            link = etree.SubElement(iface, "link")
        link.set("state", "up" if connected else "down")


def update_nic(
    conn: LibvirtConnection,
    uuid: str,
    mac: str,
    *,
    network: str | None = None,
    model: NicModel | None = None,
    connected: bool | None = None,
) -> bool:
    """Change a card; True if part of the change waits for the next boot."""

    def op(c: libvirt.virConnect) -> bool:
        if network is not None and network not in {n.name() for n in c.listAllNetworks()}:
            raise ApiException(404, "libvirt.no_network", f"network {network} not found")
        dom, root = _domain(c, uuid)
        _edit_nic(_find_nic(root, mac), network, model, connected)
        restart = False
        if dom.isActive():
            live = _find_nic(etree.fromstring(dom.XMLDesc(0).encode(), parser=_PARSER), mac)
            live_model = live.find("model")
            # The cable and the network change live; a new model needs a new device.
            restart = model is not None and (live_model is None or live_model.get("type") != model)
            if network is not None or connected is not None:
                _edit_nic(live, network, None, connected)
                dom.updateDeviceFlags(etree.tostring(live).decode(), libvirt.VIR_DOMAIN_AFFECT_LIVE)
        c.defineXML(etree.tostring(root).decode())
        return restart

    return conn.run(op)


def add_cdrom(conn: LibvirtConnection, config: Config, uuid: str, iso: str | None) -> bool:
    path = None
    if iso:
        path = str(confine(iso, config))
        if not in_iso_library(path, config):
            raise ApiException(403, "path.not_allowed", f"{iso} is not in an ISO library")
    return add_cdrom_drive(conn, uuid, path)[1]


def add_cdrom_drive(conn: LibvirtConnection, uuid: str, path: str | None) -> tuple[str, bool]:
    """Add a SATA CD/DVD drive to the config; returns its target and whether a restart is due."""

    def op(c: libvirt.virConnect) -> tuple[str, bool]:
        dom, root = _domain(c, uuid)
        devices = root.find("devices")
        if devices is None:
            devices = etree.SubElement(root, "devices")
        used = {t.get("dev") for t in devices.iterfind("disk/target")}
        target = next(f"sd{chr(97 + i)}" for i in range(26) if f"sd{chr(97 + i)}" not in used)
        disk = etree.Element("disk", type="file", device="cdrom")
        etree.SubElement(disk, "driver", name="qemu", type="raw")
        if path:
            etree.SubElement(disk, "source", file=path)
        etree.SubElement(disk, "target", dev=target, bus="sata")
        etree.SubElement(disk, "readonly")
        last = devices.findall("disk")
        if last:
            last[-1].addnext(disk)
        else:
            devices.insert(0, disk)
        c.defineXML(etree.tostring(root).decode())
        # SATA drives cannot be added to a running machine.
        return target, bool(dom.isActive())

    return conn.run(op)


def set_media(conn: LibvirtConnection, uuid: str, target: str, path: str | None) -> None:
    """Insert or eject the image of a CD/DVD drive, live when the drive is live.

    Callers check where path may come from (ISO libraries, guest tools folder).
    """

    def drive(xml: str) -> etree._Element | None:
        root = etree.fromstring(xml.encode(), parser=_PARSER)
        for disk in root.iterfind("devices/disk[@device='cdrom']"):
            t = disk.find("target")
            if t is not None and t.get("dev") == target:
                return disk
        return None

    def op(c: libvirt.virConnect) -> None:
        dom = c.lookupByUUIDString(uuid)
        live = drive(dom.XMLDesc(0)) if dom.isActive() else None
        config = drive(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)) if dom.isPersistent() else None
        for disk, flag in (
            (live, libvirt.VIR_DOMAIN_AFFECT_LIVE),
            (config, libvirt.VIR_DOMAIN_AFFECT_CONFIG),
        ):
            if disk is None:
                continue
            for old in disk.findall("source"):
                disk.remove(old)
            if path is not None:
                source = etree.Element("source", file=path)
                driver = disk.find("driver")
                disk.insert(list(disk).index(driver) + 1 if driver is not None else 0, source)
            dom.updateDeviceFlags(etree.tostring(disk).decode(), flag)
        if live is None and config is None:
            raise ApiException(404, "vm.no_cdrom", f"No CD/DVD drive {target}")

    conn.run(op)


def remove_cdrom(conn: LibvirtConnection, uuid: str, target: str) -> bool:
    def op(c: libvirt.virConnect) -> bool:
        dom, root = _domain(c, uuid)
        for disk in root.iterfind("devices/disk[@device='cdrom']"):
            t = disk.find("target")
            if t is not None and t.get("dev") == target:
                disk.getparent().remove(disk)  # type: ignore[union-attr]
                c.defineXML(etree.tostring(root).decode())
                return bool(dom.isActive())
        raise ApiException(404, "vm.no_cdrom", f"No CD/DVD drive {target}")

    return conn.run(op)
