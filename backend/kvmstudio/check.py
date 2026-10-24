"""`kvm-studio --check`: validate the configuration and the host setup."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import libvirt

from .config import Config
from .libvirt_conn import LibvirtConnection

Level = Literal["ok", "warn", "fail"]
_LABELS: dict[Level, str] = {"ok": " OK ", "warn": "WARN", "fail": "FAIL"}


@dataclass(frozen=True, slots=True)
class Result:
    level: Level
    item: str
    message: str


def _check_kvm() -> Result:
    if not os.path.exists("/dev/kvm"):
        return Result("warn", "KVM", "/dev/kvm not found (virtualization disabled in firmware?)")
    if not os.access("/dev/kvm", os.R_OK | os.W_OK):
        return Result("warn", "KVM", "/dev/kvm exists but is not accessible to this user")
    return Result("ok", "KVM", "/dev/kvm accessible")


def _check_libvirt(uri: str) -> list[Result]:
    conn = LibvirtConnection(uri)
    try:
        host = conn.host_info()
        domains = conn.list_domains()
    except libvirt.libvirtError as exc:
        return [Result("fail", "libvirt", f"{uri}: {exc.get_error_message() or exc}")]
    finally:
        conn.close()
    running = sum(1 for d in domains if d.state == "running")
    return [
        Result(
            "ok",
            "libvirt",
            f"{host.uri} ({host.driver} {host.hypervisor_version}, libvirt {host.libvirt_version})",
        ),
        Result("ok", "Domains", f"{len(domains)} defined, {running} running"),
    ]


def _check_vm_location(path: Path | None) -> Result:
    item = "VM folder"
    if path is None:
        return Result("warn", item, "not set yet (chosen in the first-run assistant)")
    if not path.is_dir():
        return Result("fail", item, f"{path} does not exist")
    if not os.access(path, os.W_OK | os.X_OK):
        # Not fatal: with qemu:///system, libvirt creates the disks itself.
        return Result("warn", item, f"{path} is not writable by this user")
    return Result("ok", item, str(path))


def _check_iso_libraries(config: Config) -> list[Result]:
    results = []
    for lib in config.iso_libraries:
        item = f'ISO library "{lib.name}"'
        if not lib.path.is_dir():
            results.append(Result("warn", item, f"{lib.path} does not exist"))
        elif not os.access(lib.path, os.R_OK | os.X_OK):
            results.append(Result("warn", item, f"{lib.path} is not readable"))
        else:
            results.append(Result("ok", item, str(lib.path)))
    return results


NM_CONF_DIR = Path("/etc/NetworkManager/conf.d")
NM_CONF_NAME = "90-kvm-studio.conf"


def _packaged_nm_conf() -> Path | None:
    """The rule file shipped in the source tree (development installs)."""
    candidate = Path(__file__).resolve().parents[2] / "packaging" / "networkmanager" / NM_CONF_NAME
    return candidate if candidate.is_file() else None


def _check_networkmanager(conf_dir: Path = NM_CONF_DIR) -> Result | None:
    if not conf_dir.parent.is_dir():
        return None  # no NetworkManager on this machine
    item = "NetworkManager"
    installed = conf_dir / NM_CONF_NAME
    try:
        content = installed.read_text()
    except OSError:
        content = ""
    if "[device-kvm-studio]" in content and "interface-name:kvmnet*" in content:
        return Result("ok", item, f"{installed} hides kvmnet* and ks-* interfaces")
    source = _packaged_nm_conf()
    command = (
        f"sudo install -m 644 {source} {conf_dir}/ && sudo systemctl reload NetworkManager"
        if source
        else f"reinstall the kvm-studio package to get {installed}"
    )
    return Result(
        "warn",
        item,
        f"{installed} is missing or outdated: KVM Studio networks show up in the network applet.\n"
        f"       To fix it: {command}",
    )


def run_checks(config: Config, config_path: Path) -> list[Result]:
    state = "found" if config_path.exists() else "not found, using defaults"
    results = [Result("ok", "Configuration", f"{config_path} ({state})")]
    results.append(_check_kvm())
    results += _check_libvirt(config.libvirt.uri)
    results.append(_check_vm_location(config.storage.vm_default_location))
    results += _check_iso_libraries(config)
    if (nm := _check_networkmanager()) is not None:
        results.append(nm)
    return results


def run(config: Config, config_path: Path) -> int:
    results = run_checks(config, config_path)
    for r in results:
        print(f"[{_LABELS[r.level]}] {r.item}: {r.message}")
    return 1 if any(r.level == "fail" for r in results) else 0
