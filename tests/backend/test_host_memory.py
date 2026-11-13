from __future__ import annotations

from pathlib import Path
from typing import Any

import libvirt
import pytest

from kvmstudio.services import host_memory
from kvmstudio.services.host_memory import MemoryWatch, _proc_rss, used_by_vms

GIB = 1024**3


class FakeDomain:
    def __init__(self, name: str, xml: str = "<domain/>", kib: int = 0) -> None:
        self._name, self._xml, self._kib = name, xml, kib

    def name(self) -> str:
        return self._name

    def XMLDesc(self, _flags: int) -> str:
        return self._xml

    def info(self) -> list[int]:
        return [1, self._kib, self._kib, 1, 0]


class FakeConn:
    def __init__(self, records: list[tuple[FakeDomain, dict[str, Any]]]) -> None:
        self.records = records

    def getAllDomainStats(self, stats: int, flags: int) -> Any:
        assert stats == libvirt.VIR_DOMAIN_STATS_BALLOON
        assert flags == libvirt.VIR_CONNECT_GET_ALL_DOMAINS_STATS_ACTIVE
        return self.records


def test_used_memory_is_what_the_vms_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    huge = "<domain><memoryBacking><hugepages/></memoryBacking></domain>"
    monkeypatch.setattr(host_memory, "_proc_rss", lambda name: GIB if name == "noballoon" else None)
    conn = FakeConn(
        [
            # 8 GiB given, 2 GiB held: counts for 2.
            (FakeDomain("small"), {"balloon.current": 8 * 1024**2, "balloon.rss": 2 * 1024**2}),
            # Huge pages are held from the start: counts in full.
            (FakeDomain("huge", huge), {"balloon.current": 4 * 1024**2, "balloon.rss": 1024}),
            (FakeDomain("noballoon"), {}),
            (FakeDomain("unknown"), {}),
        ]
    )
    assert used_by_vms(conn) == (2 + 4 + 1) * GIB  # type: ignore[arg-type]


def test_rss_of_the_qemu_process_from_proc(tmp_path: Path) -> None:
    for pid, args, rss in (
        ("10", b"/usr/bin/qemu\0-name\0guest=Fedora,debug-threads=on\0", 512),
        ("11", b"/usr/bin/qemu\0-name\0guest=Fedora-2,debug-threads=on\0", 64),
    ):
        (tmp_path / pid).mkdir()
        (tmp_path / pid / "cmdline").write_bytes(args)
        (tmp_path / pid / "status").write_text(f"Name:\tqemu\nVmRSS:\t   {rss} kB\n")
    (tmp_path / "self").mkdir()
    assert _proc_rss("Fedora", tmp_path) == 512 * 1024
    assert _proc_rss("Fedora-2", tmp_path) == 64 * 1024
    assert _proc_rss("Debian", tmp_path) is None


def test_warns_once_then_again_after_going_back_under() -> None:
    watch = MemoryWatch()
    limit = 10 * GIB
    assert watch.check(0, None) is False
    assert watch.check(9 * GIB, limit) is False
    assert watch.check(11 * GIB, limit) is True
    # Still over, or just under the limit: no new warning.
    assert watch.check(12 * GIB, limit) is False
    assert watch.check(int(9.8 * GIB), limit) is False
    assert watch.check(int(10.1 * GIB), limit) is False
    # Back under by more than the margin, then over again.
    assert watch.check(9 * GIB, limit) is False
    assert watch.check(11 * GIB, limit) is True
    # A new limit is looked at afresh.
    assert watch.check(11 * GIB, 8 * GIB) is True
    assert watch.check(11 * GIB, None) is False
    assert watch.check(11 * GIB, 8 * GIB) is True
