from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kvmstudio import helper_client
from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.services import networks as net
from kvmstudio.services import setup

from .helpers import AUTH, touch


@pytest.fixture(autouse=True)
def quiet_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Do not read the interfaces of the machine running the tests."""
    monkeypatch.setattr(net, "host_subnets", lambda: [])
    monkeypatch.setattr(net, "interface_names", lambda: {"lo", "virbr0"})


def fake_host(root: Path, *, vmx: bool, nested: str | None) -> Path:
    flags = "fpu sse2 vmx" if vmx else "fpu sse2"
    touch(root / "proc" / "cpuinfo").write_text(f"processor\t: 0\nflags\t\t: {flags}\n")
    if vmx:
        touch(root / "dev" / "kvm")
        params = root / "sys" / "module" / "kvm_intel" / "parameters"
        params.mkdir(parents=True)
        if nested is not None:
            (params / "nested").write_text(nested + "\n")
    return root


def levels(checks: list[setup.Check]) -> dict[str, str]:
    return {c.id: c.level for c in checks}


def test_host_checks_on_a_kvm_host(conn: LibvirtConnection, tmp_path: Path) -> None:
    checks = setup.host_checks(conn, fake_host(tmp_path, vmx=True, nested="Y"))
    assert levels(checks) == {"cpu": "ok", "kvm": "ok", "nested": "ok", "libvirt": "ok"}
    assert checks[0].detail == "intel"


def test_host_checks_without_virtualization(conn: LibvirtConnection, tmp_path: Path) -> None:
    checks = setup.host_checks(conn, fake_host(tmp_path, vmx=False, nested=None))
    assert levels(checks) == {"cpu": "warn", "kvm": "fail", "nested": "warn", "libvirt": "ok"}


def test_nested_disabled(conn: LibvirtConnection, tmp_path: Path) -> None:
    checks = setup.host_checks(conn, fake_host(tmp_path, vmx=True, nested="N"))
    assert levels(checks)["nested"] == "warn"


def test_status_and_default_networks(client: TestClient) -> None:
    status = client.get("/api/setup", headers=AUTH).json()
    assert status["needed"] is True
    assert {n["name"]: n["exists"] for n in status["networks"]} == {
        "kvmnet1": False,
        "kvmnet8": False,
    }
    assert client.post("/api/setup/networks", headers=AUTH).json() == ["kvmnet1", "kvmnet8"]
    # Existing networks are never touched again.
    assert client.post("/api/setup/networks", headers=AUTH).json() == []
    status = client.get("/api/setup", headers=AUTH).json()
    assert all(n["exists"] for n in status["networks"])
    for name in ("kvmnet1", "kvmnet8"):
        assert client.delete(f"/api/networks/{name}", headers=AUTH).status_code == 204


def test_session_uri_needs_no_group() -> None:
    assert setup.libvirt_group_state("qemu:///session") == "not_needed"


def test_join_libvirt_group(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(setup, "libvirt_group_state", lambda uri: "not_member")

    def fake_call(op: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append((op, params))
        return {}

    monkeypatch.setattr(helper_client, "call", fake_call)
    r = client.post("/api/setup/libvirt-group", headers=AUTH)
    assert r.json() == {"libvirt_group": "relogin"}
    # Nothing identifying the user is sent: the helper asks the kernel.
    assert calls == [("join_libvirt", {})]


def test_join_libvirt_group_when_already_member(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(setup, "libvirt_group_state", lambda uri: "member")
    monkeypatch.setattr(helper_client, "call", lambda op, params: pytest.fail("called"))
    assert client.post("/api/setup/libvirt-group", headers=AUTH).json() == {
        "libvirt_group": "member"
    }


def test_join_libvirt_group_without_helper(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(setup, "libvirt_group_state", lambda uri: "not_member")
    monkeypatch.setenv("KVMSTUDIO_HELPER_SOCKET", str(tmp_path / "none.sock"))
    r = client.post("/api/setup/libvirt-group", headers=AUTH)
    assert (r.status_code, r.json()["error"]["code"]) == (503, "helper.unavailable")
