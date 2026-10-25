"""Deleting a VM: work out exactly which files may go, then do only that.

Rules (spec 6.1.1): a file is deleted only if it sits inside the KVM Studio
library root, is not an ISO, is not used by another domain (directly or as a
backing file) and is not part of this VM's own backing chain.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import libvirt

from ..config import Config
from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection
from ..paths import in_iso_library, in_library, library_root, resolve
from . import domain_xml, qemu_img

KeepReason = Literal["no_library", "outside_library", "iso", "shared", "backing", "not_a_file"]


@dataclass(frozen=True, slots=True)
class KeptFile:
    path: str
    reason: KeepReason


@dataclass(slots=True)
class DeletionPlan:
    delete: list[str] = field(default_factory=list)
    keep: list[KeptFile] = field(default_factory=list)
    delete_nvram: bool = False


@dataclass(slots=True)
class DeletionReport:
    deleted: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def _snapshot(conn: LibvirtConnection, uuid: str) -> tuple[str, int, list[str]]:
    def op(c: libvirt.virConnect) -> tuple[str, int, list[str]]:
        dom = c.lookupByUUIDString(uuid)
        others = [d.XMLDesc(0) for d in c.listAllDomains() if d.UUIDString() != uuid]
        return dom.XMLDesc(0), dom.info()[0], others

    return conn.run(op)


def used_elsewhere(other_xmls: list[str], config: Config, own: set[str]) -> set[str]:
    """Every file another domain needs: its disks, their backing chains, its NVRAM."""
    used: set[str] = set()
    for xml in other_xmls:
        for disk in domain_xml.disks(xml):
            if disk.path:
                used.add(str(resolve(disk.path)))
                if chain := qemu_img.backing_files(Path(disk.path)):
                    used.update(chain)
            used.update(str(resolve(p)) for p in disk.backing_paths)
        if nvram := domain_xml.nvram_path(xml):
            used.add(str(resolve(nvram)))
    # Images inside the library that are not ours may be overlays of our files.
    root = library_root(config)
    if root is not None and root.is_dir():
        for image in root.rglob("*"):
            if str(image.resolve()) in own or not image.is_file() or not qemu_img.is_qcow2(image):
                continue
            used.update(qemu_img.backing_files(image) or [])
    return used


def _no_linked_clones(conn: LibvirtConnection, uuid: str) -> None:
    """Deleting the files of a VM would break the clones whose disks are overlays of them."""
    from .clone import linked_clones

    if clones := linked_clones(conn, uuid):
        raise ApiException(
            409, "vm.has_linked_clones", "Linked clones depend on it: " + ", ".join(clones)
        )


def plan_deletion(conn: LibvirtConnection, uuid: str, config: Config) -> DeletionPlan:
    _no_linked_clones(conn, uuid)
    xml, _state, others = _snapshot(conn, uuid)
    return plan_files(xml, others, config)


def plan_files(xml: str, others: list[str], config: Config) -> DeletionPlan:
    plan = DeletionPlan()
    disks = domain_xml.disks(xml)
    own = {str(resolve(d.path)) for d in disks if d.path}
    used = used_elsewhere(others, config, own)
    has_library = library_root(config) is not None
    seen: set[str] = set()

    def keep(path: str, reason: KeepReason) -> None:
        if path not in seen:
            seen.add(path)
            plan.keep.append(KeptFile(path, reason))

    for disk in disks:
        if not disk.path:
            continue
        path = str(resolve(disk.path)) if disk.source_type == "file" else disk.path
        if disk.source_type != "file":
            keep(path, "not_a_file")
        elif disk.device == "cdrom" or in_iso_library(path, config):
            keep(path, "iso")
        elif not has_library:
            keep(path, "no_library")
        elif not in_library(path, config):
            keep(path, "outside_library")
        elif path in used:
            keep(path, "shared")
        elif path not in seen:
            seen.add(path)
            plan.delete.append(path)
        if disk.source_type == "file":
            for backing in qemu_img.backing_files(Path(path)) or disk.backing_paths:
                keep(str(resolve(backing)), "backing")

    nvram = domain_xml.nvram_path(xml)
    if nvram:
        path = str(resolve(nvram))
        if not in_library(path, config):
            keep(path, "no_library" if not has_library else "outside_library")
        elif path in used:
            keep(path, "shared")
        else:
            plan.delete.append(path)
            plan.delete_nvram = True
    return plan


def delete_vm(
    conn: LibvirtConnection, uuid: str, config: Config, *, delete_files: bool
) -> tuple[DeletionPlan, DeletionReport]:
    xml, state, others = _snapshot(conn, uuid)
    if state != libvirt.VIR_DOMAIN_SHUTOFF:
        raise ApiException(409, "vm.not_shut_off", "Power the virtual machine off first")
    if delete_files:
        _no_linked_clones(conn, uuid)
    plan = plan_files(xml, others, config) if delete_files else DeletionPlan()

    flags = (
        libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE
        | libvirt.VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA
        | (libvirt.VIR_DOMAIN_UNDEFINE_NVRAM if plan.delete_nvram else 0)
    )
    if not plan.delete_nvram and domain_xml.nvram_path(xml):
        flags |= libvirt.VIR_DOMAIN_UNDEFINE_KEEP_NVRAM
    conn.run(lambda c: c.lookupByUUIDString(uuid).undefineFlags(flags))

    report = DeletionReport()
    for path in plan.delete:
        # Checked again right before the unlink, on the resolved path.
        if not in_library(path, config):
            report.failed.append(path)
            continue
        try:
            os.remove(path)
            report.deleted.append(path)
        except FileNotFoundError:
            report.deleted.append(path)  # already gone (libvirt removes the NVRAM itself)
        except OSError:
            report.failed.append(path)
    return plan, report
