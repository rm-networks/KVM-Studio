from __future__ import annotations

from pathlib import Path

import pytest

from kvmstudio import check
from kvmstudio.services.host_kvm import kvm_state


def host(
    root: Path,
    *,
    flag: str = "vmx",
    module: str | None = "kvm_intel",
    dev: bool = True,
    nested: str | None = "Y",
    kernels: tuple[str, ...] = ("6.17.1",),
) -> Path:
    (root / "proc").mkdir(parents=True)
    (root / "proc" / "cpuinfo").write_text(f"processor\t: 0\nflags\t\t: fpu {flag}\n")
    if module:
        params = root / "sys" / "module" / module / "parameters"
        params.mkdir(parents=True)
        if nested is not None:
            (params / "nested").write_text(nested + "\n")
    if dev:
        (root / "dev").mkdir()
        (root / "dev" / "kvm").touch()
    for kernel in kernels:
        (root / "lib" / "modules" / kernel).mkdir(parents=True)
    return root


def test_a_working_host(tmp_path: Path) -> None:
    state = kvm_state(host(tmp_path), "6.17.1")
    assert (state.vendor, state.module, state.problem, state.nested) == (
        "intel",
        "kvm_intel",
        None,
        True,
    )


def test_after_a_kernel_update_the_host_must_restart(tmp_path: Path) -> None:
    # Running 6.17.1, whose modules the update removed: kvm_intel cannot load.
    root = host(tmp_path, module=None, dev=False, kernels=("6.18.2",))
    assert kvm_state(root, "6.17.1").problem == "reboot_needed"


@pytest.mark.parametrize(
    ("setup", "problem"),
    [
        ({"flag": "sse2", "module": None, "dev": False}, "no_cpu_support"),
        ({"module": None, "dev": False}, "module_not_loaded"),
        ({"flag": "svm", "module": "kvm_amd", "dev": False}, "no_dev_kvm"),
    ],
)
def test_problems(tmp_path: Path, setup: dict[str, object], problem: str) -> None:
    assert kvm_state(host(tmp_path, **setup), "6.17.1").problem == problem  # type: ignore[arg-type]


def test_nested_off_is_told_by_the_check(tmp_path: Path) -> None:
    root = host(tmp_path, flag="svm", module="kvm_amd", nested="0")
    results = check._check_kvm(root)
    assert [r.level for r in results] == ["ok", "warn"]
    assert "kvm_amd nested=1" in results[1].message
