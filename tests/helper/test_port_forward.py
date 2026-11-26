"""set_port_forwards: rules checked by the helper, written to its own nftables table."""

from __future__ import annotations

import grp
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from kvmstudio_helper import server
from kvmstudio_helper.config import HelperConfig
from kvmstudio_helper.errors import HelperError
from kvmstudio_helper.ops import port_forward
from kvmstudio_helper.polkit import Peer

PEER = Peer(4242, 1000, 1000)
NET_XML = (
    "<network><name>{name}</name><bridge name='kvmnet8'/>"
    "<ip address='192.168.108.1' netmask='255.255.255.0'/></network>"
)


@pytest.fixture
def config(tmp_path: Path) -> HelperConfig:
    return HelperConfig(tmp_path / "h.sock", 107, (), tmp_path / "state" / "helper-state.json")


@pytest.fixture(autouse=True)
def libvirt_networks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake(args: list[str]) -> str:
        assert args[0] == "net-dumpxml"
        if args[1] != "kvmnet8":
            raise HelperError("not_found", "no network")
        return NET_XML.format(name=args[1])

    monkeypatch.setattr(port_forward, "virsh", fake)
    monkeypatch.setattr(port_forward, "SYSCTL", tmp_path / "sysctl")


class Recorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], fds: tuple[int, ...]) -> None:
        self.calls.append(argv)


def rule(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "proto": "tcp",
        "host_address": "127.0.0.1",
        "host_port": 8080,
        "vm_ip": "192.168.108.50",
        "vm_port": 80,
        "description": "web",
    }
    base.update(over)
    return base


def call(config: HelperConfig, params: dict[str, Any], runner: Recorder | None = None,
         allowed: bool = True) -> dict[str, Any]:  # fmt: skip
    asked: list[str] = []

    def authorizer(action: str, peer: Peer) -> bool:
        asked.append(action)
        return allowed

    raw = json.dumps({"op": "set_port_forwards", "params": params}).encode()
    answer = server.handle(raw, PEER, config, authorizer=authorizer, runner=runner or Recorder())
    answer["asked"] = asked
    return answer


LIBVIRT_GID = 990


@pytest.fixture(autouse=True)
def libvirt_group(monkeypatch: pytest.MonkeyPatch) -> None:
    group = SimpleNamespace(gr_gid=LIBVIRT_GID)
    monkeypatch.setattr(grp, "getgrnam", lambda name: group)


def test_rules_are_written_to_our_own_table(config: HelperConfig, tmp_path: Path) -> None:
    (tmp_path / "sysctl" / "kvmnet8").mkdir(parents=True)
    runner = Recorder()
    rules = [rule(), rule(proto="udp", host_address="0.0.0.0", host_port=5353, vm_port=53)]  # noqa: S104
    answer = call(config, {"network": "kvmnet8", "rules": rules}, runner)
    assert answer["ok"], answer
    assert answer["asked"] == ["org.kvmstudio.helper.port-forward"]
    assert runner.calls == [["nft", "-f", str(port_forward.ruleset_file(config))]]
    text = port_forward.ruleset_file(config).read_text()
    assert "table inet kvmstudio {" in text
    assert "ip daddr 127.0.0.1 tcp dport 8080 dnat ip to 192.168.108.50:80" in text
    assert "fib daddr type local udp dport 5353 dnat ip to 192.168.108.50:53" in text
    assert 'iifname "kvmnet8" ip daddr 127.0.0.0/8 drop' in text
    # Loopback rules never come in from outside.
    assert "prerouting" in text
    assert "ip daddr 127.0.0.1 tcp dport 8080 dnat" not in text.split("chain output")[0]
    assert (tmp_path / "sysctl" / "kvmnet8" / "route_localnet").read_text() == "1\n"
    # No other table is ever named.
    assert set(re.findall(r"table (\S+ \S+)", text)) == {"inet kvmstudio"}

    member = Peer(4242, 1000, 1000, (10, LIBVIRT_GID))
    listing = server.handle(
        b'{"op": "list_port_forwards", "params": {}}', member, config, authorizer=lambda a, p: False
    )
    assert listing["ok"]
    assert listing["result"]["networks"]["kvmnet8"][0]["host_port"] == 8080

    # An empty list forgets the network.
    assert call(config, {"network": "kvmnet8", "rules": []})["ok"]
    assert "dnat" not in port_forward.ruleset_file(config).read_text()


@pytest.mark.parametrize(
    "bad",
    [
        rule(proto="icmp"),
        rule(proto="tcp; flush ruleset"),
        rule(host_port=0),
        rule(host_port=65536),
        rule(host_port=True),
        rule(host_port="80"),
        rule(vm_port=-1),
        rule(host_address="localhost"),
        rule(host_address="::1"),
        rule(host_address="1.2.3.4 tcp dport 1 accept"),
        rule(description="a\nflush ruleset"),
        rule(description="x" * 201),
        {**rule(), "extra": 1},
        {k: v for k, v in rule().items() if k != "vm_port"},
    ],
)
def test_bad_rules_are_refused_before_polkit(config: HelperConfig, bad: dict[str, Any]) -> None:
    runner = Recorder()
    answer = call(config, {"network": "kvmnet8", "rules": [bad]}, runner)
    assert not answer["ok"]
    assert answer["asked"] == []
    assert runner.calls == []


@pytest.mark.parametrize(
    "params",
    [
        {"network": "../etc", "rules": []},
        {"network": "kvmnet8; nft flush", "rules": []},
        {"network": "kvmnet8", "rules": "all"},
        {"network": "kvmnet8", "rules": [rule()] * 257},
        {"network": "kvmnet8"},
        {"network": "kvmnet8", "rules": [], "subnet": "0.0.0.0/0"},
    ],
)
def test_bad_requests(config: HelperConfig, params: dict[str, Any]) -> None:
    answer = call(config, params)
    assert not answer["ok"]
    assert answer["asked"] == []


@pytest.mark.parametrize(
    "params",
    [
        {"network": "other", "rules": [rule()]},
        {"network": "kvmnet8", "rules": [rule(vm_ip="10.0.0.5")]},  # outside its subnet
        {"network": "kvmnet8", "rules": [rule(vm_ip="192.168.108.255")]},
        {"network": "kvmnet8", "rules": [rule(vm_ip="192.168.108.0")]},
    ],
)
def test_refused_against_libvirt_once_authorized(
    config: HelperConfig, params: dict[str, Any]
) -> None:
    runner = Recorder()
    answer = call(config, params, runner)
    assert not answer["ok"]
    # libvirt is only asked about the network for an authorized caller.
    assert answer["asked"] == ["org.kvmstudio.helper.port-forward"]
    assert runner.calls == []


def test_refused_by_polkit_changes_nothing(config: HelperConfig) -> None:
    runner = Recorder()
    answer = call(config, {"network": "kvmnet8", "rules": [rule()]}, runner, allowed=False)
    assert answer["error"] == "not_authorized"
    assert runner.calls == []
    assert not port_forward.state_file(config).exists()


def test_hook_and_removal(config: HelperConfig) -> None:
    call(config, {"network": "kvmnet8", "rules": [rule()]})
    runner = Recorder()
    port_forward.apply(config, runner)
    assert runner.calls[0][:2] == ["nft", "-f"]
    port_forward.clear(config, runner)
    assert runner.calls[-1] == ["nft", "delete", "table", "inet", "kvmstudio"]
    assert not port_forward.state_file(config).exists()


def test_a_tampered_state_file_is_checked_again(config: HelperConfig) -> None:
    path = port_forward.state_file(config)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {"x": {"subnet": "10.0.0.0/8", "bridge": "kvmnet8", "rules": [rule(proto="all")]}}
        )
    )
    assert "dnat" not in port_forward.ruleset(port_forward.load_state(config))


@pytest.mark.parametrize(
    ("peer", "ok"),
    [
        (Peer(4242, 1001, 1001), False),  # any local account
        (Peer(4242, 1001, 1001, (10, 100)), False),
        (Peer(4242, 1000, 1000, (LIBVIRT_GID,)), True),
        (Peer(4242, 1000, LIBVIRT_GID), True),
        (Peer(4242, 0, 0), True),
    ],
)
def test_only_the_libvirt_group_reads_the_rules(config: HelperConfig, peer: Peer, ok: bool) -> None:
    raw = b'{"op": "list_port_forwards", "params": {}}'
    answer = server.handle(raw, peer, config, authorizer=lambda a, p: False)
    assert answer["ok"] is ok
    if not ok:
        assert answer["error"] == "not_authorized"
