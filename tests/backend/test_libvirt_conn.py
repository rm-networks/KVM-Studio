from __future__ import annotations

import libvirt
import pytest

from kvmstudio.libvirt_conn import LibvirtConnection, format_version


def test_lists_test_driver_domain(conn: LibvirtConnection) -> None:
    domains = conn.list_domains()
    assert [d.name for d in domains] == ["test"]
    dom = domains[0]
    assert dom.state == "running"
    assert dom.vcpus >= 1
    assert dom.memory_mib > 0
    assert dom.persistent
    assert len(dom.uuid) == 36


def test_host_info(conn: LibvirtConnection) -> None:
    host = conn.host_info()
    assert host.uri == "test:///default"
    assert host.driver == "TEST"
    assert host.libvirt_version.count(".") == 2


def test_reconnects_after_the_link_drops(conn: LibvirtConnection) -> None:
    conn.list_domains()
    assert conn._conn is not None
    conn._conn.close()
    assert [d.name for d in conn.list_domains()] == ["test"]


def test_unreachable_uri_raises() -> None:
    conn = LibvirtConnection("test:///nonexistent/kvm-studio.xml")
    with pytest.raises(libvirt.libvirtError):
        conn.list_domains()


def test_format_version() -> None:
    assert format_version(12_000_000) == "12.0.0"
    assert format_version(10_002_002) == "10.2.2"
