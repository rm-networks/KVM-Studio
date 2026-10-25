"""Uninstall: only KVM Studio VMs and files inside the library ever go."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterator
from pathlib import Path

import libvirt
import pytest
from fastapi.testclient import TestClient

from kvmstudio import helper_client
from kvmstudio.config import Config
from kvmstudio.errors import ApiException
from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.services import networks as net
from kvmstudio.services import uninstall

from .helpers import AUTH, add_domain, touch
from .helpers import domain_xml as make_xml


@pytest.fixture(autouse=True)
def quiet_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "host_subnets", lambda: [])
    monkeypatch.setattr(net, "interface_names", lambda: {"lo", "virbr0"})


def with_nic(xml: str, network: str) -> str:
    nic = f"<interface type='network'><source network='{network}'/></interface>"
    return xml.replace("</devices>", nic + "</devices>")


@pytest.fixture
def lab(
    conn: LibvirtConnection,
    define: list[libvirt.virDomain],
    library: Path,
    tmp_path: Path,
) -> Iterator[dict[str, Path]]:
    """A KVM Studio VM, a virt-manager VM sharing one of its disks, two kvmnet networks."""
    for name, number, third in (("LAN-1", 3, 103), ("spare", 4, 104)):
        subnet = ipaddress.IPv4Network(f"192.168.{third}.0/24")
        spec = net.NetworkSpec("host_only", subnet, True, net.default_dhcp(subnet))
        net.create_network(conn, name, number, spec, host=[])
    vm_dir = library / "Lab" / "web"
    files = {
        "disk": touch(vm_dir / "web.qcow2"),
        "iso": touch(vm_dir / "install.iso"),
        "shared": touch(library / "data.raw"),
        "extra": touch(library / "notes.txt"),
        "outside": touch(tmp_path / "elsewhere" / "outside.qcow2"),
    }
    web = make_xml(
        "web",
        [
            ("disk", str(files["disk"])),
            ("cdrom", str(files["iso"])),
            ("disk", str(files["shared"])),
        ],
    )
    add_domain(conn, define, with_nic(web, "LAN-1"))
    outside = make_xml("outside", [("disk", str(files["outside"])), ("disk", str(files["shared"]))])
    add_domain(conn, define, with_nic(outside, "LAN-1"))
    yield files

    def cleanup(c: libvirt.virConnect) -> None:
        for network in c.listAllNetworks():
            if network.name() in ("LAN-1", "spare"):
                if network.isActive():
                    network.destroy()
                network.undefine()

    conn.run(cleanup)


@pytest.fixture
def settings(tmp_path: Path) -> Path:
    directory = tmp_path / "config" / "kvm-studio"
    touch(directory / "config.toml")
    touch(directory / "guest.hash")
    return directory


def test_plan_lists_exactly_what_may_go(
    conn: LibvirtConnection, lib_config: Config, lab: dict[str, Path], settings: Path
) -> None:
    plan = uninstall.plan(conn, lib_config, settings)
    assert [vm.name for vm in plan.vms] == ["web"]
    assert plan.vms[0].delete == [str(lab["disk"])]
    kept = {k.path: k.reason for k in plan.vms[0].keep}
    assert kept == {str(lab["iso"]): "iso", str(lab["shared"]): "shared"}
    assert "outside" in plan.kept_vms
    assert "test" in plan.kept_vms
    assert plan.extra_files == [str(lab["extra"])]
    by_name = {n.name: n for n in plan.networks}
    assert (by_name["LAN-1"].used_by_kept, by_name["LAN-1"].used_by_deleted) == (
        ["outside"],
        ["web"],
    )
    assert by_name["spare"].used_by_kept == []
    assert plan.settings == [str(settings / "config.toml"), str(settings / "guest.hash")]


def test_remove_everything(
    conn: LibvirtConnection,
    lib_config: Config,
    lab: dict[str, Path],
    settings: Path,
    library: Path,
) -> None:
    plan = uninstall.plan(conn, lib_config, settings)
    choices = uninstall.Choices(delete_vms=True, delete_networks=True, delete_settings=True)
    report = uninstall.execute(conn, lib_config, choices, plan.plan_id, settings)
    assert report.deleted_vms == ["web"]
    assert report.failed_files == []
    for key in ("disk", "extra"):
        assert not lab[key].exists()
    # Never an ISO, never a disk a kept VM uses, never a file outside the library.
    for key in ("iso", "shared", "outside"):
        assert lab[key].exists()
    names = conn.run(lambda c: [d.name() for d in c.listAllDomains()])
    assert "web" not in names
    assert "outside" in names
    # Other tests may leave networks behind in the shared test driver.
    assert "spare" in report.deleted_networks
    assert "LAN-1" in report.kept_networks
    assert report.deleted_settings
    assert not settings.exists()
    assert library.exists()  # still holds the ISO and the shared disk


def test_keep_everything_changes_nothing(
    conn: LibvirtConnection, lib_config: Config, lab: dict[str, Path], settings: Path
) -> None:
    plan = uninstall.plan(conn, lib_config, settings)
    choices = uninstall.Choices(delete_vms=False, delete_networks=False, delete_settings=False)
    report = uninstall.execute(conn, lib_config, choices, plan.plan_id, settings)
    assert report == uninstall.UninstallReport()
    assert all(path.exists() for path in lab.values())
    assert settings.exists()


@pytest.mark.parametrize("remove", [True, False])
def test_iso_rights_are_taken_back_on_request(
    conn: LibvirtConnection,
    lib_config: Config,
    settings: Path,
    monkeypatch: pytest.MonkeyPatch,
    remove: bool,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def helper(op: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((op, params))
        if op == "list_iso_libraries":
            libraries = [{"path": "/srv/admin", "source": "admin"}]
            return {
                "libraries": [*libraries, {"path": "/home/u/ISO", "source": "user"}],
                "acl_entries": 3,
            }
        return {"removed": ["/home/u/ISO/a.iso u:107:r"] if params["remove_acls"] else []}

    monkeypatch.setattr(helper_client, "call", helper)
    plan = uninstall.plan(conn, lib_config, settings)
    assert (plan.iso_libraries, plan.iso_acl_entries) == (["/home/u/ISO"], 3)
    choices = uninstall.Choices(False, False, False, remove_iso_acls=remove)
    report = uninstall.execute(conn, lib_config, choices, plan.plan_id, settings)
    # The libraries are forgotten either way: the package goes.
    assert calls[-1] == ("clear_iso_libraries", {"remove_acls": remove})
    assert len(report.removed_acls) == (1 if remove else 0)
    assert report.iso_failed is False


def test_networks_used_by_kept_vms_stay(
    conn: LibvirtConnection, lib_config: Config, lab: dict[str, Path], settings: Path
) -> None:
    plan = uninstall.plan(conn, lib_config, settings)
    choices = uninstall.Choices(delete_vms=False, delete_networks=True, delete_settings=False)
    report = uninstall.execute(conn, lib_config, choices, plan.plan_id, settings)
    assert "spare" in report.deleted_networks
    assert report.kept_networks == ["LAN-1"]


def test_changed_plan_is_refused(
    conn: LibvirtConnection, lib_config: Config, lab: dict[str, Path], settings: Path
) -> None:
    plan = uninstall.plan(conn, lib_config, settings)
    touch(lab["disk"].parent / "new-snapshot.qcow2")
    choices = uninstall.Choices(delete_vms=True, delete_networks=False, delete_settings=False)
    with pytest.raises(ApiException) as exc:
        uninstall.execute(conn, lib_config, choices, plan.plan_id, settings)
    assert exc.value.code == "uninstall.plan_changed"
    assert lab["disk"].exists()


def test_symlinked_settings_folder_is_not_followed(
    conn: LibvirtConnection, lib_config: Config, tmp_path: Path
) -> None:
    target = tmp_path / "precious"
    touch(target / "keep.txt")
    link = tmp_path / "cfg" / "kvm-studio"
    link.parent.mkdir()
    link.symlink_to(target)
    assert uninstall.plan(conn, lib_config, link).settings == []


def test_api(lib_client: TestClient, lab: dict[str, Path]) -> None:
    plan = lib_client.get("/api/uninstall/plan", headers=AUTH).json()
    assert plan["packaged"] is False
    assert [vm["name"] for vm in plan["vms"]] == ["web"]
    body = {
        "plan_id": "0" * 16,
        "delete_vms": True,
        "delete_networks": False,
        "delete_settings": False,
    }
    r = lib_client.post("/api/uninstall", json=body, headers=AUTH)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "uninstall.plan_changed")
    assert lab["disk"].exists()
    r = lib_client.post("/api/uninstall/package", headers=AUTH)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "uninstall.not_packaged")
    assert lib_client.get("/api/uninstall/package", headers=AUTH).json()["packaged"] is False


# kvm-studio --uninstall


class _Shared:
    """The fixture's connection, which the CLI must not close."""

    def __init__(self, conn: LibvirtConnection) -> None:
        self._conn = conn

    def __getattr__(self, name: str) -> object:
        return getattr(self._conn, name)

    def close(self) -> None:
        pass


def run_cli(
    monkeypatch: pytest.MonkeyPatch,
    conn: LibvirtConnection,
    config: Config,
    answers: list[str],
) -> tuple[int, str]:
    from kvmstudio import uninstall_cli

    monkeypatch.setattr(uninstall_cli, "LibvirtConnection", lambda uri: _Shared(conn))
    lines: list[str] = []
    replies = iter(answers)
    code = uninstall_cli.run(config, ask=lambda q: next(replies), out=lines.append)
    return code, "\n".join(lines)


def test_cli_asks_twice_before_deleting_vms(
    monkeypatch: pytest.MonkeyPatch,
    conn: LibvirtConnection,
    lib_config: Config,
    lab: dict[str, Path],
    settings: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(settings.parent))
    # VMs: yes then yes, networks: no, settings: no, go ahead: yes.
    code, out = run_cli(monkeypatch, conn, lib_config, ["y", "o", "n", "n", "y"])
    assert code == 0
    assert str(lab["disk"]) in out
    assert "Deleted VMs: web" in out
    assert not lab["disk"].exists()
    assert lab["iso"].exists()
    assert settings.exists()


def test_cli_second_confirmation_refused(
    monkeypatch: pytest.MonkeyPatch,
    conn: LibvirtConnection,
    lib_config: Config,
    lab: dict[str, Path],
    settings: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(settings.parent))
    code, out = run_cli(monkeypatch, conn, lib_config, ["y", "n", "n", "n", "y"])
    assert code == 0
    assert "virtual machines: keep" in out
    assert lab["disk"].exists()


def test_cli_cancel(
    monkeypatch: pytest.MonkeyPatch,
    conn: LibvirtConnection,
    lib_config: Config,
    lab: dict[str, Path],
    settings: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(settings.parent))
    code, out = run_cli(monkeypatch, conn, lib_config, ["y", "y", "y", "y", "n"])
    assert code == 1
    assert "nothing was changed" in out
    assert lab["disk"].exists()
    assert settings.exists()
