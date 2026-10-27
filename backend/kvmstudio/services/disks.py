"""Hard disks of a VM (F-44): size, Expand, Add and Remove.

Expanding only grows the virtual disk: the partition and the file system in
the guest are grown by the user afterwards. A running VM is expanded by
libvirt (virDomainBlockResize, the guest sees the new size at once). A
powered-off one too: its file belongs to QEMU's account, so the user cannot
resize it; libvirt does it as a storage volume, of the pool that holds the
folder or else of a transient pool made for the occasion. Only disks under
the KVM-Studio root, and not a disk that linked clones are built on.

Add: a new image in the VM folder, or an existing file the owner picks
anywhere (a guest only inside the library). A running VM gets it live when
QEMU accepts the hotplug (virtio, SCSI); otherwise nothing is changed and
the VM must be powered off first. Remove keeps the file unless asked, and
then deletes only that file, inside the library and used by no other VM.
"""

from __future__ import annotations

import time
import uuid as uuidlib
from dataclasses import dataclass
from pathlib import Path

import libvirt
from lxml import etree

from ..config import Config
from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection
from ..paths import in_library, library_root
from ..xml.profiles import DiskBus
from . import qemu_img
from .clone import linked_clones
from .create import existing_disk
from .library import _snapshot, placement_of

GIB = 1024**3
MAX_GIB = 64 * 1024

_PARSER = etree.XMLParser(resolve_entities=False)


@dataclass(frozen=True, slots=True)
class DiskSize:
    target: str
    path: str
    capacity: int  # bytes the guest sees
    allocation: int  # bytes used on the host
    expandable: bool
    # The file can go with the disk: in the library, used by no other VM.
    deletable: bool = False


def _find(conn: LibvirtConnection, uuid: str, target: str) -> tuple[Path, bool]:
    def op(c: libvirt.virConnect) -> tuple[str | None, bool]:
        dom = c.lookupByUUIDString(uuid)
        root = etree.fromstring(dom.XMLDesc(0).encode(), parser=_PARSER)
        for disk in root.iterfind("devices/disk[@device='disk']"):
            dev = disk.find("target")
            source = disk.find("source")
            if dev is not None and dev.get("dev") == target and source is not None:
                return source.get("file"), bool(dom.isActive())
        return None, False

    path, active = conn.run(op)
    if not path:
        raise ApiException(404, "disk.not_found", f"no disk {target} backed by a file")
    return Path(path), active


def size(conn: LibvirtConnection, config: Config, uuid: str, target: str) -> DiskSize:
    path, _active = _find(conn, uuid, target)
    info = qemu_img.image_info(path) or {}
    return DiskSize(
        target=target,
        path=str(path),
        capacity=int(info.get("virtual-size", 0)),
        allocation=int(info.get("actual-size", 0)),
        expandable=in_library(str(path), config),
        deletable=_deletable(conn, config, uuid, path),
    )


def expand(conn: LibvirtConnection, config: Config, uuid: str, target: str, gib: int) -> DiskSize:
    path, active = _find(conn, uuid, target)
    if not in_library(str(path), config):
        raise ApiException(403, "path.not_allowed", f"{path} is outside the KVM-Studio folder")
    if clones := linked_clones(conn, uuid):
        raise ApiException(
            409, "disk.linked_clones", "Linked clones are built on this disk: " + ", ".join(clones)
        )
    current = size(conn, config, uuid, target).capacity
    wanted = gib * GIB
    if not 0 < gib <= MAX_GIB or wanted <= current:
        raise ApiException(
            422, "disk.not_larger", f"the new size must be larger than {current / GIB:.1f} GiB"
        )
    if active:
        conn.run(
            lambda c: c.lookupByUUIDString(uuid).blockResize(
                target, wanted, libvirt.VIR_DOMAIN_BLOCK_RESIZE_BYTES
            )
        )
    else:
        try:
            conn.run(lambda c: _resize_volume(c, path, wanted))
        except libvirt.libvirtError as exc:
            raise ApiException(409, "disk.resize_failed", exc.get_error_message() or "") from exc
    return size(conn, config, uuid, target)


def _resize_volume(c: libvirt.virConnect, path: Path, wanted: int) -> None:
    try:
        c.storageVolLookupByPath(str(path)).resize(wanted, 0)
        return
    except libvirt.libvirtError:
        pass  # in no pool
    pool_xml = etree.Element("pool", type="dir")
    etree.SubElement(pool_xml, "name").text = f"kvmstudio-resize-{uuidlib.uuid4().hex[:8]}"
    etree.SubElement(etree.SubElement(pool_xml, "target"), "path").text = str(path.parent)
    pool = c.storagePoolCreateXML(etree.tostring(pool_xml).decode(), 0)
    try:
        pool.storageVolLookupByName(path.name).resize(wanted, 0)
    finally:
        pool.destroy()


# Add and Remove

ADD_BUSES: tuple[DiskBus, ...] = ("virtio", "sata", "scsi")
UNPLUG_WAIT = 15.0  # seconds
_PREFIX = {"virtio": "vd", "sata": "sd", "scsi": "sd"}


@dataclass(frozen=True, slots=True)
class AddedDisk:
    target: str
    path: str


def _users(conn: LibvirtConnection, path: Path, but: str) -> list[str]:
    """Other VMs whose disks (or snapshots of them) point at path."""
    wanted = str(path)
    names = []
    for uuid, name, _active, xml in _snapshot(conn):
        root = etree.fromstring(xml.encode(), parser=_PARSER)
        files = {s.get("file") for s in root.iterfind("devices/disk/source")}
        if uuid != but and wanted in files:
            names.append(name)
    return names


def _deletable(conn: LibvirtConnection, config: Config, uuid: str, path: Path) -> bool:
    return (
        in_library(str(path), config)
        and not _users(conn, path, uuid)
        and not linked_clones(conn, uuid)
    )


def default_dir(conn: LibvirtConnection, config: Config, uuid: str) -> Path:
    """Where a new disk goes: the VM folder in the library."""
    place = placement_of(conn, config, uuid)
    if place.vm_dir is not None:
        return place.vm_dir
    root = library_root(config)
    if root is None:
        raise ApiException(409, "library.no_location", "No folder for virtual machines is set")
    name = conn.run(lambda c: c.lookupByUUIDString(uuid).name())
    return root / place.folder / name if place.folder else root / name


def _new_path(folder: Path, name: str, fmt: str) -> Path:
    for i in range(1, 100):
        path = folder / f"{name}-{i}.{fmt}"
        if not path.exists():
            return path
    raise ApiException(409, "library.exists", f"{folder} already holds 99 extra disks")


def _target(bus: str, *roots: etree._Element) -> str:
    prefix = _PREFIX[bus]
    used = {t.get("dev") for root in roots for t in root.iterfind("devices/disk/target")}
    for i in range(26):
        name = prefix + chr(97 + i)
        if name not in used:
            return name
    raise ApiException(422, "vm.too_many_disks", f"no free {bus} slot")


def _disk_element(path: Path, fmt: str, bus: str, target: str) -> etree._Element:
    disk = etree.Element("disk", type="file", device="disk")
    etree.SubElement(disk, "driver", name="qemu", type=fmt, discard="unmap")
    etree.SubElement(disk, "source", file=str(path))
    etree.SubElement(disk, "target", dev=target, bus=bus)
    return disk


def add(
    conn: LibvirtConnection,
    config: Config,
    uuid: str,
    *,
    bus: DiskBus,
    size_gib: int = 0,
    fmt: str = "qcow2",
    existing: str | None = None,
    confined: bool = False,
) -> AddedDisk:
    """A new or existing disk; live as well when the VM runs and QEMU accepts it."""
    if bus not in ADD_BUSES:
        raise ApiException(422, "vm.bad_bus", f"{bus} disks cannot be added")
    created: Path | None = None
    if existing is not None:
        path = existing_disk(existing, config, "in_place", confined=confined)
        fmt = "qcow2" if qemu_img.is_qcow2(path) else "raw"
    else:
        if not 0 < size_gib <= MAX_GIB:
            raise ApiException(422, "disk.bad_size", f"size between 1 and {MAX_GIB} GiB")
        folder = default_dir(conn, config, uuid)
        name = conn.run(lambda c: c.lookupByUUIDString(uuid).name())
        path = _new_path(folder, name, fmt)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            qemu_img.create(path, fmt, size_gib, preallocate=False)
        except (qemu_img.QemuImgError, OSError) as exc:
            raise ApiException(500, "vm.disk_failed", str(exc)) from exc
        created = path

    def op(c: libvirt.virConnect) -> str:
        dom = c.lookupByUUIDString(uuid)
        root = etree.fromstring(
            dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE).encode(), parser=_PARSER
        )
        devices = root.find("devices")
        if devices is None:
            devices = etree.SubElement(root, "devices")
        active = bool(dom.isActive())
        # Free in the config and, when it runs, in the live VM too.
        live = [etree.fromstring(dom.XMLDesc(0).encode(), parser=_PARSER)] if active else []
        target = _target(bus, root, *live)
        disk = _disk_element(path, fmt, bus, target)
        if bus == "scsi" and devices.find("controller[@type='scsi']") is None:
            controller = etree.Element("controller", type="scsi", model="virtio-scsi")
            if active:
                dom.attachDeviceFlags(
                    etree.tostring(controller).decode(), libvirt.VIR_DOMAIN_AFFECT_LIVE
                )
            devices.append(controller)
        if active:
            # SATA has no hotplug: QEMU refuses, and the VM stays as it was.
            dom.attachDeviceFlags(etree.tostring(disk).decode(), libvirt.VIR_DOMAIN_AFFECT_LIVE)
        disks = devices.findall("disk")
        if disks:
            disks[-1].addnext(disk)
        else:
            devices.insert(0, disk)
        c.defineXML(etree.tostring(root).decode())
        return target

    try:
        target = conn.run(op)
    except libvirt.libvirtError as exc:
        if created is not None:
            created.unlink(missing_ok=True)
        raise ApiException(
            409, "disk.hotplug_refused", exc.get_error_message() or "hotplug refused"
        ) from exc
    except BaseException:
        if created is not None:
            created.unlink(missing_ok=True)
        raise
    return AddedDisk(target, str(path))


def _live_disk(dom: libvirt.virDomain, target: str) -> etree._Element | None:
    live = etree.fromstring(dom.XMLDesc(0).encode(), parser=_PARSER)
    for el in live.iterfind("devices/disk[@device='disk']"):
        dev = el.find("target")
        if dev is not None and dev.get("dev") == target:
            return el
    return None


def remove(
    conn: LibvirtConnection, config: Config, uuid: str, target: str, *, delete_file: bool
) -> list[str]:
    """Take a disk out of the VM; with delete_file, its file too. Returns the files deleted.

    A running guest is asked to release the disk first; the config and the file
    change only once it has, so a guest that keeps it leaves everything as it was.
    """
    path, active = _find_config(conn, uuid, target)
    if delete_file and (path is None or not _deletable(conn, config, uuid, path)):
        raise ApiException(409, "disk.not_deletable", f"the file of {target} cannot be deleted")

    if active:

        def unplug(c: libvirt.virConnect) -> None:
            dom = c.lookupByUUIDString(uuid)
            el = _live_disk(dom, target)
            if el is not None:
                dom.detachDeviceFlags(etree.tostring(el).decode(), libvirt.VIR_DOMAIN_AFFECT_LIVE)

        try:
            conn.run(unplug)
        except libvirt.libvirtError as exc:
            raise ApiException(
                409, "disk.unplug_refused", exc.get_error_message() or "unplug refused"
            ) from exc
        # The guest acknowledges the unplug on its own time.
        deadline = time.monotonic() + UNPLUG_WAIT
        while conn.run(lambda c: _live_disk(c.lookupByUUIDString(uuid), target)) is not None:
            if time.monotonic() > deadline:
                raise ApiException(409, "disk.unplug_refused", "the guest did not release the disk")
            time.sleep(0.5)

    def drop(c: libvirt.virConnect) -> None:
        dom = c.lookupByUUIDString(uuid)
        root = etree.fromstring(
            dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE).encode(), parser=_PARSER
        )
        for disk in root.iterfind("devices/disk[@device='disk']"):
            dev = disk.find("target")
            if dev is not None and dev.get("dev") == target:
                disk.getparent().remove(disk)  # type: ignore[union-attr]
                c.defineXML(etree.tostring(root).decode())
                return

    conn.run(drop)
    if not delete_file or path is None:
        return []
    try:
        path.unlink()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise ApiException(500, "disk.delete_failed", str(exc)) from exc
    return [str(path)]


def _find_config(conn: LibvirtConnection, uuid: str, target: str) -> tuple[Path | None, bool]:
    def op(c: libvirt.virConnect) -> tuple[Path | None, bool]:
        dom = c.lookupByUUIDString(uuid)
        root = etree.fromstring(
            dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE).encode(), parser=_PARSER
        )
        for disk in root.iterfind("devices/disk[@device='disk']"):
            dev = disk.find("target")
            source = disk.find("source")
            if dev is not None and dev.get("dev") == target:
                file = source.get("file") if source is not None else None
                return (Path(file) if file else None), bool(dom.isActive())
        raise ApiException(404, "disk.not_found", f"no disk {target}")

    return conn.run(op)
