"""Cloning a powered off VM (F-84): full copy or linked clone.

The clone gets its own folder in the library, laid out like any other VM:
<root>/<folder>/<name>/<name>.qcow2, <name>-2.qcow2..., <name>_VARS.fd. It has a
new name, a new UUID and new MAC addresses, and the same hardware.

- Full clone: every disk is copied with qemu-img convert.
- Linked clone: every disk is a new qcow2 image whose backing file is the
  source disk. The source must then never run again while a clone uses it:
  its disks would change under the clones (see linked_clones()).

The firmware variables (NVRAM) and the TPM state belong to QEMU and to swtpm:
the helper copies them. A cancelled or failed clone removes what it created.
"""

from __future__ import annotations

import contextlib
import os
import uuid as uuidlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import libvirt
from lxml import etree

from .. import helper_client
from ..config import Config
from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection
from ..paths import library_root, resolve
from . import domain_xml, qemu_img
from .create import nic_target
from .library import _SEGMENT_RE, NAMESPACE, PREFIX, check_folder, metadata_values
from .tasks import Task

Kind = Literal["full", "linked"]
# Without the helper (sources), the clone starts with fresh firmware variables
# and a new TPM: these codes are reported, not raised.
_WITHOUT_HELPER = {"helper.unavailable", "helper.unknown_operation", "helper.not_authorized"}


@dataclass(frozen=True, slots=True)
class DiskCopy:
    target: str
    source: Path
    source_format: str
    dest: Path
    dest_format: str
    size: int


@dataclass(slots=True)
class ClonePlan:
    source_uuid: str
    source_name: str
    kind: Kind
    name: str
    folder: str
    vm_dir: Path
    uuid: str
    xml: str
    disks: list[DiskCopy] = field(default_factory=list)
    nvram_source: Path | None = None
    nvram_dest: Path | None = None
    tpm: bool = False


def _parse(xml: str) -> etree._Element:
    return etree.fromstring(xml.encode(), parser=etree.XMLParser(resolve_entities=False))


def prepare(
    conn: LibvirtConnection, config: Config, uuid: str, kind: Kind, name: str, folder: str
) -> ClonePlan:
    """Check everything that can be checked before copying anything."""
    if not _SEGMENT_RE.match(name):
        raise ApiException(422, "vm.bad_name", f"invalid virtual machine name: {name}")
    folder = check_folder(folder)
    root = library_root(config)
    if root is None:
        raise ApiException(409, "library.no_location", "No VM location is configured")
    parent = root / folder if folder else root
    if not parent.is_dir():
        raise ApiException(404, "library.no_folder", f"{folder or root} does not exist")

    def snapshot(c: libvirt.virConnect) -> tuple[str, str, bool, bool, set[str]]:
        dom = c.lookupByUUIDString(uuid)
        return (
            dom.name(),
            dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE | libvirt.VIR_DOMAIN_XML_SECURE),
            bool(dom.isActive()),
            bool(dom.isPersistent()),
            {d.name() for d in c.listAllDomains()},
        )

    source_name, xml, active, persistent, names = conn.run(snapshot)
    if active or not persistent:
        raise ApiException(409, "vm.not_shut_off", "Power the virtual machine off first")
    if name in names:
        raise ApiException(409, "vm.exists", f"{name} already exists")
    vm_dir = parent / name
    if vm_dir.exists():
        raise ApiException(409, "library.exists", f"{vm_dir} already exists")

    plan = ClonePlan(uuid, source_name, kind, name, folder, vm_dir, str(uuidlib.uuid4()), xml)
    files = [d for d in domain_xml.disks(xml) if d.device == "disk" and d.path]
    for index, disk in enumerate(files):
        if disk.source_type != "file" or disk.path is None:
            raise ApiException(422, "clone.unsupported_disk", f"{disk.target} is not a file")
        source = resolve(disk.path)
        info = qemu_img.image_info(source)
        if info is None or not os.access(source, os.R_OK):
            raise ApiException(403, "clone.unreadable_disk", f"Cannot read {source}")
        source_format = str(info.get("format", "raw"))
        dest_format = "qcow2" if kind == "linked" else source_format
        if dest_format not in ("qcow2", "raw"):
            dest_format = "qcow2"
        suffix = "" if index == 0 else f"-{index + 1}"
        plan.disks.append(
            DiskCopy(
                disk.target,
                source,
                source_format,
                vm_dir / f"{name}{suffix}.{dest_format}",
                dest_format,
                int(info.get("virtual-size", 0)),
            )
        )
    if nvram := domain_xml.nvram_path(xml):
        plan.nvram_source = resolve(nvram)
        plan.nvram_dest = vm_dir / f"{name}_VARS.fd"
    plan.tpm = _parse(xml).find("devices/tpm/backend[@type='emulator']") is not None
    return plan


def clone_xml(plan: ClonePlan) -> str:
    """The source definition with the clone's name, UUID, files and fresh MACs."""
    root = _parse(plan.xml)
    root.find("name").text = plan.name  # type: ignore[union-attr]
    uuid_el = root.find("uuid")
    if uuid_el is None:
        uuid_el = etree.SubElement(root, "uuid")
    uuid_el.text = plan.uuid
    copies = {d.target: d for d in plan.disks}
    for disk in root.iterfind("devices/disk"):
        target = disk.find("target")
        copy = copies.get(target.get("dev", "") if target is not None else "")
        if copy is None or disk.get("device", "disk") != "disk":
            continue
        source = disk.find("source")
        if source is not None:
            source.set("file", str(copy.dest))
        driver = disk.find("driver")
        if driver is not None:
            driver.set("type", copy.dest_format)
        for store in disk.findall("backingStore"):
            disk.remove(store)
    for index, nic in enumerate(root.iterfind("devices/interface")):
        for mac in nic.findall("mac"):
            nic.remove(mac)  # libvirt gives a new one
        target = nic.find("target")
        if target is not None:
            if target.get("dev", "").startswith("ks-"):
                target.set("dev", nic_target(plan.uuid, index))
            else:
                nic.remove(target)
    for source in root.iterfind("devices/channel[@type='unix']/source"):
        if "path" in source.attrib:
            del source.attrib["path"]  # libvirt makes one per domain
    nvram = root.find("os/nvram")
    if nvram is not None and plan.nvram_dest is not None:
        file_source = nvram.find("source")
        if file_source is not None:
            file_source.set("file", str(plan.nvram_dest))
        else:
            nvram.text = str(plan.nvram_dest)
    _set_metadata(root, plan)
    return etree.tostring(root).decode()


def _set_metadata(root: etree._Element, plan: ClonePlan) -> None:
    values = metadata_values(plan.xml)
    values["folder"] = plan.folder
    if plan.kind == "linked":
        values["linked_to"] = plan.source_uuid
    else:
        values.pop("linked_to", None)  # a full copy depends on nothing
    metadata = root.find("metadata")
    if metadata is None:
        metadata = etree.SubElement(root, "metadata")
    for old in metadata.findall(f"{{{NAMESPACE}}}vm"):
        metadata.remove(old)
    vm = etree.SubElement(metadata, f"{{{NAMESPACE}}}vm", nsmap={PREFIX: NAMESPACE})
    for key, value in values.items():
        etree.SubElement(vm, f"{{{NAMESPACE}}}{key}").text = value


def run(conn: LibvirtConnection, plan: ClonePlan, task: Task) -> dict[str, Any]:
    created: list[Path] = []
    defined = False
    plan.vm_dir.mkdir()
    try:
        total = sum(max(d.size, 1) for d in plan.disks) or 1
        done = 0
        for disk in plan.disks:
            task.report(done / total * 0.95, disk.dest.name)
            created.append(disk.dest)
            if plan.kind == "linked":
                qemu_img.create_overlay(disk.dest, disk.source, disk.source_format)
            else:
                start, share = done / total, max(disk.size, 1) / total

                def progress(part: float, start: float = start, share: float = share) -> None:
                    task.report((start + part * share) * 0.95)

                qemu_img.convert_progress(disk.source, disk.dest, disk.dest_format, progress)
            done += max(disk.size, 1)
        task.report(0.95, plan.name)
        xml = clone_xml(plan)
        conn.run(lambda c: c.defineXML(xml))
        defined = True
        warnings = _copy_state(plan, created)
        task.report(1.0)
    except BaseException:
        _clean(conn, plan, created, defined)
        raise
    return {"uuid": plan.uuid, "name": plan.name, "warnings": warnings}


def _copy_state(plan: ClonePlan, created: list[Path]) -> list[str]:
    """NVRAM and TPM through the helper; without it the clone starts afresh."""
    if plan.nvram_source is None and not plan.tpm:
        return []
    params = {
        "source_uuid": plan.source_uuid,
        "target_uuid": plan.uuid,
        "nvram_source": str(plan.nvram_source) if plan.nvram_source else None,
        "nvram_target": str(plan.nvram_dest) if plan.nvram_dest else None,
    }
    if plan.nvram_source is not None and not plan.nvram_source.exists():
        # Never started: libvirt makes the variables from its template.
        params["nvram_source"] = params["nvram_target"] = None
    try:
        result = helper_client.call("clone_vm_state", params)
    except ApiException as exc:
        if exc.code in _WITHOUT_HELPER:
            return ["state_not_copied"]
        raise
    if result.get("nvram") and plan.nvram_dest is not None:
        created.append(plan.nvram_dest)
    return []


def _clean(conn: LibvirtConnection, plan: ClonePlan, created: list[Path], defined: bool) -> None:
    if defined:

        def undefine(c: libvirt.virConnect) -> None:
            dom = c.lookupByUUIDString(plan.uuid)
            try:
                # The copied TPM state goes with it; libvirt removes it as root.
                dom.undefineFlags(
                    libvirt.VIR_DOMAIN_UNDEFINE_NVRAM | libvirt.VIR_DOMAIN_UNDEFINE_TPM
                )
            except libvirt.libvirtError:
                dom.undefine()

        with contextlib.suppress(libvirt.libvirtError):
            conn.run(undefine)
    for path in created:
        with contextlib.suppress(OSError):
            path.unlink()
    with contextlib.suppress(OSError):
        plan.vm_dir.rmdir()


def linked_clones(conn: LibvirtConnection, uuid: str) -> list[str]:
    """Names of the VMs whose disks are overlays of this VM's disks."""

    def snapshot(c: libvirt.virConnect) -> tuple[str, list[tuple[str, str]]]:
        dom = c.lookupByUUIDString(uuid)
        others = [
            (d.name(), d.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))
            for d in c.listAllDomains()
            if d.UUIDString() != uuid
        ]
        return dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE), others

    xml, others = conn.run(snapshot)
    own = {str(resolve(d.path)) for d in domain_xml.disks(xml) if d.path and d.device == "disk"}
    clones = []
    for name, other in others:
        if metadata_values(other).get("linked_to") == uuid:
            clones.append(name)
            continue
        for disk in domain_xml.disks(other):
            if not disk.path or disk.source_type != "file":
                continue
            chain = qemu_img.backing_files(Path(disk.path)) or list(disk.backing_paths)
            if any(str(resolve(b)) in own for b in chain):
                clones.append(name)
                break
    return sorted(clones)
