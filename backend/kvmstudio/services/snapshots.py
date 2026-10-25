"""Snapshots (F-80 to F-82): take, restore and delete, with a name and a description.

libvirt 12 takes internal qcow2 snapshots of UEFI VMs whose firmware variables
are stored as qcow2, TPM included: powered off (disks), or running (disks and
memory, the VM goes on). Where libvirt refuses (raw disk or raw NVRAM), its
error is reported as is.

A VM whose disks back linked clones is never snapshotted, restored or cleaned:
writing to its disk would damage the clones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import libvirt
from lxml import etree

from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection
from .clone import linked_clones

_PARSER = etree.XMLParser(resolve_entities=False, remove_blank_text=True)
NAME_RE = re.compile(r"^[^/\\\x00-\x1f\x7f]{1,100}$")
MAX_DESCRIPTION = 2000


@dataclass(frozen=True, slots=True)
class Snapshot:
    name: str
    description: str
    created: int  # seconds since the epoch
    state: str  # state of the VM in the snapshot: running, shutoff, paused...
    parent: str | None
    current: bool


def _describe(snap: libvirt.virDomainSnapshot, current: str | None) -> Snapshot:
    root = etree.fromstring(snap.getXMLDesc(0).encode(), parser=_PARSER)
    try:
        parent = snap.getParent(0).getName()
    except libvirt.libvirtError:
        parent = None
    return Snapshot(
        name=snap.getName(),
        description=root.findtext("description", ""),
        created=int(root.findtext("creationTime", "0") or 0),
        state=root.findtext("state", ""),
        parent=parent,
        current=snap.getName() == current,
    )


def _current(dom: libvirt.virDomain) -> str | None:
    try:
        return dom.snapshotCurrent(0).getName() if dom.hasCurrentSnapshot(0) else None
    except libvirt.libvirtError:
        return None


def list_snapshots(conn: LibvirtConnection, uuid: str) -> list[Snapshot]:
    def op(c: libvirt.virConnect) -> list[Snapshot]:
        dom = c.lookupByUUIDString(uuid)
        current = _current(dom)
        snaps = [_describe(s, current) for s in dom.listAllSnapshots(0)]
        return sorted(snaps, key=lambda s: (s.created, s.name))

    return conn.run(op)


def _no_linked_clones(conn: LibvirtConnection, uuid: str) -> None:
    if clones := linked_clones(conn, uuid):
        raise ApiException(
            409,
            "snapshot.linked_clones",
            "Linked clones use this VM's disks, which must not change: " + ", ".join(clones),
        )


def take(conn: LibvirtConnection, uuid: str, name: str, description: str) -> Snapshot:
    name = name.strip()
    if not NAME_RE.match(name):
        raise ApiException(422, "snapshot.bad_name", f"invalid snapshot name: {name!r}")
    if len(description) > MAX_DESCRIPTION:
        raise ApiException(422, "snapshot.bad_description", "The description is too long")
    _no_linked_clones(conn, uuid)
    xml = etree.Element("domainsnapshot")
    etree.SubElement(xml, "name").text = name
    if description:
        etree.SubElement(xml, "description").text = description

    def op(c: libvirt.virConnect) -> Snapshot:
        dom = c.lookupByUUIDString(uuid)
        if name in dom.snapshotListNames(0):
            raise ApiException(409, "snapshot.exists", f"{name} already exists")
        snap = dom.snapshotCreateXML(etree.tostring(xml).decode(), 0)
        return _describe(snap, _current(dom))

    return conn.run(op)


def revert(conn: LibvirtConnection, uuid: str, name: str) -> None:
    """Back to the snapshot: what changed since is lost (asked in the interface)."""
    _no_linked_clones(conn, uuid)

    def op(c: libvirt.virConnect) -> None:
        dom = c.lookupByUUIDString(uuid)
        dom.revertToSnapshot(dom.snapshotLookupByName(name, 0), 0)

    conn.run(op)


def delete(conn: LibvirtConnection, uuid: str, name: str) -> None:
    """Forget the snapshot; its children are kept (attached to its parent)."""
    _no_linked_clones(conn, uuid)
    conn.run(lambda c: c.lookupByUUIDString(uuid).snapshotLookupByName(name, 0).delete(0))


def count(conn: LibvirtConnection, uuid: str) -> int:
    return conn.run(lambda c: c.lookupByUUIDString(uuid).snapshotNum(0))
