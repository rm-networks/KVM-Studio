"""Disk utilities (F-44): size of a disk and Expand.

Expanding only grows the virtual disk: the partition and the file system in
the guest are grown by the user afterwards. A running VM is expanded by
libvirt (virDomainBlockResize, the guest sees the new size at once). A
powered-off one too: its file belongs to QEMU's account, so the user cannot
resize it; libvirt does it as a storage volume, of the pool that holds the
folder or else of a transient pool made for the occasion. Only disks under
the KVM-Studio root, and not a disk that linked clones are built on.
"""

from __future__ import annotations

import uuid as uuidlib
from dataclasses import dataclass
from pathlib import Path

import libvirt
from lxml import etree

from ..config import Config
from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection
from ..paths import in_library
from . import qemu_img
from .clone import linked_clones

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
