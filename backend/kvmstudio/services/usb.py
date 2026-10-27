"""USB storage of the host, connected to a running VM (Removable Devices).

Only USB devices with a mass storage interface are listed, with the disks the
kernel made of them: a SATA or NVMe disk is never on the USB bus, so it never
shows, removable or not. A device is passed by its bus and device numbers,
live only: it goes back to the host when the VM stops. libvirt gives QEMU the
device node (owner and SELinux label), so no root operation is needed here.

The host keeps what it uses: a device whose disk or partitions are mounted,
used as swap, or held by device mapper (LUKS, LVM) is refused, with the reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import libvirt
from lxml import etree

from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection

MASS_STORAGE = "08"
SYSFS = Path("/sys")
MOUNTINFO = Path("/proc/self/mountinfo")
SWAPS = Path("/proc/swaps")

_PARSER = etree.XMLParser(resolve_entities=False, remove_blank_text=True)


@dataclass(slots=True)
class UsbStorage:
    bus: int
    device: int
    vendor_id: str
    product_id: str
    name: str
    size: int  # bytes, all its disks
    disks: list[str] = field(default_factory=list)  # sdc, ...
    mountpoints: list[str] = field(default_factory=list)
    in_use: list[str] = field(default_factory=list)  # swap, dm-0 ...
    vm: str | None = None  # uuid of the running VM it is connected to
    vm_name: str | None = None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _unescape(field_: str) -> str:
    # mountinfo writes spaces, tabs and backslashes as octal escapes.
    return field_.encode().decode("unicode_escape").encode("latin-1").decode(errors="replace")


def _mounts(mountinfo: Path) -> dict[str, list[str]]:
    by_dev: dict[str, list[str]] = {}
    for line in _read(mountinfo).splitlines():
        parts = line.split()
        if len(parts) > 4:
            by_dev.setdefault(parts[2], []).append(_unescape(parts[4]))
    return by_dev


def _swaps(swaps: Path) -> set[str]:
    return {line.split()[0].rsplit("/", 1)[-1] for line in _read(swaps).splitlines()[1:] if line}


def _is_storage(dev: Path) -> bool:
    return any(
        _read(iface / "bInterfaceClass") == MASS_STORAGE for iface in dev.glob(f"{dev.name}:*")
    )


def host_devices(
    sysfs: Path = SYSFS, mountinfo: Path = MOUNTINFO, swaps: Path = SWAPS
) -> list[UsbStorage]:
    """USB mass storage devices plugged into the host, with their disks."""
    mounts = _mounts(mountinfo)
    swapped = _swaps(swaps)
    blocks = []
    for block in sorted((sysfs / "class" / "block").glob("*")):
        if (block / "partition").exists():
            continue
        blocks.append((block.name, block.resolve()))
    found = []
    for dev in sorted((sysfs / "bus" / "usb" / "devices").glob("*")):
        if ":" in dev.name or not (dev / "busnum").exists() or not _is_storage(dev):
            continue
        real = dev.resolve()
        usb = UsbStorage(
            bus=int(_read(dev / "busnum") or 0),
            device=int(_read(dev / "devnum") or 0),
            vendor_id=_read(dev / "idVendor"),
            product_id=_read(dev / "idProduct"),
            name=" ".join(p for p in (_read(dev / "manufacturer"), _read(dev / "product")) if p)
            or f"{_read(dev / 'idVendor')}:{_read(dev / 'idProduct')}",
            size=0,
        )
        for name, path in blocks:
            if real not in path.parents:
                continue
            node = sysfs / "class" / "block" / name
            usb.disks.append(name)
            usb.size += int(_read(node / "size") or 0) * 512
            parts = [node, *sorted(p for p in node.glob(f"{name}*") if (p / "partition").exists())]
            for part in parts:
                usb.mountpoints += mounts.get(_read(part / "dev"), [])
                if part.name in swapped:
                    usb.in_use.append(f"swap ({part.name})")
                usb.in_use += sorted(h.name for h in (part / "holders").glob("*"))
        found.append(usb)
    return found


def _usb_hostdevs(root: etree._Element) -> list[etree._Element]:
    return list(root.iterfind("devices/hostdev[@type='usb']"))


def _matches(hostdev: etree._Element, usb: UsbStorage) -> bool:
    address = hostdev.find("source/address")
    if address is not None and address.get("bus") and address.get("device"):
        return (int(address.get("bus", "0"), 0), int(address.get("device", "0"), 0)) == (
            usb.bus,
            usb.device,
        )
    vendor = hostdev.find("source/vendor")
    product = hostdev.find("source/product")
    return (
        vendor is not None
        and product is not None
        and int(vendor.get("id", "0"), 16) == int(usb.vendor_id or "0", 16)
        and int(product.get("id", "0"), 16) == int(usb.product_id or "0", 16)
    )


def list_devices(conn: LibvirtConnection) -> list[UsbStorage]:
    devices = host_devices()

    def op(c: libvirt.virConnect) -> None:
        for dom in c.listAllDomains(libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE):
            root = etree.fromstring(dom.XMLDesc(0).encode(), parser=_PARSER)
            for hostdev in _usb_hostdevs(root):
                for usb in devices:
                    if _matches(hostdev, usb):
                        usb.vm, usb.vm_name = dom.UUIDString(), dom.name()

    conn.run(op)
    return devices


def _find(devices: list[UsbStorage], bus: int, device: int) -> UsbStorage:
    for usb in devices:
        if (usb.bus, usb.device) == (bus, device):
            return usb
    raise ApiException(404, "usb.not_found", f"no USB storage device {bus}:{device}")


def _hostdev(usb: UsbStorage) -> etree._Element:
    hostdev = etree.Element("hostdev", mode="subsystem", type="usb", managed="yes")
    source = etree.SubElement(hostdev, "source")
    etree.SubElement(source, "address", bus=str(usb.bus), device=str(usb.device))
    return hostdev


def _has_usb_controller(root: etree._Element) -> bool:
    return any(c.get("model") != "none" for c in root.iterfind("devices/controller[@type='usb']"))


def _ensure_controller(c: libvirt.virConnect, dom: libvirt.virDomain) -> None:
    """A USB controller in the running VM, and in its config for the next starts."""
    live = etree.fromstring(dom.XMLDesc(0).encode(), parser=_PARSER)
    if _has_usb_controller(live):
        return
    inactive = etree.fromstring(
        dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE).encode(), parser=_PARSER
    )
    devices = inactive.find("devices")
    if devices is not None and not _has_usb_controller(inactive):
        for none in devices.findall("controller[@type='usb']"):
            devices.remove(none)
        etree.SubElement(devices, "controller", type="usb", model="qemu-xhci", ports="15")
        if dom.isPersistent():
            c.defineXML(etree.tostring(inactive).decode())
    controller = etree.Element("controller", type="usb", model="qemu-xhci", ports="15")
    try:
        dom.attachDeviceFlags(etree.tostring(controller).decode(), libvirt.VIR_DOMAIN_AFFECT_LIVE)
    except libvirt.libvirtError as exc:
        raise ApiException(
            409,
            "usb.no_controller",
            "The VM had no USB controller: one was added, ready at the next start. "
            + (exc.get_error_message() or ""),
        ) from exc


def connect(conn: LibvirtConnection, uuid: str, bus: int, device: int) -> UsbStorage:
    usb = _find(list_devices(conn), bus, device)
    if usb.vm == uuid:
        return usb
    if usb.vm is not None:
        raise ApiException(409, "usb.in_vm", f"Connected to {usb.vm_name}")
    if usb.mountpoints:
        raise ApiException(409, "usb.mounted", "Mounted on the host: " + ", ".join(usb.mountpoints))
    if usb.in_use:
        raise ApiException(409, "usb.in_use", "Used by the host: " + ", ".join(usb.in_use))

    def op(c: libvirt.virConnect) -> None:
        dom = c.lookupByUUIDString(uuid)
        if not dom.isActive():
            raise ApiException(409, "usb.vm_off", "Start the virtual machine first")
        _ensure_controller(c, dom)
        # Live only: the device goes back to the host when the VM stops.
        dom.attachDeviceFlags(
            etree.tostring(_hostdev(usb)).decode(), libvirt.VIR_DOMAIN_AFFECT_LIVE
        )

    try:
        conn.run(op)
    except libvirt.libvirtError as exc:
        raise ApiException(409, "usb.attach_failed", exc.get_error_message() or "") from exc
    usb.vm = uuid
    return usb


def disconnect(conn: LibvirtConnection, uuid: str, bus: int, device: int) -> None:
    usb = _find(list_devices(conn), bus, device)

    def op(c: libvirt.virConnect) -> None:
        dom = c.lookupByUUIDString(uuid)
        root = etree.fromstring(dom.XMLDesc(0).encode(), parser=_PARSER)
        for hostdev in _usb_hostdevs(root):
            if _matches(hostdev, usb):
                dom.detachDeviceFlags(
                    etree.tostring(hostdev).decode(), libvirt.VIR_DOMAIN_AFFECT_LIVE
                )
                return
        raise ApiException(404, "usb.not_connected", "Not connected to this virtual machine")

    try:
        conn.run(op)
    except libvirt.libvirtError as exc:
        raise ApiException(409, "usb.detach_failed", exc.get_error_message() or "") from exc
