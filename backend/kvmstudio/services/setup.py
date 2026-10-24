"""First-run assistant: host checks, libvirt group, default networks."""

from __future__ import annotations

import contextlib
import grp
import ipaddress
import os
import pwd
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import libvirt

from ..libvirt_conn import LibvirtConnection
from . import networks as net

Level = Literal["ok", "warn", "fail"]
CheckId = Literal["cpu", "kvm", "nested", "libvirt"]
GroupState = Literal["member", "relogin", "not_member", "no_group", "not_needed"]
LIBVIRT_GROUP = "libvirt"


@dataclass(frozen=True, slots=True)
class Check:
    id: CheckId
    level: Level
    detail: str


@dataclass(frozen=True, slots=True)
class DefaultNetwork:
    name: str
    kind: net.EditableKind
    subnet: str | None
    exists: bool


def _cpu_flags(cpuinfo: Path) -> set[str]:
    try:
        text = cpuinfo.read_text()
    except OSError:
        return set()
    for line in text.splitlines():
        if line.startswith("flags"):
            return set(line.partition(":")[2].split())
    return set()


def host_checks(conn: LibvirtConnection, root: Path = Path("/")) -> list[Check]:
    flags = _cpu_flags(root / "proc" / "cpuinfo")
    vendor = "intel" if "vmx" in flags else "amd" if "svm" in flags else None
    checks = [Check("cpu", "ok" if vendor else "warn", vendor or "")]

    module = next(
        (m for m in ("kvm_intel", "kvm_amd") if (root / "sys" / "module" / m).is_dir()), None
    )
    if (root / "dev" / "kvm").exists():
        checks.append(Check("kvm", "ok", module or "kvm"))
    else:
        checks.append(Check("kvm", "fail", ""))

    nested = ""
    if module:
        with contextlib.suppress(OSError):
            nested = (root / "sys" / "module" / module / "parameters" / "nested").read_text()
    checks.append(Check("nested", "ok" if nested.strip() in ("Y", "1") else "warn", module or ""))

    try:
        info = conn.host_info()
        checks.append(Check("libvirt", "ok", f"libvirt {info.libvirt_version} ({info.uri})"))
    except libvirt.libvirtError as exc:
        checks.append(Check("libvirt", "fail", exc.get_error_message() or str(exc)))
    return checks


def libvirt_group_state(uri: str) -> GroupState:
    """Membership of the current account: in this session, or only after a new login."""
    if uri.rstrip("/").endswith("/session"):
        return "not_needed"
    try:
        group = grp.getgrnam(LIBVIRT_GROUP)
    except KeyError:
        return "no_group"
    if os.getuid() == 0 or group.gr_gid in os.getgroups():
        return "member"
    name = pwd.getpwuid(os.getuid()).pw_name
    if name in group.gr_mem:
        return "relogin"
    return "not_member"


def _existing(networks: list[net.NetworkInfo], name: str) -> net.NetworkInfo | None:
    return next((n for n in networks if n.name == name or n.bridge == name), None)


def default_networks(
    conn: LibvirtConnection, host: Iterable[tuple[str, ipaddress.IPv4Network]] | None = None
) -> list[DefaultNetwork]:
    """kvmnet1 and kvmnet8: present, or the subnet they would get."""
    host = list(net.host_subnets() if host is None else host)
    networks = net.list_networks(conn)
    plan = []
    for name, (kind, _number) in net.DEFAULTS.items():
        found = _existing(networks, name)
        if found is not None:
            plan.append(DefaultNetwork(name, kind, found.subnet, True))
        else:
            subnet = net.free_subnet(conn, host, net.DEFAULT_SUBNET_STARTS[name])
            plan.append(DefaultNetwork(name, kind, str(subnet), False))
    return plan


def create_default_networks(
    conn: LibvirtConnection, host: Iterable[tuple[str, ipaddress.IPv4Network]] | None = None
) -> list[str]:
    """Create the missing default networks; existing ones are left as they are."""
    host = list(net.host_subnets() if host is None else host)
    created = []
    for name, (kind, number) in net.DEFAULTS.items():
        if _existing(net.list_networks(conn), name) is not None:
            continue
        subnet = net.free_subnet(conn, host, net.DEFAULT_SUBNET_STARTS[name])
        spec = net.NetworkSpec(kind, subnet, True, net.default_dhcp(subnet))
        net.create_network(conn, name, number, spec, host=host)
        created.append(name)
    return created
