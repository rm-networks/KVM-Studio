"""State of KVM on the host, read again at each start: a kernel or package
update can leave it unusable until the next reboot.

The usual case after a kernel update: the running kernel's modules were
removed (only the newest kernels are kept), so kvm_intel or kvm_amd cannot be
loaded any more and /dev/kvm is missing until the host restarts.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Problem = Literal[
    "no_cpu_support",  # neither vmx nor svm: disabled in the firmware, or no support
    "reboot_needed",  # the running kernel's modules are gone (kernel update)
    "module_not_loaded",  # kvm_intel / kvm_amd not loaded
    "no_dev_kvm",  # module loaded, still no /dev/kvm
    "dev_kvm_denied",  # /dev/kvm not readable and writable by this account
]


@dataclass(frozen=True, slots=True)
class KvmState:
    vendor: Literal["intel", "amd"] | None
    module: str | None
    problem: Problem | None
    # None when unknown (no module loaded).
    nested: bool | None
    kernel: str


def cpu_flags(cpuinfo: Path) -> set[str]:
    try:
        text = cpuinfo.read_text()
    except OSError:
        return set()
    for line in text.splitlines():
        if line.startswith("flags"):
            return set(line.partition(":")[2].split())
    return set()


def kvm_state(root: Path = Path("/"), kernel: str | None = None) -> KvmState:
    kernel = kernel or os.uname().release
    flags = cpu_flags(root / "proc" / "cpuinfo")
    vendor: Literal["intel", "amd"] | None = (
        "intel" if "vmx" in flags else "amd" if "svm" in flags else None
    )
    module = next(
        (m for m in ("kvm_intel", "kvm_amd") if (root / "sys" / "module" / m).is_dir()), None
    )
    nested = None
    if module:
        with contextlib.suppress(OSError):
            value = (root / "sys" / "module" / module / "parameters" / "nested").read_text()
            nested = value.strip() in ("Y", "1")

    dev = root / "dev" / "kvm"
    problem: Problem | None = None
    if not dev.exists():
        if module is None and not (root / "lib" / "modules" / kernel).is_dir():
            problem = "reboot_needed"
        elif vendor is None:
            problem = "no_cpu_support"
        elif module is None:
            problem = "module_not_loaded"
        else:
            problem = "no_dev_kvm"
    elif root == Path("/") and not os.access(dev, os.R_OK | os.W_OK):
        problem = "dev_kvm_denied"
    return KvmState(vendor, module, problem, nested, kernel)
