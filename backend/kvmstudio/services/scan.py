"""Scanning a folder for virtual machines: disks grouped by folder, libvirt definitions.

What was found is listed first, with the VMs libvirt already knows marked.
The ones picked are then defined in libvirt, their files left where they are
or copied or moved into the KVM-Studio tree (never anywhere else). Their
library folders are rebuilt from the tree they were found in.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import libvirt
from lxml import etree

from ..config import Config
from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection
from ..paths import LIBRARY_DIRNAME, VMS_DIRNAME, is_strictly_within, library_root, resolve
from ..xml.profiles import PROFILES
from . import create, domain_xml, qemu_img
from .library import _SEGMENT_RE, check_folder, create_folder, set_metadata_folder

MAX_DEPTH = 8
MAX_FOLDERS = 5000
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True)

Mode = Literal["keep", "copy", "move"]


@dataclass(slots=True)
class Found:
    id: str  # the folder of a group of disks, or the path of a definition
    name: str
    folder: str  # library folder rebuilt from the tree
    disks: list[str]
    definition: str | None = None  # libvirt XML file
    known: str | None = None  # the libvirt VM that already uses these files
    uefi: bool = False


@dataclass(slots=True)
class Choice:
    id: str
    mode: Mode = "keep"


@dataclass(slots=True)
class Outcome:
    imported: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def _known(conn: LibvirtConnection) -> tuple[dict[Path, str], dict[str, str], set[str]]:
    """Disk files in use, UUIDs and names of the domains libvirt has."""

    def op(c: libvirt.virConnect) -> list[tuple[str, str, str]]:
        return [
            (d.name(), d.UUIDString(), d.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))
            for d in c.listAllDomains()
        ]

    files: dict[Path, str] = {}
    uuids: dict[str, str] = {}
    names: set[str] = set()
    for name, uuid, xml in conn.run(op):
        names.add(name)
        uuids[uuid] = name
        for disk in domain_xml.disks(xml):
            if disk.path:
                files[resolve(disk.path)] = name
    return files, uuids, names


def _place(top: Path, directory: Path) -> tuple[str, str]:
    """Library folder and VM name of a folder of disks, from the tree under top."""
    parts = list(directory.relative_to(top).parts) if directory != top else []
    # A KVM-Studio tree inside: what lies under KVM-Studio/VM is the library.
    for i in range(len(parts) - 1):
        if parts[i] == LIBRARY_DIRNAME and parts[i + 1] == VMS_DIRNAME:
            parts = parts[i + 2 :]
            break
    if not parts:
        return "", ""
    return "/".join(parts[:-1]), parts[-1]


def _definition(path: Path) -> tuple[str, str, etree._Element] | None:
    try:
        root = etree.parse(str(path), _PARSER).getroot()
    except (etree.XMLSyntaxError, OSError):
        return None
    if root.tag != "domain" or not root.findtext("name"):
        return None
    return root.findtext("name", ""), root.findtext("uuid", ""), root


def _disk_paths(root: etree._Element, directory: Path) -> list[str]:
    """Disk files of a definition; one gone from its old place is looked for next to it."""
    paths = []
    for source in root.iterfind("devices/disk[@device='disk']/source"):
        path = source.get("file")
        if not path:
            continue
        if not Path(path).exists() and (directory / Path(path).name).is_file():
            path = str(directory / Path(path).name)
        paths.append(path)
    return paths


def scan(conn: LibvirtConnection, top_path: str) -> list[Found]:
    if not os.path.isabs(top_path):
        raise ApiException(422, "files.not_absolute", f"{top_path} is not an absolute path")
    top = resolve(top_path)
    if not top.is_dir():
        raise ApiException(404, "files.no_folder", f"{top_path} is not a folder")
    files, uuids, _names = _known(conn)
    found: list[Found] = []
    visited = 0
    for current, dirs, names in os.walk(top):
        here = Path(current)
        depth = len(here.relative_to(top).parts)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and depth < MAX_DEPTH)
        visited += 1
        if visited > MAX_FOLDERS:
            break
        folder, vm_name = _place(top, here)
        taken: set[str] = set()
        for name in sorted(n for n in names if n.lower().endswith(".xml")):
            parsed = _definition(here / name)
            if parsed is None:
                continue
            dom_name, uuid, root = parsed
            disks = _disk_paths(root, here)
            taken.update(Path(d).name for d in disks)
            in_use = next((files[resolve(d)] for d in disks if resolve(d) in files), None)
            found.append(
                Found(
                    id=str(here / name),
                    name=dom_name,
                    folder=folder,
                    disks=disks,
                    definition=str(here / name),
                    known=uuids.get(uuid) or in_use,
                )
            )
        disks = [
            str(here / n)
            for n in sorted(names)
            if n.lower().endswith(".qcow2") and n not in taken and not n.startswith(".")
        ]
        if disks:
            in_use = next((files[resolve(d)] for d in disks if resolve(d) in files), None)
            found.append(
                Found(
                    id=str(here),
                    name=vm_name or Path(disks[0]).stem,
                    folder=folder,
                    disks=disks,
                    known=in_use,
                    uefi=qemu_img.has_gpt(Path(disks[0]), "qcow2"),
                )
            )
    return found


def _target_dir(config: Config, item: Found) -> Path:
    root = library_root(config)
    if root is None:
        raise ApiException(409, "library.no_location", "No VM location is configured")
    folder = check_folder(item.folder)
    target = resolve(root) / folder / item.name if folder else resolve(root) / item.name
    if not is_strictly_within(target, root):
        raise ApiException(403, "path.not_allowed", f"{target} is outside the library")
    return target


def _picked(conn: LibvirtConnection, top: str, choices: list[Choice]) -> list[tuple[Found, Mode]]:
    by_id = {f.id: f for f in scan(conn, top)}
    picked = []
    for choice in choices:
        item = by_id.get(choice.id)
        if item is None:
            raise ApiException(404, "scan.gone", f"{choice.id} is no longer there")
        if item.known is not None:
            raise ApiException(409, "scan.known", f"{item.name} is already in libvirt")
        picked.append((item, choice.mode))
    return picked


def plan(
    conn: LibvirtConnection, config: Config, top: str, choices: list[Choice]
) -> list[tuple[str, str]]:
    """Exact copies and moves an import would make: (from, to)."""
    moves = []
    for item, mode in _picked(conn, top, choices):
        if mode == "keep":
            continue
        target = _target_dir(config, item)
        moves += [(d, str(target / Path(d).name)) for d in item.disks]
    return moves


def _bring_in(item: Found, mode: Mode, config: Config) -> list[str]:
    """Copy or move the disks into the VM's folder of the library; their new paths."""
    if mode == "keep":
        return item.disks
    target = _target_dir(config, item)
    if target.exists():
        raise ApiException(409, "library.exists", f"{target} already exists")
    target.mkdir(parents=True)
    placed: list[str] = []
    try:
        for disk in item.disks:
            dest = target / Path(disk).name
            if mode == "move":
                create.move_file(Path(disk), dest)
            else:
                fmt = "qcow2" if qemu_img.is_qcow2(Path(disk)) else "raw"
                qemu_img.convert(Path(disk), dest, fmt)
            placed.append(str(dest))
    except (qemu_img.QemuImgError, OSError) as exc:
        if mode == "move":
            for disk, done in zip(item.disks, placed, strict=False):
                create.move_file(Path(done), Path(disk))  # back where it was
        shutil.rmtree(target, ignore_errors=True)
        raise ApiException(500, "library.copy_failed", str(exc)) from exc
    return placed


def _define(conn: LibvirtConnection, config: Config, item: Found, disks: list[str]) -> None:
    if item.definition is not None:
        root = etree.parse(item.definition, _PARSER).getroot()
        sources = root.findall("devices/disk[@device='disk']/source")
        for source, path in zip((s for s in sources if s.get("file")), disks, strict=False):
            source.set("file", path)
        xml = etree.tostring(root).decode()
        dom = conn.run(lambda c: c.defineXML(xml))
        set_metadata_folder(dom, item.folder, config)
        return
    profile = PROFILES["other"]
    create.create_vm(
        conn,
        config,
        create.NewVm(
            name=item.name,
            folder=item.folder,
            profile="other",
            iso=None,
            existing_disk=disks[0],
            extra_disks=disks[1:],
            disk_gib=0,
            disk_bus=profile.disk_bus,
            disk_format="qcow2",
            preallocate=False,
            memory_mib=profile.memory_mib,
            vcpus=profile.vcpus,
            # Firmware from the disk: a GPT disk was installed for UEFI.
            uefi=item.uefi,
        ),
    )


def import_found(
    conn: LibvirtConnection, config: Config, top: str, choices: list[Choice]
) -> Outcome:
    outcome = Outcome()
    _files, _uuids, names = _known(conn)
    for item, mode in _picked(conn, top, choices):
        try:
            if not _SEGMENT_RE.match(item.name) or item.name in names:
                raise ApiException(409, "vm.exists", f"{item.name} already exists")
            if item.folder:
                root = library_root(config)
                if root is not None and not (root / item.folder).is_dir():
                    create_folder(config, item.folder)
            disks = _bring_in(item, mode, config)
            _define(conn, config, item, disks)
        except (ApiException, libvirt.libvirtError) as exc:
            detail = exc.detail if isinstance(exc, ApiException) else str(exc)
            outcome.failed.append((item.name, detail))
            continue
        names.add(item.name)
        outcome.imported.append(item.name)
    return outcome
