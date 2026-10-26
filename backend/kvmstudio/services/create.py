"""Creating a VM from the wizard: its folder, its disk, its libvirt definition."""

from __future__ import annotations

import os
import re
import shutil
import uuid as uuidlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import libvirt
from lxml import etree

from ..config import Config
from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection
from ..paths import confine, in_iso_library, in_library, library_root, resolve
from ..xml.domain import DiskSpec, DomainSpec, NicSpec, build_domain
from ..xml.profiles import PROFILES, DiskBus, NicModel
from . import qemu_img
from .host_kvm import kvm_state
from .library import _SEGMENT_RE, check_folder, noted_root

MAX_NICS = 10

# What happens to an existing disk: used where it is (no folder is made for
# the VM), copied into the VM's folder, or moved there.
ExistingMode = Literal["in_place", "copy", "move"]


@dataclass(slots=True)
class NicChoice:
    network: str
    model: NicModel


@dataclass(slots=True)
class NewVm:
    name: str
    folder: str
    profile: str
    iso: str | None
    existing_disk: str | None
    disk_gib: int
    disk_bus: DiskBus
    disk_format: str
    preallocate: bool
    memory_mib: int
    vcpus: int
    nics: list[NicChoice] = field(default_factory=list)
    uefi: bool = True
    secure_boot: bool = False
    tpm: bool = False
    start: bool = False
    existing_mode: ExistingMode = "in_place"
    # A guest of LAN sharing: disks only from inside the library (F-103).
    confined: bool = False


def nic_target(uuid: str, index: int) -> str:
    """Host interface name of a VM card: ks-<6 hex>-<n>, at most 15 characters."""
    return f"ks-{uuid.replace('-', '')[:6]}-{index}"


def _check(conn: LibvirtConnection, config: Config, vm: NewVm) -> tuple[Path, str]:
    if not _SEGMENT_RE.match(vm.name):
        raise ApiException(422, "vm.bad_name", f"invalid virtual machine name: {vm.name}")
    if vm.profile not in PROFILES:
        raise ApiException(422, "vm.bad_profile", f"unknown profile {vm.profile}")
    if len(vm.nics) > MAX_NICS:
        raise ApiException(422, "vm.too_many_nics", f"at most {MAX_NICS} network cards")
    if vm.disk_format not in ("qcow2", "raw"):
        raise ApiException(422, "vm.bad_format", "disk format must be qcow2 or raw")
    if vm.secure_boot and not vm.uefi:
        raise ApiException(422, "vm.secure_boot_needs_uefi", "Secure Boot needs UEFI")
    folder = check_folder(vm.folder)
    root = library_root(config)
    if root is None:
        raise ApiException(409, "library.no_location", "No VM location is configured")
    parent = root / folder if folder else root
    if not parent.is_dir():
        raise ApiException(404, "library.no_folder", f"{folder or root} does not exist")

    def names(c: libvirt.virConnect) -> tuple[set[str], set[str], str]:
        return (
            {d.name() for d in c.listAllDomains()},
            {n.name() for n in c.listAllNetworks()},
            c.getType(),
        )

    existing, networks, driver = conn.run(names)
    if vm.name in existing:
        raise ApiException(409, "vm.exists", f"{vm.name} already exists")
    for nic in vm.nics:
        if nic.network not in networks:
            raise ApiException(404, "libvirt.no_network", f"network {nic.network} not found")
    vm_dir = parent / vm.name
    in_place = vm.existing_disk is not None and vm.existing_mode == "in_place"
    if not in_place and vm_dir.exists():
        raise ApiException(409, "library.exists", f"{vm_dir} already exists")
    return vm_dir, "test" if driver.upper() == "TEST" else "kvm"


def existing_disk(path: str, config: Config, mode: ExistingMode, *, confined: bool) -> Path:
    """The disk file an existing-disk VM starts from, checked for the chosen mode.

    The owner may pick a disk anywhere; a guest only inside the library. An ISO
    library is read only: a disk there can be copied, never used or moved.
    """
    if not os.path.isabs(path):
        raise ApiException(422, "vm.disk_not_absolute", f"{path} is not an absolute path")
    source = resolve(path)
    in_iso = in_iso_library(source, config)
    if confined and not (in_library(source, config) or (in_iso and mode == "copy")):
        raise ApiException(403, "path.not_allowed", f"{path} is outside the library")
    if in_iso and mode != "copy":
        raise ApiException(
            409, "vm.disk_in_iso_library", "ISO libraries are read only: copy the disk instead"
        )
    if not source.is_file():
        raise ApiException(404, "vm.no_disk", f"{path} is not a file")
    if not os.access(source, os.R_OK):
        raise ApiException(403, "library.unreadable", f"{path} is not readable")
    return source


def _move_file(src: Path, dest: Path) -> None:
    """rename(), or a copy then removal across file systems."""
    try:
        os.rename(src, dest)
    except OSError:
        shutil.copy2(src, dest)
        os.unlink(src)


def machine_type(conn: LibvirtConnection) -> str:
    """The versioned name behind the q35 alias, as QEMU reports it now."""
    try:
        xml = conn.run(lambda c: c.getDomainCapabilities(None, "x86_64", "q35", "kvm", 0))
    except libvirt.libvirtError:
        return "q35"
    root = etree.fromstring(xml.encode(), parser=etree.XMLParser(resolve_entities=False))
    found = root.findtext("machine") or ""
    return found if re.fullmatch(r"pc-q35-\d+\.\d+", found) else "q35"


def create_vm(conn: LibvirtConnection, config: Config, vm: NewVm) -> str:
    vm_dir, domain_type = _check(conn, config, vm)
    iso = None
    if vm.iso:
        iso = confine(vm.iso, config)
        if not in_iso_library(iso, config):
            raise ApiException(403, "path.not_allowed", f"{vm.iso} is not in an ISO library")
    existing = (
        existing_disk(vm.existing_disk, config, vm.existing_mode, confined=vm.confined)
        if vm.existing_disk
        else None
    )
    in_place = existing is not None and vm.existing_mode == "in_place"

    uuid = str(uuidlib.uuid4())
    if not in_place:
        vm_dir.mkdir(parents=True)
    moved: tuple[Path, Path] | None = None
    try:
        disks: list[DiskSpec] = []
        if existing is not None:
            fmt = "qcow2" if qemu_img.is_qcow2(existing) else "raw"
            path = existing
            if not in_place:
                path = vm_dir / f"{vm.name}.{fmt}"
                try:
                    if vm.existing_mode == "move":
                        _move_file(existing, path)
                        moved = (path, existing)
                    else:
                        qemu_img.convert(existing, path, fmt)
                except (qemu_img.QemuImgError, OSError) as exc:
                    raise ApiException(500, "library.copy_failed", str(exc)) from exc
            disks.append(DiskSpec(path, fmt, vm.disk_bus))
        elif vm.disk_gib > 0:
            path = vm_dir / f"{vm.name}.{vm.disk_format}"
            try:
                qemu_img.create(path, vm.disk_format, vm.disk_gib, preallocate=vm.preallocate)
            except qemu_img.QemuImgError as exc:
                raise ApiException(500, "vm.disk_failed", str(exc)) from exc
            disks.append(DiskSpec(path, vm.disk_format, vm.disk_bus))
        spec = DomainSpec(
            name=vm.name,
            uuid=uuid,
            profile=PROFILES[vm.profile],
            memory_mib=vm.memory_mib,
            vcpus=vm.vcpus,
            disks=disks,
            iso=iso,
            nics=[
                NicSpec(nic.network, nic.model, nic_target(uuid, i))
                for i, nic in enumerate(vm.nics)
            ],
            uefi=vm.uefi,
            secure_boot=vm.secure_boot,
            tpm=vm.tpm,
            # A disk used where it is gets no folder: libvirt keeps the
            # variables in its own place, as for a VM made in virt-manager.
            nvram=vm_dir / f"{vm.name}_VARS.fd" if vm.uefi and not in_place else None,
            folder=check_folder(vm.folder),
            library=noted_root(config),
            domain_type=domain_type,
            machine=machine_type(conn) if domain_type == "kvm" else "q35",
            cpu_vendor=kvm_state().vendor,
        )
        xml = build_domain(spec)

        conn.run(lambda c: c.defineXML(xml))
    except Exception:
        if moved is not None:
            _move_file(*moved)  # the disk goes back where it was
        if not in_place:
            shutil.rmtree(vm_dir, ignore_errors=True)
        raise
    if vm.start:
        # The VM exists from here on: a failed start leaves it defined, with its files.
        conn.run(lambda c: c.lookupByUUIDString(uuid).create())
    return uuid
