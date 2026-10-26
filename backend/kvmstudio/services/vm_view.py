"""What the API says about a VM: libvirt state plus its place in the library."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import libvirt

from ..config import Config
from ..libvirt_conn import DomainState, LibvirtConnection, summarize
from .library import Drift, Files, placements


@dataclass(frozen=True, slots=True)
class VmEntry:
    uuid: str
    name: str
    state: DomainState
    vcpus: int
    memory_mib: int
    persistent: bool
    folder: str
    managed: bool
    drift: tuple[Drift, ...]
    files: Files

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["drift"] = list(self.drift)
        return data


def _entries(doms: list[libvirt.virDomain], config: Config) -> list[VmEntry]:
    rows = []
    for dom in doms:
        try:
            rows.append((summarize(dom), dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)))
        except libvirt.libvirtError as exc:
            # Undefined between the listing and the lookup.
            if exc.get_error_code() != libvirt.VIR_ERR_NO_DOMAIN:
                raise
    places = placements([xml for _s, xml in rows], config)
    return [
        VmEntry(
            uuid=s.uuid,
            name=s.name,
            state=s.state,
            vcpus=s.vcpus,
            memory_mib=s.memory_mib,
            persistent=s.persistent,
            folder=p.folder,
            managed=p.managed,
            drift=p.drift,
            files=p.files,
        )
        for (s, _xml), p in zip(rows, places, strict=True)
    ]


def all_vms(conn: LibvirtConnection, config: Config) -> list[VmEntry]:
    return conn.run(lambda c: _entries(c.listAllDomains(), config))


def one_vm(conn: LibvirtConnection, config: Config, uuid: str) -> VmEntry | None:
    # The whole list is needed anyway: a VM folder is only "its own" if no
    # other domain uses it.
    return next((e for e in all_vms(conn, config) if e.uuid == uuid), None)
