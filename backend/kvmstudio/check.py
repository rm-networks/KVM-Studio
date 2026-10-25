"""`kvm-studio --check`: validate the configuration and the host setup."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import libvirt

from .config import Config
from .i18n import t
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
        return Result("warn", "KVM", t("check.kvm_missing"))
    if not os.access("/dev/kvm", os.R_OK | os.W_OK):
        return Result("warn", "KVM", t("check.kvm_denied"))
    return Result("ok", "KVM", t("check.kvm_ok"))


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
            t(
                "check.libvirt_ok",
                uri=host.uri,
                driver=host.driver,
                hypervisor=host.hypervisor_version,
                libvirt=host.libvirt_version,
            ),
        ),
        Result(
            "ok", t("check.domains"), t("check.domains_ok", defined=len(domains), running=running)
        ),
    ]


def _check_vm_location(path: Path | None) -> Result:
    item = t("check.vm_folder")
    if path is None:
        return Result("warn", item, t("check.vm_folder_unset"))
    if not path.is_dir():
        return Result("fail", item, t("check.missing", path=path))
    if not os.access(path, os.W_OK | os.X_OK):
        # Not fatal: with qemu:///system, libvirt creates the disks itself.
        return Result("warn", item, t("check.not_writable", path=path))
    return Result("ok", item, str(path))


def _check_iso_libraries(config: Config) -> list[Result]:
    results = []
    for lib in config.iso_libraries:
        item = t("check.iso_library", name=lib.name)
        if not lib.path.is_dir():
            results.append(Result("warn", item, t("check.missing", path=lib.path)))
        elif not os.access(lib.path, os.R_OK | os.X_OK):
            results.append(Result("warn", item, t("check.not_readable", path=lib.path)))
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
    if "[device-kvm-studio]" in content and all(
        f"interface-name:{name}*" in content for name in ("kvmnet", "ks-", "vnet")
    ):
        return Result("ok", item, t("check.nm_ok", path=installed))
    source = _packaged_nm_conf()
    command = (
        f"sudo install -m 644 {source} {conf_dir}/ && sudo systemctl reload NetworkManager"
        if source
        else t("check.nm_reinstall", path=installed)
    )
    return Result(
        "warn",
        item,
        t("check.nm_missing", path=installed, command=command),
    )


def run_checks(config: Config, config_path: Path) -> list[Result]:
    state = t("check.config_found" if config_path.exists() else "check.config_defaults")
    results = [Result("ok", t("check.config"), f"{config_path} ({state})")]
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
