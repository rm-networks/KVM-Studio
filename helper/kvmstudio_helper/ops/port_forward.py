"""NAT port forwarding: host address and port to a VM address and port.

The administrator writes the rules; the helper only checks what a root
operation must: protocol tcp or udp, ports between 1 and 65535, a valid host
address (0.0.0.0 included), and a VM address inside the subnet of the libvirt
network, which the helper reads from libvirt itself (qemu:///system), never
from the request.

Everything lives in KVM Studio's own nftables table, `inet kvmstudio`, written
again as a whole from the state file at each change and when libvirt starts a
network (hook): no other table, firewalld included, is ever touched.

Connections from the host itself go through the output chain. For a loopback
host address the network's bridge gets route_localnet, without which the
kernel drops 127.0.0.1 traffic leaving through it; a prerouting rule drops
anything a VM sends to 127.0.0.0/8 through that bridge.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import os
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config import HelperConfig
from ..errors import HelperError
from ..polkit import Peer
from . import Runner, Task, expect_keys
from .clone_state import virsh

ACTION = "org.kvmstudio.helper.port-forward"
TABLE = "kvmstudio"
MAX_RULES = 256
MAX_DESCRIPTION = 200
NETWORK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,49}$")
BRIDGE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")
RULE_KEYS = {"proto", "host_address", "host_port", "vm_ip", "vm_port", "description"}
SYSCTL = Path("/proc/sys/net/ipv4/conf")


@dataclass(frozen=True, slots=True)
class Rule:
    proto: str
    host_address: str
    host_port: int
    vm_ip: str
    vm_port: int
    description: str


def state_file(config: HelperConfig) -> Path:
    return config.state.parent / "port-forwards.json"


def ruleset_file(config: HelperConfig) -> Path:
    return config.state.parent / "port-forwards.nft"


def _port(value: object, what: str) -> int:
    # bool is an int in Python: refused explicitly.
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 65535:
        raise HelperError("invalid_params", f"{what} must be a port between 1 and 65535")
    return value


def _address(value: object, what: str) -> ipaddress.IPv4Address:
    if not isinstance(value, str):
        raise HelperError("invalid_params", f"{what} must be an IPv4 address")
    try:
        return ipaddress.IPv4Address(value)
    except ValueError:
        raise HelperError("invalid_params", f"{what} is not a valid IPv4 address") from None


def parse_rule(raw: object, subnet: ipaddress.IPv4Network) -> Rule:
    if not isinstance(raw, dict):
        raise HelperError("invalid_params", "each rule must be an object")
    expect_keys(raw, RULE_KEYS)
    proto = raw["proto"]
    if proto not in ("tcp", "udp"):
        raise HelperError("invalid_params", "proto must be tcp or udp")
    host = _address(raw["host_address"], "host_address")
    vm = _address(raw["vm_ip"], "vm_ip")
    if vm not in subnet or vm in (subnet.network_address, subnet.broadcast_address):
        raise HelperError("invalid_params", f"vm_ip {vm} is not a host address of {subnet}")
    description = raw["description"]
    if not isinstance(description, str) or len(description) > MAX_DESCRIPTION:
        raise HelperError("invalid_params", "description must be a short text")
    if any(ord(c) < 32 or ord(c) == 127 for c in description):
        raise HelperError("invalid_params", "description must not hold control characters")
    return Rule(
        str(proto),
        str(host),
        _port(raw["host_port"], "host_port"),
        str(vm),
        _port(raw["vm_port"], "vm_port"),
        description,
    )


def network_of(name: str) -> tuple[ipaddress.IPv4Network, str]:
    """Subnet and bridge of a libvirt network, read from libvirt."""
    # libvirt's own output; expat expands no external entity.
    root = ET.fromstring(virsh(["net-dumpxml", name]))  # noqa: S314
    if root.findtext("name") != name:
        raise HelperError("not_found", f"no network {name}")
    bridge = root.find("bridge")
    bridge_name = bridge.get("name", "") if bridge is not None else ""
    if not BRIDGE_RE.match(bridge_name):
        raise HelperError("invalid_params", f"network {name} has no usable bridge")
    for ip in root.findall("ip"):
        if ip.get("family", "ipv4") != "ipv4" or not ip.get("address"):
            continue
        mask = ip.get("prefix") or ip.get("netmask") or "24"
        try:
            return ipaddress.IPv4Interface(f"{ip.get('address')}/{mask}").network, bridge_name
        except ValueError:
            break
    raise HelperError("invalid_params", f"network {name} has no IPv4 subnet")


# State


def load_state(config: HelperConfig) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(state_file(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(config: HelperConfig, state: dict[str, dict[str, Any]]) -> None:
    path = state_file(config)
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(state, out, indent=1)
    os.replace(tmp, path)


def _stored_rules(entry: dict[str, Any]) -> list[Rule]:
    """Rules read back from the state file, checked again (root-owned, but cheap)."""
    rules = []
    try:
        subnet = ipaddress.IPv4Network(entry["subnet"])
        for raw in entry.get("rules", []):
            rules.append(parse_rule(raw, subnet))
    except (KeyError, ValueError, TypeError, HelperError):
        return []
    return rules


# nftables


def _match(rule: Rule) -> str:
    return f"{rule.proto} dport {rule.host_port}"


def _target(rule: Rule) -> str:
    return f"dnat ip to {rule.vm_ip}:{rule.vm_port}"


def ruleset(state: dict[str, dict[str, Any]]) -> str:
    """The whole table, written again each time (nft -f is atomic)."""
    prerouting: list[str] = []
    output: list[str] = []
    postrouting: list[str] = []
    guard: list[str] = []
    for entry in state.values():
        bridge = entry.get("bridge", "")
        if not BRIDGE_RE.match(str(bridge)):
            continue
        local = False
        for rule in _stored_rules(entry):
            host = ipaddress.IPv4Address(rule.host_address)
            if host.is_unspecified:
                # Any address of the host, from the host and from outside.
                output.append(f"fib daddr type local {_match(rule)} {_target(rule)}")
                prerouting.append(
                    f'iifname != "{bridge}" fib daddr type local {_match(rule)} {_target(rule)}'
                )
                local = True
            else:
                output.append(f"ip daddr {host} {_match(rule)} {_target(rule)}")
                if host.is_loopback:
                    local = True
                else:
                    prerouting.append(f"ip daddr {host} {_match(rule)} {_target(rule)}")
            # The VM answers the host, not 127.0.0.1.
            postrouting.append(
                f"ip saddr 127.0.0.0/8 ip daddr {rule.vm_ip} {rule.proto} dport {rule.vm_port}"
                " masquerade"
            )
        if local:
            guard.append(f'iifname "{bridge}" ip daddr 127.0.0.0/8 drop')
            guard.append(f'iifname "{bridge}" ip saddr 127.0.0.0/8 drop')

    def chain(name: str, hook: str, priority: str, kind: str, lines: list[str]) -> str:
        body = "".join(f"\t\t{line}\n" for line in lines)
        return (
            f"\tchain {name} {{\n\t\ttype {kind} hook {hook} priority {priority}; policy accept;\n"
            f"{body}\t}}\n"
        )

    return (
        f"table inet {TABLE}\n"
        f"delete table inet {TABLE}\n"
        f"table inet {TABLE} {{\n"
        + chain("guard", "prerouting", "raw", "filter", guard)
        + chain("prerouting", "prerouting", "dstnat", "nat", prerouting)
        + chain("output", "output", "-100", "nat", output)
        + chain("postrouting", "postrouting", "srcnat", "nat", postrouting)
        + "}\n"
    )


def _route_localnet(state: dict[str, dict[str, Any]]) -> None:
    """127.0.0.1 traffic may leave through the bridges of loopback rules."""
    for entry in state.values():
        bridge = str(entry.get("bridge", ""))
        if not BRIDGE_RE.match(bridge):
            continue
        wanted = any(
            ipaddress.IPv4Address(r.host_address).is_loopback
            or ipaddress.IPv4Address(r.host_address).is_unspecified
            for r in _stored_rules(entry)
        )
        knob = SYSCTL / bridge / "route_localnet"
        if wanted and knob.parent.is_dir():
            knob.write_text("1\n")


def apply(config: HelperConfig, runner: Runner) -> None:
    state = load_state(config)
    path = ruleset_file(config)
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(ruleset(state))
    runner(["nft", "-f", str(path)], ())
    _route_localnet(state)


def clear(config: HelperConfig, runner: Runner) -> None:
    """Package removal: the table goes, and the rules with it."""
    if not state_file(config).exists() and not ruleset_file(config).exists():
        return  # never used: no table was created
    with contextlib.suppress(HelperError):
        runner(["nft", "delete", "table", "inet", TABLE], ())
    state_file(config).unlink(missing_ok=True)
    ruleset_file(config).unlink(missing_ok=True)


# Operations


def prepare_set(params: Mapping[str, object], config: HelperConfig, peer: Peer) -> Task:
    expect_keys(params, {"network", "rules"})
    name, raw_rules = params["network"], params["rules"]
    if not isinstance(name, str) or not NETWORK_RE.match(name):
        raise HelperError("invalid_params", "network must be a libvirt network name")
    if not isinstance(raw_rules, list) or len(raw_rules) > MAX_RULES:
        raise HelperError("invalid_params", f"rules must be a list of at most {MAX_RULES}")
    if raw_rules:
        subnet, bridge = network_of(name)
        rules = [parse_rule(r, subnet) for r in raw_rules]
    else:
        subnet, bridge, rules = None, "", []

    def run(runner: Runner) -> dict[str, Any]:
        state = load_state(config)
        if rules and subnet is not None:
            state[name] = {
                "subnet": str(subnet),
                "bridge": bridge,
                "rules": [asdict(r) for r in rules],
            }
        else:
            state.pop(name, None)
        _save_state(config, state)
        apply(config, runner)
        return {"rules": len(rules)}

    return run


def prepare_list(params: Mapping[str, object], config: HelperConfig, peer: Peer) -> Task:
    expect_keys(params, set())

    def run(_runner: Runner) -> dict[str, Any]:
        state = load_state(config)
        return {
            "networks": {
                name: [asdict(r) for r in _stored_rules(entry)] for name, entry in state.items()
            }
        }

    return run
