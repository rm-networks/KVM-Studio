"""Format and backing chain of a disk image KVM Studio did not just create.

The format is never read from the file: a raw disk is written freely by its
VM, which could put a qcow2 header there pointing at any file of the host.
It comes from the libvirt definition of the VM that uses the file, or else
from the file name (qcow2 for .qcow2, raw for anything else).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import libvirt
from lxml import etree

from ..config import Config
from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection
from ..paths import in_library, resolve
from . import domain_xml, qemu_img

log = logging.getLogger(__name__)


@dataclass(slots=True)
class KnownDisk:
    format: str
    uuids: set[str] = field(default_factory=set)


def known_disks(conn: LibvirtConnection) -> dict[Path, KnownDisk]:
    """Every file used as a disk by a libvirt domain, with its declared format."""

    def op(c: libvirt.virConnect) -> list[tuple[str, str]]:
        return [
            (d.UUIDString(), d.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)) for d in c.listAllDomains()
        ]

    found: dict[Path, KnownDisk] = {}
    for uuid, xml in conn.run(op):
        for disk in domain_xml.disks(xml):
            if disk.path and disk.source_type == "file" and disk.device == "disk":
                known = found.setdefault(resolve(disk.path), KnownDisk(disk.format))
                known.uuids.add(uuid)
    return found


def format_of(path: Path, known: dict[Path, KnownDisk]) -> str:
    """The declared format of a VM's disk, else the one its name stands for."""
    disk = known.get(resolve(path))
    return disk.format if disk is not None else qemu_img.format_from_name(path)


def checked_chain(path: Path, fmt: str, config: Config, *, confined: bool) -> list[str]:
    """The backing chain of a disk about to be used or copied.

    The owner may use any base, the chain is only logged. For a guest, every
    file of the chain must be in the library; nothing outside it is opened.
    """
    chain = qemu_img.backing_files(
        path, fmt, stop=(lambda p: not in_library(p, config)) if confined else None
    )
    if chain is None:
        raise ApiException(422, "disk.unreadable_image", f"{path} is not a readable {fmt} image")
    if chain:
        log.info("disk %s is based on %s", path, " -> ".join(chain))
    if confined and any(not in_library(p, config) for p in chain):
        raise ApiException(
            403, "path.not_allowed", f"the backing files of {path} are outside the library"
        )
    return chain


def not_another_vms(path: Path, known: dict[Path, KnownDisk], uuid: str | None = None) -> None:
    """For a guest: refuses the disk of a VM other than uuid."""
    disk = known.get(resolve(path))
    if disk is not None and disk.uuids - ({uuid} if uuid else set()):
        raise ApiException(403, "disk.in_use", f"{path} is a disk of another virtual machine")


def set_backing_store(disk: etree._Element, fmt: str, chain: list[str]) -> None:
    """An empty <backingStore/> when a qcow2 disk has no base.

    Without it libvirt reads the chain from the image header when the VM
    starts; with it, the disk is used alone whatever the header says.
    """
    for store in disk.findall("backingStore"):
        disk.remove(store)
    if fmt == "qcow2" and not chain:
        store = etree.Element("backingStore")
        target = disk.find("target")
        if target is not None:
            target.addprevious(store)
        else:
            disk.append(store)
