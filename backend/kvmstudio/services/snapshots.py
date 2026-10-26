"""Snapshots (F-80 to F-82): take, restore and delete, with a name and a description.

libvirt 12 takes internal qcow2 snapshots of UEFI VMs whose firmware variables
are stored as qcow2, TPM included: powered off (disks), or running (disks and
memory, the VM goes on). Where libvirt refuses (raw disk or raw NVRAM), its
error is reported as is; limits() lets the interface say so beforehand.

Limits of libvirt 12 met in testing: a running VM is only snapshotted with its
memory (a disk-only snapshot is an external one, whose restore leaves overlay
files behind); a powered-off snapshot holds no TPM state; while the memory is
written, job statistics wait for the end and the job cannot be aborted.

A VM whose disks back linked clones is never snapshotted, restored or cleaned:
writing to its disk would damage the clones.
"""

from __future__ import annotations

import contextlib
import re
import threading
from dataclasses import dataclass
from typing import Any

import libvirt
from lxml import etree

from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection
from .clone import linked_clones
from .tasks import Cancelled, Task

_PARSER = etree.XMLParser(resolve_entities=False, remove_blank_text=True)
# What QEMU takes in the job name of a running VM's snapshot
# ("internal-snapshot-save-<name>"), and libvirt refuses a leading dot.
NAME_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}$")
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


@dataclass(frozen=True, slots=True)
class Limits:
    running: bool
    # Targets of the disks libvirt cannot snapshot internally (not qcow2).
    raw_disks: list[str]
    # UEFI variables in a raw file (VMs made before the qcow2 NVRAM).
    raw_nvram: bool
    tpm: bool


def limits(conn: LibvirtConnection, uuid: str) -> Limits:
    def op(c: libvirt.virConnect) -> Limits:
        dom = c.lookupByUUIDString(uuid)
        root = etree.fromstring(dom.XMLDesc(0).encode(), parser=_PARSER)
        raw = []
        for disk in root.iterfind("devices/disk[@device='disk']"):
            driver, target = disk.find("driver"), disk.find("target")
            if driver is None or driver.get("type") != "qcow2":
                raw.append(target.get("dev", "") if target is not None else "")
        nvram = root.find("os/nvram")
        raw_nvram = nvram is not None and nvram.get("format", "raw") != "qcow2"
        state = dom.state()[0]
        running = state in (libvirt.VIR_DOMAIN_RUNNING, libvirt.VIR_DOMAIN_PAUSED)
        return Limits(running, raw, raw_nvram, root.find("devices/tpm") is not None)

    return conn.run(op)


def _no_linked_clones(conn: LibvirtConnection, uuid: str) -> None:
    if clones := linked_clones(conn, uuid):
        raise ApiException(
            409,
            "snapshot.linked_clones",
            "Linked clones use this VM's disks, which must not change: " + ", ".join(clones),
        )


def check_new(conn: LibvirtConnection, uuid: str, name: str, description: str, memory: bool) -> str:
    """Refuses at once what libvirt would refuse later; returns the name to use."""
    name = name.strip()
    if not NAME_RE.match(name):
        raise ApiException(422, "snapshot.bad_name", f"invalid snapshot name: {name!r}")
    if len(description) > MAX_DESCRIPTION:
        raise ApiException(422, "snapshot.bad_description", "The description is too long")
    _no_linked_clones(conn, uuid)
    if limits(conn, uuid).running and not memory:
        raise ApiException(
            409,
            "snapshot.memory_required",
            "libvirt only takes an internal snapshot of a running VM with its memory",
        )
    if name in conn.run(lambda c: c.lookupByUUIDString(uuid).snapshotListNames(0)):
        raise ApiException(409, "snapshot.exists", f"{name} already exists")
    return name


def take(
    conn: LibvirtConnection, uuid: str, name: str, description: str, task: Task | None = None
) -> dict[str, Any]:
    """Takes the snapshot (memory included when the VM runs); a task follows it.

    Cancelling cannot stop libvirt: the snapshot is deleted once it is written.
    """
    xml = etree.Element("domainsnapshot")
    etree.SubElement(xml, "name").text = name
    if description:
        etree.SubElement(xml, "description").text = description
    done = threading.Event()

    def watch() -> None:
        # Progress where libvirt reports it; libvirt 12 makes this call wait for
        # the end of an internal snapshot, so the interface shows no percentage.
        while task is not None and not done.wait(1.0):
            with contextlib.suppress(libvirt.libvirtError):
                stats = conn.run(lambda c: c.lookupByUUIDString(uuid).jobStats(0))
                total = stats.get("memory_total") or 0
                if total and not done.is_set():
                    task.progress = min(0.99, stats.get("memory_processed", 0) / total)

    threading.Thread(target=watch, name="snapshot-progress", daemon=True).start()
    try:
        conn.run(
            lambda c: c.lookupByUUIDString(uuid).snapshotCreateXML(etree.tostring(xml).decode(), 0)
        )
    finally:
        done.set()
    if task is not None and task.cancel.is_set():
        delete(conn, uuid, name)
        raise Cancelled
    return {"name": name}


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
