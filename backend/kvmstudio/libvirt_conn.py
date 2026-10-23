"""Shared libvirt connection, reopened automatically when it drops."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypeVar

import libvirt

T = TypeVar("T")

DomainState = Literal[
    "running", "paused", "shutting_down", "shutoff", "crashed", "suspended", "unknown"
]

_STATES: dict[int, DomainState] = {
    libvirt.VIR_DOMAIN_NOSTATE: "unknown",
    libvirt.VIR_DOMAIN_RUNNING: "running",
    libvirt.VIR_DOMAIN_BLOCKED: "running",
    libvirt.VIR_DOMAIN_PAUSED: "paused",
    libvirt.VIR_DOMAIN_SHUTDOWN: "shutting_down",
    libvirt.VIR_DOMAIN_SHUTOFF: "shutoff",
    libvirt.VIR_DOMAIN_CRASHED: "crashed",
    libvirt.VIR_DOMAIN_PMSUSPENDED: "suspended",
}

# By default libvirt-python prints every error on stderr, even the ones we handle.
libvirt.registerErrorHandler(lambda _ctx, _err: None, None)


@dataclass(frozen=True, slots=True)
class DomainSummary:
    uuid: str
    name: str
    state: DomainState
    vcpus: int
    memory_mib: int
    persistent: bool


@dataclass(frozen=True, slots=True)
class HostInfo:
    uri: str
    hostname: str
    driver: str
    libvirt_version: str
    hypervisor_version: str


def format_version(packed: int) -> str:
    """libvirt packs versions as major * 1_000_000 + minor * 1000 + release."""
    return f"{packed // 1_000_000}.{packed // 1000 % 1000}.{packed % 1000}"


def _alive(conn: libvirt.virConnect) -> bool:
    try:
        return conn.isAlive() == 1
    except libvirt.libvirtError:
        return False


class LibvirtConnection:
    def __init__(self, uri: str) -> None:
        self.uri = uri
        self._conn: libvirt.virConnect | None = None
        self._lock = threading.Lock()

    def _get(self) -> libvirt.virConnect:
        with self._lock:
            if self._conn is not None and _alive(self._conn):
                return self._conn
            self._discard()
            self._conn = libvirt.open(self.uri)
            return self._conn

    def _discard(self) -> None:
        if self._conn is not None:
            with contextlib.suppress(libvirt.libvirtError):
                self._conn.close()
            self._conn = None

    def close(self) -> None:
        with self._lock:
            self._discard()

    def run(self, op: Callable[[libvirt.virConnect], T]) -> T:
        """Run op on the connection, retrying once if the link died meanwhile."""
        conn = self._get()
        try:
            return op(conn)
        except libvirt.libvirtError:
            if _alive(conn):
                raise
        return op(self._get())

    def host_info(self) -> HostInfo:
        def op(conn: libvirt.virConnect) -> HostInfo:
            return HostInfo(
                uri=conn.getURI(),
                hostname=conn.getHostname(),
                driver=conn.getType(),
                libvirt_version=format_version(conn.getLibVersion()),
                hypervisor_version=format_version(conn.getVersion()),
            )

        return self.run(op)

    def list_domains(self) -> list[DomainSummary]:
        return self.run(_list_domains)


def _list_domains(conn: libvirt.virConnect) -> list[DomainSummary]:
    domains = []
    for dom in conn.listAllDomains():
        try:
            state, max_mem_kib, _mem, vcpus, _cpu_time = dom.info()
            domains.append(
                DomainSummary(
                    uuid=dom.UUIDString(),
                    name=dom.name(),
                    state=_STATES.get(state, "unknown"),
                    vcpus=vcpus,
                    memory_mib=max_mem_kib // 1024,
                    persistent=dom.isPersistent() == 1,
                )
            )
        except libvirt.libvirtError as exc:
            # The domain was undefined between the listing and the lookup.
            if exc.get_error_code() != libvirt.VIR_ERR_NO_DOMAIN:
                raise
    return domains
