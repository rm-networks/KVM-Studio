"""Guest OS profiles: sensible hardware for each kind of system (F-24).

Windows defaults to SATA disks and e1000e cards, which its installer knows
without extra drivers; Linux and BSD get virtio.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Family = Literal["windows", "linux", "bsd", "other"]
DiskBus = Literal["virtio", "scsi", "sata", "nvme", "ide"]
NicModel = Literal["virtio", "e1000e", "rtl8139", "vmxnet3"]


@dataclass(frozen=True, slots=True)
class Profile:
    id: str
    family: Family
    memory_mib: int
    vcpus: int
    disk_gib: int
    disk_bus: DiskBus
    nic_model: NicModel
    nics: int
    uefi: bool
    secure_boot: bool
    tpm: bool
    serial: bool
    nested: bool
    video: Literal["virtio", "bochs"]
    # Matched against the ISO file name to guess the profile.
    iso_hint: str


PROFILES: dict[str, Profile] = {
    p.id: p
    for p in [
        Profile("windows11", "windows", 4096, 2, 64, "sata", "e1000e", 1, True, True, True,
                False, False, "bochs", r"win(dows)?[ _-]?11"),
        Profile("windows10", "windows", 4096, 2, 64, "sata", "e1000e", 1, True, False, False,
                False, False, "bochs", r"win(dows)?[ _-]?10"),
        Profile("windows-server", "windows", 4096, 2, 64, "sata", "e1000e", 1, True, True, False,
                False, False, "bochs", r"server|srv20\d\d|ws20\d\d"),
        Profile("linux", "linux", 2048, 2, 25, "virtio", "virtio", 1, True, False, False,
                False, False, "virtio",
                r"debian|ubuntu|fedora|rhel|rocky|alma|centos|mint|kali|arch|opensuse|linux"),
        Profile("firewall", "bsd", 2048, 2, 20, "virtio", "virtio", 3, True, False, False,
                True, False, "virtio",
                r"opnsense|pfsense|freebsd|fortigate|fortios|stormshield|vyos"),
        Profile("nested", "linux", 8192, 4, 64, "sata", "e1000e", 1, True, False, False,
                False, True, "virtio", r"proxmox|pve|esxi|vmvisor|xcp"),
        Profile("other", "other", 2048, 2, 20, "sata", "e1000e", 1, True, False, False,
                False, False, "bochs", r"$^"),
    ]
}  # fmt: skip


def guess_profile(iso_name: str) -> str:
    """Profile id suggested by an ISO file name, "other" when nothing matches."""
    name = iso_name.lower()
    # Windows Server before Windows 10/11: "Windows Server 2025" also says "windows".
    for profile_id in ["windows-server", "windows11", "windows10", "firewall", "nested", "linux"]:
        if re.search(PROFILES[profile_id].iso_hint, name):
            if profile_id == "windows-server" and "win" not in name and "srv" not in name:
                continue
            return profile_id
    return "other"
