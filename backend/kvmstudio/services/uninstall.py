"""Uninstalling KVM Studio: what may go, then only that.

Same rules as deleting a VM: a file is deleted only inside the library root
(<location>/KVM-Studio/VM), never an ISO, never a file another domain still
needs. Only VMs whose files are in the library are deleted; VMs created
elsewhere (virt-manager) are always kept, and so are the kvmnet networks they
use. The package itself is removed by the helper, after all this.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import helper_client
from ..config import Config, config_dir
from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection
from ..paths import LIBRARY_DIRNAME, in_iso_library, in_library, library_root, resolve
from . import library
from . import networks as net
from .deletion import KeptFile, plan_files, used_elsewhere

# Where the package installs the application.
PACKAGE_ROOT = Path("/opt/kvm-studio")


@dataclass(frozen=True, slots=True)
class NetworkRemoval:
    name: str
    bridge: str
    # VMs using it that stay in any case (created outside KVM Studio).
    used_by_kept: list[str]
    # VMs using it among those KVM Studio would delete.
    used_by_deleted: list[str]


@dataclass(slots=True)
class UninstallPlan:
    library_root: str | None
    vms: list[library.VmDeletion] = field(default_factory=list)
    running: list[str] = field(default_factory=list)
    kept_vms: list[str] = field(default_factory=list)
    extra_files: list[str] = field(default_factory=list)
    keep: list[KeptFile] = field(default_factory=list)
    networks: list[NetworkRemoval] = field(default_factory=list)
    # ISO libraries declared through the helper, and the ACL entries it added.
    iso_libraries: list[str] = field(default_factory=list)
    iso_acl_entries: int = 0
    settings: list[str] = field(default_factory=list)

    @property
    def plan_id(self) -> str:
        """Fingerprint of what the user was shown: execution refuses any other plan."""
        data = json.dumps(asdict(self), sort_keys=True, default=str).encode()
        return hashlib.sha256(data).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Choices:
    delete_vms: bool
    delete_networks: bool
    delete_settings: bool
    remove_iso_acls: bool = False


@dataclass(slots=True)
class UninstallReport:
    deleted_vms: list[str] = field(default_factory=list)
    failed_files: list[str] = field(default_factory=list)
    deleted_networks: list[str] = field(default_factory=list)
    kept_networks: list[str] = field(default_factory=list)
    removed_acls: list[str] = field(default_factory=list)
    # The helper could not forget the libraries or take its rights back.
    iso_failed: bool = False
    deleted_settings: bool = False


def _settings_files(directory: Path) -> list[str]:
    if not directory.is_dir() or directory.is_symlink():
        return []
    return sorted(str(p) for p in directory.rglob("*") if p.is_file() or p.is_symlink())


def plan(
    conn: LibvirtConnection, config: Config, settings_dir: Path | None = None
) -> UninstallPlan:
    root = library_root(config)
    result = UninstallPlan(str(root) if root else None)
    domains = library._snapshot(conn)
    places = library.placements([x for _u, _n, _a, x in domains], config)
    managed = {d[0] for d, p in zip(domains, places, strict=True) if p.managed}
    others = [x for u, _n, _a, x in domains if u not in managed]
    planned: set[str] = set()
    for uuid, name, active, xml in domains:
        if uuid not in managed:
            result.kept_vms.append(name)
            continue
        if active:
            result.running.append(name)
        files = plan_files(xml, others, config)
        result.vms.append(
            library.VmDeletion(uuid, name, files.delete, files.keep, files.delete_nvram)
        )
        planned.update(files.delete)
        planned.update(k.path for k in files.keep)

    if root is not None and root.is_dir():
        used = used_elsewhere(others, config, planned)
        for path in sorted(resolve(root).rglob("*")):
            p = str(path)
            if not path.is_file() or p in planned:
                continue
            if path.is_symlink() or not in_library(p, config):
                result.keep.append(KeptFile(p, "outside_library"))
            elif in_iso_library(p, config) or path.suffix.lower() == ".iso":
                result.keep.append(KeptFile(p, "iso"))
            elif p in used:
                result.keep.append(KeptFile(p, "shared"))
            else:
                result.extra_files.append(p)

    deleted_names = {vm.name for vm in result.vms}
    for info in net.list_networks(conn):
        if not info.managed or info.bridge is None:
            continue
        users = sorted(info.used_by)
        result.networks.append(
            NetworkRemoval(
                info.name,
                info.bridge,
                [u for u in users if u not in deleted_names],
                [u for u in users if u in deleted_names],
            )
        )
    result.iso_libraries, result.iso_acl_entries = _helper_libraries()
    result.settings = _settings_files(settings_dir or config_dir())
    return result


def _helper_libraries() -> tuple[list[str], int]:
    try:
        known = helper_client.call("list_iso_libraries", {})
    except ApiException:
        return [], 0
    paths = [str(lib["path"]) for lib in known["libraries"] if lib["source"] == "user"]
    return paths, int(known["acl_entries"])


def execute(
    conn: LibvirtConnection,
    config: Config,
    choices: Choices,
    plan_id: str,
    settings_dir: Path | None = None,
) -> UninstallReport:
    settings_dir = settings_dir or config_dir()
    current = plan(conn, config, settings_dir)
    if current.plan_id != plan_id:
        raise ApiException(409, "uninstall.plan_changed", "Something changed: review the plan")
    report = UninstallReport()

    if choices.delete_vms and current.vms:
        if current.running:
            raise ApiException(
                409, "library.vms_running", "Power off first: " + ", ".join(current.running)
            )
        library.undefine_vms(conn, current.vms)
        report.deleted_vms = [vm.name for vm in current.vms]
        files = [p for vm in current.vms for p in vm.delete] + current.extra_files
        report.failed_files = library.remove_files(files, config)
        root = library_root(config)
        if root is not None:
            library.remove_empty_dirs(root)
            parent = root.parent
            if parent.name == LIBRARY_DIRNAME and parent.is_dir():
                library.remove_empty_dirs(parent)

    if choices.delete_networks:
        for removal in current.networks:
            users = removal.used_by_kept + ([] if choices.delete_vms else removal.used_by_deleted)
            if users:
                report.kept_networks.append(removal.name)
                continue
            try:
                net.delete_network(conn, removal.name)
                report.deleted_networks.append(removal.name)
            except ApiException:
                report.kept_networks.append(removal.name)

    if current.iso_libraries or current.iso_acl_entries:
        try:
            done = helper_client.call(
                "clear_iso_libraries", {"remove_acls": choices.remove_iso_acls}
            )
            report.removed_acls = list(done["removed"])
        except ApiException:
            report.iso_failed = True

    # Only the KVM Studio settings folder itself, never a link to elsewhere.
    if choices.delete_settings and current.settings and settings_dir.name == "kvm-studio":
        shutil.rmtree(settings_dir, ignore_errors=True)
        report.deleted_settings = not settings_dir.exists()
    return report


def installed_from_package() -> bool:
    return Path(__file__).resolve().is_relative_to(PACKAGE_ROOT)


def package_present() -> bool:
    """False once the package removal took the application files away."""
    return (PACKAGE_ROOT / "lib" / "kvmstudio" / "__init__.py").exists()
