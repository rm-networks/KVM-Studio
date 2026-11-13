"""Host memory taken by the running VMs, and the warning past the limit of Preferences.

The figure is the memory the VMs really hold on the host, not what they were
given: libvirt reads the resident size of each QEMU process (balloon.rss, from
/proc/<pid>/stat), all domains in one call. A VM backed by huge pages holds
them from the start and outside that figure: it counts in full. Without
balloon.rss, the QEMU process is looked for in /proc; a VM found nowhere
counts for nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import libvirt
from lxml import etree

KIB = 1024
# Seconds between two measures: one libvirt call for all the domains.
CHECK_INTERVAL = 15
# Once warned, the total has to go this far below the limit to warn again.
REARM_RATIO = 0.95


def _hugepages(dom: libvirt.virDomain) -> bool:
    root = etree.fromstring(dom.XMLDesc(0).encode())
    return root.find("memoryBacking/hugepages") is not None


def _proc_rss(name: str, proc: Path = Path("/proc")) -> int | None:
    """Resident size in bytes of the QEMU process of this domain, if it can be read."""
    # QEMU started by libvirt: -name guest=<name>,debug-threads=on
    wanted = f"guest={name}".encode()
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = (entry / "cmdline").read_bytes().split(b"\0")
            if not any(a == wanted or a.startswith(wanted + b",") for a in args):
                continue
            for line in (entry / "status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * KIB
        except (OSError, ValueError, IndexError):
            continue
    return None


def used_by_vms(conn: libvirt.virConnect) -> int:
    """Bytes held on the host by every running domain, KVM Studio's or not."""
    total = 0
    records = conn.getAllDomainStats(
        libvirt.VIR_DOMAIN_STATS_BALLOON, libvirt.VIR_CONNECT_GET_ALL_DOMAINS_STATS_ACTIVE
    )
    for dom, stats in records:
        try:
            if _hugepages(dom):
                total += int(stats.get("balloon.current") or dom.info()[2]) * KIB
            elif "balloon.rss" in stats:
                total += int(stats["balloon.rss"]) * KIB
            else:
                total += _proc_rss(dom.name()) or 0
        except libvirt.libvirtError:
            # Stopped between the two calls.
            continue
    return total


@dataclass
class MemoryWatch:
    """Says when to warn: once over the limit, then again only after going back under it."""

    armed: bool = True
    limit: int | None = None

    def check(self, used: int, limit: int | None) -> bool:
        if limit != self.limit:
            self.limit = limit
            self.armed = True
        if limit is None:
            return False
        if self.armed and used > limit:
            self.armed = False
            return True
        if not self.armed and used < limit * REARM_RATIO:
            self.armed = True
        return False


def gib_to_bytes(gib: float) -> int:
    return int(gib * KIB**3)
