"""Library folders that are real folders on disk (spec 6.1.1).

Layout: <location>/KVM-Studio/VM/<folders>/<VM folder>/<disks>.

Each VM's folder is also written in its <metadata>, so the tree can be rebuilt
when files were moved by hand. KVM Studio then reports the gap ("drift") and
never fixes it on its own.

VMs whose disks live outside the library (created in virt-manager, say) are
never moved automatically: their folder is only a note in <metadata>.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import threading
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import libvirt
from lxml import etree

from ..config import Config
from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection
from ..paths import in_iso_library, in_library, is_strictly_within, library_root, resolve
from . import domain_xml, qemu_img
from .deletion import KeptFile, plan_files, used_elsewhere

NAMESPACE = "https://github.com/rm-networks/kvm-studio/ns/1.0"
PREFIX = "kvmstudio"
MAX_DEPTH = 8

Drift = Literal["missing_files", "folder_mismatch"]

# Moves and deletions touch several files: one at a time.
_lock = threading.Lock()

# Folder and VM folder names: same rule as VM names.
_SEGMENT_RE = re.compile(r"^(?![.\s])[^/\\\x00-\x1f\x7f]{1,64}(?<!\s)$")


@dataclass(frozen=True, slots=True)
class Placement:
    folder: str  # relative path inside the library, "" for the top level
    managed: bool  # files inside the library root
    vm_dir: Path | None
    drift: tuple[Drift, ...]


# Metadata


def metadata_folder(xml: str) -> str | None:
    root = etree.fromstring(xml.encode(), parser=etree.XMLParser(resolve_entities=False))
    node = root.find(f"metadata/{{{NAMESPACE}}}vm/{{{NAMESPACE}}}folder")
    if node is None:
        return None
    return (node.text or "").strip()


def metadata_values(xml: str) -> dict[str, str]:
    """Every field KVM Studio keeps in <metadata> (folder, profile, keyboard...)."""
    root = etree.fromstring(xml.encode(), parser=etree.XMLParser(resolve_entities=False))
    vm = root.find(f"metadata/{{{NAMESPACE}}}vm")
    if vm is None:
        return {}
    return {
        etree.QName(child).localname: (child.text or "").strip()
        for child in vm
        if isinstance(child.tag, str)
    }


def set_metadata(dom: libvirt.virDomain, **values: str) -> None:
    """Update some fields of our <metadata> element, keeping the others."""
    current = metadata_values(dom.XMLDesc(0))
    current.update(values)
    vm = etree.Element("vm")
    for key, value in current.items():
        etree.SubElement(vm, key).text = value
    # Transient domains have no persistent config, only the live one.
    flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG if dom.isPersistent() else 0
    if dom.isActive():
        flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE
    dom.setMetadata(
        libvirt.VIR_DOMAIN_METADATA_ELEMENT,
        etree.tostring(vm).decode(),
        PREFIX,
        NAMESPACE,
        flags,
    )


def set_metadata_folder(dom: libvirt.virDomain, folder: str) -> None:
    set_metadata(dom, folder=folder)


# Validation


def check_folder(folder: str) -> str:
    """Normalise a relative folder path ("" is the top level) or raise 422."""
    folder = folder.strip("/")
    if folder == "":
        return ""
    parts = folder.split("/")
    if len(parts) > MAX_DEPTH or not all(_SEGMENT_RE.match(p) for p in parts):
        raise ApiException(422, "library.invalid_name", f"invalid folder name: {folder}")
    return "/".join(parts)


def _require_root(config: Config) -> Path:
    root = library_root(config)
    if root is None:
        raise ApiException(409, "library.no_location", "No VM location is configured")
    return root


def _folder_dir(root: Path, folder: str) -> Path:
    path = root / folder if folder else root
    # check_folder already refuses "..", this guards against symlinked folders.
    if folder and not is_strictly_within(path, root):
        raise ApiException(403, "path.not_allowed", f"{folder} is outside the library")
    return path


# Placement


def _file_disks(xml: str) -> list[str]:
    return [
        d.path
        for d in domain_xml.disks(xml)
        if d.path and d.source_type == "file" and d.device == "disk"
    ]


def _candidate(xml: str, config: Config) -> Path | None:
    """Folder holding the VM's first disk, when that disk is inside the library."""
    root = library_root(config)
    if root is None:
        return None
    inside = [p for p in _file_disks(xml) if in_library(p, config)]
    return resolve(inside[0]).parent if inside else None


def _own_folder(candidate: Path, root: Path, shared: bool) -> bool:
    """A VM folder holds one VM's files and nothing else: no subfolder, no other VM."""
    if shared or not is_strictly_within(candidate, root):
        return False
    try:
        return not any(child.is_dir() for child in candidate.iterdir())
    except OSError:
        return True  # moved away by hand: it was a VM folder, see drift


def _rel(path: Path, root: Path) -> str:
    rel = path.relative_to(resolve(root))
    return "" if str(rel) == "." else rel.as_posix()


def placements(xmls: list[str], config: Config) -> list[Placement]:
    """Placement of each domain; all domains are needed to spot shared folders."""
    root = library_root(config)
    candidates = [_candidate(xml, config) for xml in xmls]
    counts = Counter(c for c in candidates if c is not None)
    result = []
    for xml, candidate in zip(xmls, candidates, strict=True):
        meta = metadata_folder(xml)
        missing = any(not Path(p).exists() for p in _file_disks(xml))
        drift: list[Drift] = ["missing_files"] if missing else []
        if root is None or candidate is None:
            result.append(Placement(meta or "", False, None, tuple(drift)))
            continue
        if not _own_folder(candidate, root, counts[candidate] > 1):
            # Loose files in a library folder: shown there, never moved as a block.
            folder = meta if meta is not None else _rel(candidate, root)
            result.append(Placement(folder, False, None, tuple(drift)))
            continue
        actual = _rel(candidate.parent, root)
        if meta is not None and meta != actual:
            drift.append("folder_mismatch")
        # Files moved by hand: the XML points to the old place, trust the note.
        folder = meta if missing and meta is not None else actual
        result.append(Placement(folder, True, candidate, tuple(drift)))
    return result


def placement(xml: str, config: Config, others: Iterable[str] = ()) -> Placement:
    return placements([xml, *others], config)[0]


# Folders


def list_folders(config: Config, placements: Iterable[Placement]) -> list[str]:
    placements = list(placements)
    folders: set[str] = {p.folder for p in placements if p.folder}
    root = library_root(config)
    if root is not None and root.is_dir():
        vm_dirs = {p.vm_dir for p in placements if p.vm_dir is not None}
        base = resolve(root)
        for current, dirs, _files in os.walk(base):
            here = Path(current)
            keep = []
            for name in sorted(dirs):
                child = here / name
                if name.startswith(".") or child.is_symlink() or child in vm_dirs:
                    continue
                keep.append(name)
                folders.add(child.relative_to(base).as_posix())
            dirs[:] = keep
    # Parents of nested virtual folders exist too.
    for folder in list(folders):
        parts = folder.split("/")
        folders.update("/".join(parts[:i]) for i in range(1, len(parts)))
    return sorted(folders, key=str.casefold)


def create_folder(config: Config, folder: str) -> str:
    folder = check_folder(folder)
    if not folder:
        raise ApiException(422, "library.invalid_name", "empty folder name")
    root = _require_root(config)
    with _lock:
        root.mkdir(parents=True, exist_ok=True)
        path = _folder_dir(root, folder)
        if path.exists():
            raise ApiException(409, "library.exists", f"{folder} already exists")
        path.mkdir(parents=True)
    return folder


def _snapshot(conn: LibvirtConnection) -> list[tuple[str, str, bool, str]]:
    """(uuid, name, active, inactive xml) for every domain."""

    def op(c: libvirt.virConnect) -> list[tuple[str, str, bool, str]]:
        return [
            (
                d.UUIDString(),
                d.name(),
                bool(d.isActive()),
                d.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE),
            )
            for d in c.listAllDomains()
        ]

    return conn.run(op)


def _in_subtree(folder: str, top: str) -> bool:
    return folder == top or folder.startswith(top + "/")


def _rebased(path: str, old: Path, new: Path) -> str:
    p = resolve(path)
    return str(new / p.relative_to(old)) if p.is_relative_to(old) else path


def _rewrite_paths(xml: str, old: Path, new: Path) -> str:
    """Point disk sources and the NVRAM file under old/ to the same place under new/."""
    root = etree.fromstring(xml.encode(), parser=etree.XMLParser(resolve_entities=False))
    for source in root.iterfind("devices/disk/source"):
        for attr in ("file", "dev"):
            if value := source.get(attr):
                source.set(attr, _rebased(value, old, new))
    nvram = root.find("os/nvram")
    if nvram is not None:
        src = nvram.find("source")
        if src is not None and src.get("file"):
            src.set("file", _rebased(src.get("file") or "", old, new))
        elif nvram.text and nvram.text.strip():
            nvram.text = _rebased(nvram.text.strip(), old, new)
    return etree.tostring(root).decode()


@dataclass(slots=True)
class _Move:
    uuid: str
    xml: str
    old_dir: Path
    new_dir: Path


def _dependents(target_dirs: list[Path], others: list[str], config: Config) -> list[str]:
    """Files outside the moved folders that use something inside them as backing."""
    used_by: list[str] = []
    for xml in others:
        for disk in domain_xml.disks(xml):
            if not disk.path:
                continue
            chain = qemu_img.backing_files(Path(disk.path)) or list(disk.backing_paths)
            if any(resolve(b).is_relative_to(d) for b in chain for d in target_dirs):
                used_by.append(disk.path)
    root = library_root(config)
    if root is not None and root.is_dir():
        for image in resolve(root).rglob("*"):
            if any(image.is_relative_to(d) for d in target_dirs):
                continue
            if image.is_file() and qemu_img.is_qcow2(image):
                chain = qemu_img.backing_files(image) or []
                if any(resolve(b).is_relative_to(d) for b in chain for d in target_dirs):
                    used_by.append(str(image))
    return sorted(set(used_by))


def _rebase_internal_chains(moves: list[_Move]) -> None:
    """Overlays whose backing file moved with them get the new absolute path."""
    for move in moves:
        for path in _file_disks(move.xml):
            overlay = Path(_rebased(path, move.old_dir, move.new_dir))
            if not overlay.exists() or not qemu_img.is_qcow2(overlay):
                continue
            info = qemu_img.image_info(overlay)
            if info is None:
                continue
            backing = info.get("backing-filename")
            # Relative backing names still work once the whole folder moved.
            if not backing or not os.path.isabs(backing):
                continue
            new_backing = Path(_rebased(backing, move.old_dir, move.new_dir))
            if new_backing != Path(backing):
                qemu_img.rebase_unsafe(overlay, new_backing, info.get("backing-filename-format"))


def _apply_moves(conn: LibvirtConnection, moves: list[_Move], folders: dict[str, str]) -> None:
    def op(c: libvirt.virConnect) -> None:
        for move in moves:
            c.defineXML(_rewrite_paths(move.xml, move.old_dir, move.new_dir))
        for uuid, folder in folders.items():
            set_metadata_folder(c.lookupByUUIDString(uuid), folder)

    conn.run(op)


def rename_folder(conn: LibvirtConnection, config: Config, folder: str, new_name: str) -> str:
    folder = check_folder(folder)
    if not folder or "/" in new_name or not _SEGMENT_RE.match(new_name):
        raise ApiException(422, "library.invalid_name", f"invalid folder name: {new_name}")
    root = _require_root(config)
    parent = folder.rpartition("/")[0]
    target = f"{parent}/{new_name}" if parent else new_name

    with _lock:
        domains = _snapshot(conn)
        places = placements([x for _u, _n, _a, x in domains], config)
        inside = [(u, n, a, x, p) for (u, n, a, x), p in zip(domains, places, strict=True)]
        inside = [d for d in inside if _in_subtree(d[4].folder, folder)]
        running = [n for _u, n, a, _x, _p in inside if a]
        if running:
            raise ApiException(
                409, "library.vms_running", "Power off first: " + ", ".join(sorted(running))
            )
        old_dir, new_dir = _folder_dir(root, folder), _folder_dir(root, target)
        if new_dir.exists():
            raise ApiException(409, "library.exists", f"{target} already exists")
        others = [x for u, _n, _a, x in domains if u not in {d[0] for d in inside}]
        old_resolved, new_resolved = resolve(old_dir), resolve(new_dir)
        renamed = False
        if old_dir.is_dir():
            if blockers := _dependents([old_resolved], others, config):
                raise ApiException(
                    409, "library.backing_in_use", "Linked clones depend on: " + ", ".join(blockers)
                )
            os.rename(old_dir, new_dir)
            renamed = True
        moves = []
        folders = {}
        for uuid, _n, _a, xml, place in inside:
            folders[uuid] = target + place.folder[len(folder) :]
            on_disk = place.vm_dir is not None and place.vm_dir.is_relative_to(old_resolved)
            if renamed and place.managed and on_disk:
                moves.append(_Move(uuid, xml, old_resolved, new_resolved))
        _rebase_internal_chains(moves)
        _apply_moves(conn, moves, folders)
    return target


@dataclass(slots=True)
class VmDeletion:
    uuid: str
    name: str
    delete: list[str]
    keep: list[KeptFile]
    delete_nvram: bool


@dataclass(slots=True)
class FolderDeletionPlan:
    folder: str
    vms: list[VmDeletion] = field(default_factory=list)
    extra_files: list[str] = field(default_factory=list)
    keep: list[KeptFile] = field(default_factory=list)
    running: list[str] = field(default_factory=list)


def plan_folder_deletion(
    conn: LibvirtConnection, config: Config, folder: str
) -> FolderDeletionPlan:
    folder = check_folder(folder)
    if not folder:
        raise ApiException(422, "library.invalid_name", "the top level cannot be deleted")
    root = _require_root(config)
    domains = _snapshot(conn)
    plan = FolderDeletionPlan(folder)
    places = placements([x for _u, _n, _a, x in domains], config)
    members = {d[0] for d, p in zip(domains, places, strict=True) if _in_subtree(p.folder, folder)}
    others = [x for u, _n, _a, x in domains if u not in members]
    planned: set[str] = set()
    for uuid, name, active, xml in domains:
        if uuid not in members:
            continue
        if active:
            plan.running.append(name)
        vm_plan = plan_files(xml, others, config)
        plan.vms.append(VmDeletion(uuid, name, vm_plan.delete, vm_plan.keep, vm_plan.delete_nvram))
        planned.update(vm_plan.delete)
        planned.update(k.path for k in vm_plan.keep)

    folder_dir = _folder_dir(root, folder)
    if folder_dir.is_dir():
        used = used_elsewhere(others, config, planned)
        for path in sorted(resolve(folder_dir).rglob("*")):
            if not path.is_file() or str(path) in planned:
                continue
            p = str(path)
            if path.is_symlink() or not in_library(p, config):
                plan.keep.append(KeptFile(p, "outside_library"))
            elif in_iso_library(p, config) or path.suffix.lower() == ".iso":
                plan.keep.append(KeptFile(p, "iso"))
            elif p in used:
                plan.keep.append(KeptFile(p, "shared"))
            else:
                plan.extra_files.append(p)
    return plan


def delete_folder(conn: LibvirtConnection, config: Config, folder: str) -> list[str]:
    """Delete every VM and file of the folder; return the paths that could not go."""
    root = _require_root(config)
    with _lock:
        plan = plan_folder_deletion(conn, config, folder)
        if plan.running:
            raise ApiException(
                409, "library.vms_running", "Power off first: " + ", ".join(plan.running)
            )
        failed: list[str] = []

        def undefine(c: libvirt.virConnect) -> None:
            for vm in plan.vms:
                flags = (
                    libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE
                    | libvirt.VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA
                )
                dom = c.lookupByUUIDString(vm.uuid)
                if domain_xml.nvram_path(dom.XMLDesc(0)):
                    flags |= (
                        libvirt.VIR_DOMAIN_UNDEFINE_NVRAM
                        if vm.delete_nvram
                        else libvirt.VIR_DOMAIN_UNDEFINE_KEEP_NVRAM
                    )
                dom.undefineFlags(flags)

        conn.run(undefine)
        for path in [p for vm in plan.vms for p in vm.delete] + plan.extra_files:
            if not in_library(path, config):
                failed.append(path)
                continue
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError:
                failed.append(path)
        folder_dir = _folder_dir(root, plan.folder)
        if folder_dir.is_dir():
            for current, _dirs, _files in os.walk(resolve(folder_dir), topdown=False):
                with contextlib.suppress(OSError):
                    Path(current).rmdir()  # only succeeds on empty folders
        return failed


# Moving a VM


def move_vm(conn: LibvirtConnection, config: Config, uuid: str, folder: str) -> str:
    folder = check_folder(folder)
    with _lock:
        domains = _snapshot(conn)
        match = [(n, a, x) for u, n, a, x in domains if u == uuid]
        if not match:
            raise ApiException(404, "libvirt.no_domain", "Domain not found")
        _name, active, xml = match[0]
        place = placement(xml, config, (x for u, _n, _a, x in domains if u != uuid))
        if place.folder == folder:
            return folder
        if folder:
            root = _require_root(config)
            target_parent = _folder_dir(root, folder)
            if not target_parent.is_dir():
                raise ApiException(404, "library.no_folder", f"{folder} does not exist")

        if not place.managed or place.vm_dir is None:
            # Not our files: only the note in <metadata> changes.
            conn.run(lambda c: set_metadata_folder(c.lookupByUUIDString(uuid), folder))
            return folder

        if active:
            raise ApiException(409, "vm.not_shut_off", "Power the virtual machine off first")
        if "missing_files" in place.drift:
            raise ApiException(
                409, "library.drift", "Files were moved by hand; fix the gap before moving"
            )
        root = _require_root(config)
        old_dir = place.vm_dir
        new_dir = resolve(_folder_dir(root, folder)) / old_dir.name
        if new_dir.exists():
            raise ApiException(409, "library.exists", f"{new_dir} already exists")
        others = [x for u, _n, _a, x in domains if u != uuid]
        if blockers := _dependents([old_dir], others, config):
            raise ApiException(
                409, "library.backing_in_use", "Linked clones depend on: " + ", ".join(blockers)
            )
        try:
            os.rename(old_dir, new_dir)
        except OSError as exc:
            raise ApiException(500, "library.move_failed", str(exc)) from exc
        move = _Move(uuid, xml, old_dir, new_dir)
        try:
            _rebase_internal_chains([move])
            _apply_moves(conn, [move], {uuid: folder})
        except Exception:
            os.rename(new_dir, old_dir)  # put things back as they were
            raise
    return folder


# Bringing an outside VM into the library


@dataclass(slots=True)
class ImportResult:
    copied: list[str] = field(default_factory=list)
    originals: list[str] = field(default_factory=list)


def import_vm_files(
    conn: LibvirtConnection, config: Config, uuid: str, folder: str
) -> ImportResult:
    """Copy an outside VM's disks into the library and point the VM at the copies.

    The originals are left in place (KVM Studio never deletes outside its root);
    the result lists them so the user can remove them.
    """
    folder = check_folder(folder)
    root = _require_root(config)
    with _lock:
        domains = _snapshot(conn)
        match = [(n, a, x) for u, n, a, x in domains if u == uuid]
        if not match:
            raise ApiException(404, "libvirt.no_domain", "Domain not found")
        name, active, xml = match[0]
        if active:
            raise ApiException(409, "vm.not_shut_off", "Power the virtual machine off first")
        sources = [p for p in _file_disks(xml) if not in_library(p, config)]
        if not sources:
            raise ApiException(
                409, "library.already_inside", "The disks are already in the library"
            )
        if not _SEGMENT_RE.match(name):
            raise ApiException(422, "library.invalid_name", f"invalid folder name: {name}")
        vm_dir = resolve(_folder_dir(root, folder)) / name
        if vm_dir.exists():
            raise ApiException(409, "library.exists", f"{vm_dir} already exists")
        for src in sources:
            if not os.access(src, os.R_OK):
                raise ApiException(403, "library.unreadable", f"{src} is not readable")

        vm_dir.mkdir(parents=True)
        result = ImportResult()
        mapping: dict[str, str] = {}
        try:
            for i, src in enumerate(sources):
                fmt = "qcow2" if qemu_img.is_qcow2(Path(src)) else "raw"
                suffix = "" if i == 0 else f"-{i + 1}"
                dest = vm_dir / f"{name}{suffix}.{fmt}"
                qemu_img.convert(Path(src), dest, fmt)
                mapping[src] = str(dest)
                result.copied.append(str(dest))
                result.originals.append(src)
        except (qemu_img.QemuImgError, subprocess.SubprocessError, OSError) as exc:
            shutil.rmtree(vm_dir, ignore_errors=True)
            raise ApiException(500, "library.copy_failed", str(exc)) from exc

        tree = etree.fromstring(xml.encode(), parser=etree.XMLParser(resolve_entities=False))
        for source in tree.iterfind("devices/disk/source"):
            if (path := source.get("file")) in mapping:
                source.set("file", mapping[path])

        def op(c: libvirt.virConnect) -> None:
            c.defineXML(etree.tostring(tree).decode())
            set_metadata_folder(c.lookupByUUIDString(uuid), folder)

        conn.run(op)
    return result


def placement_of(conn: LibvirtConnection, config: Config, uuid: str) -> Placement:
    domains = _snapshot(conn)
    xml = next((x for u, _n, _a, x in domains if u == uuid), None)
    if xml is None:
        raise ApiException(404, "libvirt.no_domain", "Domain not found")
    return placement(xml, config, (x for u, _n, _a, x in domains if u != uuid))
