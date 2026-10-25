"""lan_port: the HTTPS port of LAN sharing, opened and closed in the firewall."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvmstudio_helper.config import HelperConfig
from kvmstudio_helper.errors import HelperError
from kvmstudio_helper.ops import lan_port
from kvmstudio_helper.polkit import Peer

PEER = Peer(4242, 1000, 1000)


@pytest.fixture
def config(tmp_path: Path) -> HelperConfig:
    return HelperConfig(tmp_path / "h.sock", 107, (), tmp_path / "state" / "helper-state.json")


class Recorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], fds: tuple[int, ...]) -> None:
        self.calls.append(argv)


def tools(monkeypatch: pytest.MonkeyPatch, *found: str) -> None:
    monkeypatch.setattr("shutil.which", lambda name, path=None: name in found or None)


def test_firewalld_gets_the_packaged_service(
    monkeypatch: pytest.MonkeyPatch, config: HelperConfig
) -> None:
    tools(monkeypatch, "firewall-cmd", "ufw")
    run = Recorder()
    result = lan_port.prepare({"open": True, "port": 60443}, config, PEER)(run)
    assert result == {"firewall": "firewalld"}
    assert run.calls == [
        ["firewall-cmd", "--state"],
        ["firewall-cmd", "--permanent", "--add-service=kvm-studio"],
        ["firewall-cmd", "--add-service=kvm-studio"],
    ]
    assert json.loads(lan_port.state_file(config).read_text()) == {
        "tool": "firewalld",
        "port": 60443,
    }

    run = Recorder()
    assert lan_port.prepare({"open": False, "port": 60443}, config, PEER)(run) == {"firewall": None}
    assert run.calls == [
        ["firewall-cmd", "--permanent", "--remove-service=kvm-studio"],
        ["firewall-cmd", "--remove-service=kvm-studio"],
    ]
    assert not lan_port.state_file(config).exists()


def test_another_port_is_opened_alone_and_the_old_one_closed(
    monkeypatch: pytest.MonkeyPatch, config: HelperConfig
) -> None:
    tools(monkeypatch, "firewall-cmd")
    lan_port.prepare({"open": True, "port": 60443}, config, PEER)(Recorder())
    run = Recorder()
    lan_port.prepare({"open": True, "port": 61443}, config, PEER)(run)
    assert ["firewall-cmd", "--remove-service=kvm-studio"] in run.calls
    assert ["firewall-cmd", "--permanent", "--add-port=61443/tcp"] in run.calls


def test_ufw_when_firewalld_is_not_running(
    monkeypatch: pytest.MonkeyPatch, config: HelperConfig
) -> None:
    tools(monkeypatch, "firewall-cmd", "ufw")

    def run(argv: list[str], fds: tuple[int, ...]) -> None:
        calls.append(argv)
        if argv == ["firewall-cmd", "--state"]:
            raise HelperError("failed", "not running")

    calls: list[list[str]] = []
    assert lan_port.prepare({"open": True, "port": 60443}, config, PEER)(run) == {"firewall": "ufw"}
    assert calls[-1] == ["ufw", "allow", "60443/tcp", "comment", "kvm-studio"]
    calls.clear()
    lan_port.close_recorded(config, run)
    assert calls == [["ufw", "delete", "allow", "60443/tcp"]]


def test_no_firewall_nothing_to_open(monkeypatch: pytest.MonkeyPatch, config: HelperConfig) -> None:
    tools(monkeypatch)
    run = Recorder()
    assert lan_port.prepare({"open": True, "port": 60443}, config, PEER)(run) == {"firewall": None}
    assert run.calls == []


@pytest.mark.parametrize(
    "params",
    [
        {"open": True, "port": 80},
        {"open": True, "port": True},
        {"open": "yes", "port": 60443},
        {"open": True, "port": 60443, "zone": "public"},
    ],
)
def test_invalid_requests(config: HelperConfig, params: dict[str, object]) -> None:
    with pytest.raises(HelperError):
        lan_port.prepare(params, config, PEER)
