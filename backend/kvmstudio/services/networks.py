"""Virtual networks: every libvirt network is listed and can be edited.

KVM Studio creates its own networks with a bridge named kvmnetN, which the
packaged NetworkManager rule hides from the desktop. Host-only networks have
no <forward>; NAT networks use <forward mode='nat'/>. libvirt's DHCP server
needs an address on the bridge, so DHCP implies the host adapter.
"""

from __future__ import annotations

import fcntl
import ipaddress
import re
import socket
import struct
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

import libvirt
from lxml import etree

from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection

Kind = Literal["host_only", "nat", "other"]
EditableKind = Literal["host_only", "nat"]
# What DHCP announces as gateway. libvirt announces the host on a NAT network
# and nothing on a host-only one; there the host itself or another address
# (a firewall VM routing the segment) can be announced instead.
GatewayMode = Literal["host", "custom", "none"]


def default_gateway(kind: str) -> GatewayMode:
    return "host" if kind == "nat" else "none"


DNSMASQ_NS = "http://libvirt.org/schemas/network/dnsmasq/1.0"
# Clean shutdown of the VMs of a network about to restart.
SHUTDOWN_WAIT_S = 60

BRIDGE_PREFIX = "kvmnet"
RESERVED_NUMBERS = {0}  # kvmnet0 is kept for bridged networking (V2)
MAX_NUMBER = 99
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,49}$")

# Defaults created at first run, like VMnet1 and VMnet8.
DEFAULTS: dict[str, tuple[EditableKind, int]] = {"kvmnet1": ("host_only", 1), "kvmnet8": ("nat", 8)}
DEFAULT_SUBNET_STARTS = {"kvmnet1": 101, "kvmnet8": 108}

_PARSER = etree.XMLParser(resolve_entities=False, remove_blank_text=True)


@dataclass(frozen=True, slots=True)
class DhcpRange:
    start: str
    end: str


@dataclass(frozen=True, slots=True)
class NetworkSpec:
    """What the editor lets the user choose for host-only and NAT networks."""

    kind: EditableKind
    subnet: ipaddress.IPv4Network | None
    host_adapter: bool
    dhcp: DhcpRange | None
    # The host's address on the network (first one when None). With libvirt it
    # is also the gateway and DNS server of a NAT network.
    host_ip: str | None = None
    # None: libvirt's default for the kind (see default_gateway).
    gateway: GatewayMode | None = None
    gateway_ip: str | None = None

    @property
    def gateway_mode(self) -> GatewayMode:
        return self.gateway or default_gateway(self.kind)

    def host_address(self) -> ipaddress.IPv4Address | None:
        if self.subnet is None:
            return None
        if self.host_ip:
            return ipaddress.IPv4Address(self.host_ip)
        return next(self.subnet.hosts())


@dataclass(frozen=True, slots=True)
class NetworkInfo:
    name: str
    uuid: str
    kind: Kind
    forward_mode: str | None
    bridge: str | None
    active: bool
    autostart: bool
    persistent: bool
    subnet: str | None
    host_ip: str | None
    dhcp: DhcpRange | None
    used_by: tuple[str, ...] = field(default=())
    gateway: GatewayMode = "host"
    gateway_ip: str | None = None

    @property
    def managed(self) -> bool:
        return bool(self.bridge and self.bridge.startswith(BRIDGE_PREFIX))


# XML


def _ipv4_element(root: etree._Element) -> etree._Element | None:
    for ip in root.iterfind("ip"):
        if ip.get("family", "ipv4") == "ipv4":
            return ip
    return None


def _interface(ip: etree._Element) -> ipaddress.IPv4Interface | None:
    address = ip.get("address")
    if not address:
        return None
    try:
        if prefix := ip.get("prefix"):
            return ipaddress.IPv4Interface(f"{address}/{prefix}")
        return ipaddress.IPv4Interface(f"{address}/{ip.get('netmask', '255.255.255.0')}")
    except ValueError:
        return None


def parse(
    xml: str,
) -> tuple[str, Kind, str | None, str | None, ipaddress.IPv4Interface | None, DhcpRange | None]:
    """(uuid, kind, forward mode, bridge, host interface, dhcp) from network XML."""
    root = etree.fromstring(xml.encode(), parser=_PARSER)
    forward = root.find("forward")
    mode = forward.get("mode", "nat") if forward is not None else None
    kind: Kind = "host_only" if mode is None else "nat" if mode == "nat" else "other"
    bridge = root.find("bridge")
    ip = _ipv4_element(root)
    iface = _interface(ip) if ip is not None else None
    dhcp = None
    if ip is not None and (rng := ip.find("dhcp/range")) is not None:
        dhcp = DhcpRange(rng.get("start", ""), rng.get("end", ""))
    return (
        root.findtext("uuid", ""),
        kind,
        mode,
        bridge.get("name") if bridge is not None else None,
        iface,
        dhcp,
    )


def _router_option(value: str | None) -> tuple[GatewayMode, str | None] | None:
    """Our dnsmasq option for the announced gateway, read back."""
    if not value:
        return None
    for prefix in ("dhcp-option=option:router", "dhcp-option=3"):
        if value == prefix:
            return "none", None
        if value.startswith(prefix + ","):
            return "custom", value.split(",", 1)[1]
    return None


def parse_gateway(xml: str) -> tuple[GatewayMode, str | None]:
    """Gateway announced by DHCP (from the dnsmasq options)."""
    root = etree.fromstring(xml.encode(), parser=_PARSER)
    kind = "nat" if root.find("forward") is not None else "host_only"
    gateway: tuple[GatewayMode, str | None] = (default_gateway(kind), None)
    for option in root.iterfind(f"{{{DNSMASQ_NS}}}options/{{{DNSMASQ_NS}}}option"):
        if found := _router_option(option.get("value")):
            gateway = found
    ip = _ipv4_element(root)
    if gateway[0] == "custom" and ip is not None and ip.get("address") == gateway[1]:
        gateway = ("host", None)
    return gateway


def _set_router_option(root: etree._Element, spec: NetworkSpec) -> None:
    """Keep other dnsmasq options; ours says which gateway DHCP announces."""
    options = root.find(f"{{{DNSMASQ_NS}}}options")
    if options is not None:
        for option in options.findall(f"{{{DNSMASQ_NS}}}option"):
            if _router_option(option.get("value")):
                options.remove(option)
    wanted = None
    if spec.kind == "host_only" and spec.dhcp is not None:
        # "none" is libvirt's own default there (it writes dhcp-option=3).
        if spec.gateway_mode == "host":
            wanted = f"dhcp-option=option:router,{spec.host_address()}"
        elif spec.gateway_mode == "custom":
            wanted = f"dhcp-option=option:router,{spec.gateway_ip}"
    if wanted:
        if options is None:
            options = etree.SubElement(
                root, f"{{{DNSMASQ_NS}}}options", nsmap={"dnsmasq": DNSMASQ_NS}
            )
        etree.SubElement(options, f"{{{DNSMASQ_NS}}}option", value=wanted)
    if options is not None and len(options) == 0:
        root.remove(options)


def apply_spec(xml: str | None, name: str, bridge: str, spec: NetworkSpec) -> str:
    """Network XML for spec, keeping whatever else an existing definition holds."""
    if xml is None:
        root = etree.Element("network")
        etree.SubElement(root, "name").text = name
        etree.SubElement(root, "bridge", name=bridge, stp="on", delay="0")
    else:
        root = etree.fromstring(xml.encode(), parser=_PARSER)
        root.find("name").text = name  # type: ignore[union-attr]
    for old in root.findall("forward"):
        root.remove(old)
    # Static hosts set with virsh are the administrator's: they stay.
    kept_hosts: list[etree._Element] = []
    for old in [ip for ip in root.findall("ip") if ip.get("family", "ipv4") == "ipv4"]:
        kept_hosts += old.findall("dhcp/host")
        root.remove(old)
    if spec.kind == "nat":
        bridge_el = root.find("bridge")
        position = list(root).index(bridge_el) if bridge_el is not None else len(root)
        root.insert(position, etree.Element("forward", mode="nat"))
    if spec.host_adapter and spec.subnet is not None:
        host = spec.host_address()
        ip = etree.Element("ip", address=str(host), netmask=str(spec.subnet.netmask))
        # Before the dnsmasq options, which libvirt wants last.
        options = root.find(f"{{{DNSMASQ_NS}}}options")
        if options is not None:
            options.addprevious(ip)
        else:
            root.append(ip)
        if spec.dhcp is not None:
            dhcp = etree.SubElement(ip, "dhcp")
            etree.SubElement(dhcp, "range", start=spec.dhcp.start, end=spec.dhcp.end)
            for host_el in kept_hosts:
                address = host_el.get("ip")
                if address and ipaddress.IPv4Address(address) in spec.subnet:
                    dhcp.append(host_el)
    _set_router_option(root, spec)
    return etree.tostring(root, pretty_print=True).decode()


# Validation


def default_dhcp(subnet: ipaddress.IPv4Network) -> DhcpRange:
    """Upper half of the subnet, as VMware does (.128 to .254 on a /24)."""
    hosts = list(subnet.hosts())
    half = hosts[len(hosts) // 2 :]
    return DhcpRange(str(half[0]), str(half[-1]))


def fit_range(spec: NetworkSpec) -> NetworkSpec:
    """Move the DHCP range off the host address when it falls inside it."""
    if spec.dhcp is None or spec.subnet is None or not spec.host_adapter:
        return spec
    try:
        start = ipaddress.IPv4Address(spec.dhcp.start)
        end = ipaddress.IPv4Address(spec.dhcp.end)
        host = spec.host_address()
    except ValueError:
        return spec
    if host is None or not start <= host <= end:
        return spec
    # Keep the larger side of the range.
    below, above = int(host) - int(start), int(end) - int(host)
    if below == 0 and above == 0:
        return spec
    if above >= below:
        dhcp = DhcpRange(str(host + 1), str(end))
    else:
        dhcp = DhcpRange(str(start), str(host - 1))
    return NetworkSpec(
        spec.kind, spec.subnet, spec.host_adapter, dhcp,
        spec.host_ip, spec.gateway, spec.gateway_ip,
    )  # fmt: skip


def check_spec(spec: NetworkSpec) -> None:
    def bad(code: str, detail: str) -> ApiException:
        return ApiException(422, f"net.{code}", detail)

    def usable(value: str, what: str) -> ipaddress.IPv4Address:
        try:
            address = ipaddress.IPv4Address(value)
        except ValueError as exc:
            raise bad("bad_address", f"{what}: {exc}") from exc
        assert spec.subnet is not None  # noqa: S101 (checked by the callers)
        if address not in spec.subnet:
            raise bad("address_outside", f"{what} {address} is not in {spec.subnet}")
        if address in (spec.subnet.network_address, spec.subnet.broadcast_address):
            raise bad("address_reserved", f"{what} {address} is the network or broadcast address")
        return address

    if spec.kind == "nat" and not spec.host_adapter:
        raise bad("nat_needs_adapter", "A NAT network always has a host address")
    if spec.host_adapter or spec.dhcp is not None:
        if spec.subnet is None:
            raise bad("subnet_required", "A subnet is required")
        if not (8 <= spec.subnet.prefixlen <= 30):
            raise bad("bad_prefix", "Use a prefix between /8 and /30")
        if not spec.subnet.is_private:
            raise bad("not_private", "Use a private address range")
    host = None
    if spec.host_adapter and spec.subnet is not None and spec.host_ip:
        host = usable(spec.host_ip, "Host address")
    elif spec.host_adapter and spec.subnet is not None:
        host = next(spec.subnet.hosts())
    if spec.dhcp is not None:
        if not spec.host_adapter:
            raise bad("dhcp_needs_adapter", "libvirt's DHCP needs the host adapter")
        if spec.subnet is None:
            raise bad("subnet_required", "A subnet is required")
        try:
            start = ipaddress.IPv4Address(spec.dhcp.start)
            end = ipaddress.IPv4Address(spec.dhcp.end)
        except ValueError as exc:
            raise bad("bad_dhcp", str(exc)) from exc
        hosts = set(spec.subnet.hosts())
        if start not in hosts or end not in hosts or start > end:
            raise bad("bad_dhcp", "The DHCP range must lie inside the subnet")
        if host is not None and start <= host <= end:
            raise bad("bad_dhcp", f"The DHCP range must not include the host address {host}")
        if spec.kind == "nat" and spec.gateway_mode != "host":
            raise bad("gateway_nat", "A NAT network's gateway is the host address")
        if spec.gateway_mode == "custom":
            if not spec.gateway_ip:
                raise bad("gateway_required", "Give the gateway address")
            usable(spec.gateway_ip, "Gateway")
    elif spec.gateway not in (None, default_gateway(spec.kind)):
        raise bad("needs_dhcp", "The announced gateway needs DHCP")


# Host side


def host_subnets() -> list[tuple[str, ipaddress.IPv4Network]]:
    """IPv4 subnet of each host interface (primary address), read with ioctls."""
    siocgifaddr, siocgifnetmask = 0x8915, 0x891B
    result = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for _index, name in socket.if_nameindex():
            request = struct.pack("256s", name[:15].encode())
            try:
                addr = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), siocgifaddr, request)[20:24])
                mask = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), siocgifnetmask, request)[20:24])
            except OSError:
                continue  # no IPv4 address
            network = ipaddress.IPv4Interface(f"{addr}/{mask}").network
            if not network.is_loopback:
                result.append((name, network))
    return result


def listening_ports(proc: str = "/proc/net") -> dict[str, list[int]]:
    """TCP ports in LISTEN state and bound UDP ports on the host, IPv4 and IPv6."""
    found: dict[str, set[int]] = {"tcp": set(), "udp": set()}
    for proto in ("tcp", "udp"):
        for suffix in ("", "6"):
            try:
                with open(f"{proc}/{proto}{suffix}", encoding="ascii") as table:
                    next(table, None)
                    for line in table:
                        fields = line.split()
                        if len(fields) < 4:
                            continue
                        if proto == "tcp" and fields[3] != "0A":  # LISTEN
                            continue
                        found[proto].add(int(fields[1].rsplit(":", 1)[1], 16))
            except OSError:
                continue
    return {k: sorted(v) for k, v in found.items()}


def interface_names() -> set[str]:
    return {name for _i, name in socket.if_nameindex()}


# libvirt side


def _config_xml(net: libvirt.virNetwork) -> str:
    """Persistent definition, falling back to the live XML where unsupported."""
    try:
        return net.XMLDesc(libvirt.VIR_NETWORK_XML_INACTIVE)
    except libvirt.libvirtError:
        return net.XMLDesc(0)


def _domain_usage(c: libvirt.virConnect) -> dict[str, set[str]]:
    """Network name -> names of the VMs whose config or live XML uses it."""
    usage: dict[str, set[str]] = {}
    for dom in c.listAllDomains():
        xmls = {dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)}
        if dom.isActive():
            xmls.add(dom.XMLDesc(0))
        for xml in xmls:
            root = etree.fromstring(xml.encode(), parser=_PARSER)
            for src in root.iterfind("devices/interface[@type='network']/source"):
                if net := src.get("network"):
                    usage.setdefault(net, set()).add(dom.name())
    return usage


def _running_users(c: libvirt.virConnect, network: str) -> list[str]:
    names = []
    for dom in c.listAllDomains(libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE):
        root = etree.fromstring(dom.XMLDesc(0).encode(), parser=_PARSER)
        sources = root.iterfind("devices/interface[@type='network']/source")
        if any(s.get("network") == network for s in sources):
            names.append(dom.name())
    return sorted(names)


def list_networks(conn: LibvirtConnection) -> list[NetworkInfo]:
    def op(c: libvirt.virConnect) -> list[NetworkInfo]:
        usage = _domain_usage(c)
        result = []
        for net in c.listAllNetworks():
            xml = net.XMLDesc(0)
            uuid, kind, mode, bridge, iface, dhcp = parse(xml)
            gateway, gateway_ip = parse_gateway(xml)
            result.append(
                NetworkInfo(
                    name=net.name(),
                    uuid=uuid,
                    kind=kind,
                    forward_mode=mode,
                    bridge=bridge,
                    active=bool(net.isActive()),
                    autostart=bool(net.autostart()),
                    persistent=bool(net.isPersistent()),
                    subnet=str(iface.network) if iface else None,
                    host_ip=str(iface.ip) if iface else None,
                    dhcp=dhcp,
                    used_by=tuple(sorted(usage.get(net.name(), ()))),
                    gateway=gateway,
                    gateway_ip=gateway_ip,
                )
            )
        return sorted(result, key=lambda n: n.name.casefold())

    return conn.run(op)


def _check_overlap(
    conn: LibvirtConnection,
    subnet: ipaddress.IPv4Network | None,
    ignore: str | None,
    host: Iterable[tuple[str, ipaddress.IPv4Network]],
) -> None:
    if subnet is None:
        return
    networks = list_networks(conn)
    bridges = {n.bridge for n in networks}
    for net in networks:
        if net.name != ignore and net.subnet and subnet.overlaps(ipaddress.IPv4Network(net.subnet)):
            raise ApiException(409, "net.overlap", f"{subnet} overlaps {net.name} ({net.subnet})")
    for iface, network in host:
        if iface not in bridges and subnet.overlaps(network):
            raise ApiException(409, "net.overlap", f"{subnet} overlaps {iface} ({network})")


def free_subnet(
    conn: LibvirtConnection,
    host: Iterable[tuple[str, ipaddress.IPv4Network]],
    start: int = 101,
) -> ipaddress.IPv4Network:
    """First 192.168.X.0/24 from X=start that overlaps nothing."""
    host = list(host)
    taken = [ipaddress.IPv4Network(n.subnet) for n in list_networks(conn) if n.subnet]
    taken += [network for _name, network in host]
    for third in [*range(start, 255), *range(1, start)]:
        candidate = ipaddress.IPv4Network(f"192.168.{third}.0/24")
        if not any(candidate.overlaps(t) for t in taken):
            return candidate
    raise ApiException(409, "net.no_free_subnet", "No free 192.168.x.0/24 subnet")


def free_number(conn: LibvirtConnection) -> int:
    used = {n.bridge for n in list_networks(conn)} | interface_names()
    for number in range(1, MAX_NUMBER + 1):
        if number not in RESERVED_NUMBERS and f"{BRIDGE_PREFIX}{number}" not in used:
            return number
    raise ApiException(409, "net.no_free_number", "Every kvmnet number is taken")


def create_network(
    conn: LibvirtConnection,
    name: str,
    number: int,
    spec: NetworkSpec,
    *,
    autostart: bool = True,
    host: Iterable[tuple[str, ipaddress.IPv4Network]] | None = None,
) -> str:
    if not NAME_RE.match(name):
        raise ApiException(422, "net.bad_name", f"invalid network name: {name}")
    if number in RESERVED_NUMBERS or not (0 < number <= MAX_NUMBER):
        raise ApiException(422, "net.bad_number", f"kvmnet{number} cannot be used")
    spec = fit_range(spec)
    check_spec(spec)
    bridge = f"{BRIDGE_PREFIX}{number}"
    networks = list_networks(conn)
    if any(n.name == name for n in networks):
        raise ApiException(409, "net.exists", f"{name} already exists")
    if any(n.bridge == bridge for n in networks) or bridge in interface_names():
        raise ApiException(409, "net.bridge_taken", f"{bridge} is already used")
    _check_overlap(conn, spec.subnet, None, host_subnets() if host is None else host)

    xml = apply_spec(None, name, bridge, spec)

    def op(c: libvirt.virConnect) -> None:
        net = c.networkDefineXML(xml)
        net.setAutostart(int(autostart))
        net.create()

    conn.run(op)
    return name


@dataclass(frozen=True, slots=True)
class UpdatePlan:
    # The network must restart: libvirt 12 does not plug the cards of running
    # VMs back into the bridge afterwards, so those VMs are stopped first.
    restart: bool
    running: tuple[str, ...]


def _needs_restart(xml: str, spec: NetworkSpec) -> bool:
    """Only the DHCP range changes on a running network."""
    _uuid, kind, _mode, _bridge, iface, dhcp = parse(xml)
    gateway, gateway_ip = parse_gateway(xml)
    host = spec.host_address() if spec.host_adapter else None
    same_address = (iface is None and host is None) or (
        iface is not None and host is not None and iface.network == spec.subnet and iface.ip == host
    )
    mode = spec.gateway_mode
    wanted_gateway = (mode, spec.gateway_ip if mode == "custom" else None)
    return not (
        kind == spec.kind
        and same_address
        and (dhcp is None) == (spec.dhcp is None)
        and (gateway, gateway_ip) == wanted_gateway
    )


def _prepare(
    conn: LibvirtConnection,
    name: str,
    spec: NetworkSpec,
    host: Iterable[tuple[str, ipaddress.IPv4Network]] | None,
) -> tuple[NetworkSpec, str, str, bool, bool]:
    """(fitted spec, current xml, new xml, active, restart needed), all checked."""
    spec = fit_range(spec)
    check_spec(spec)

    def current(c: libvirt.virConnect) -> tuple[str, bool]:
        net = c.networkLookupByName(name)
        return _config_xml(net), bool(net.isActive())

    xml, active = conn.run(current)
    _uuid, kind, _mode, bridge, _iface, _dhcp = parse(xml)
    if kind == "other":
        raise ApiException(409, "net.not_editable", f"{name} is not a host-only or NAT network")
    _check_overlap(conn, spec.subnet, name, host_subnets() if host is None else host)
    return spec, xml, apply_spec(xml, name, bridge or name, spec), active, _needs_restart(xml, spec)


def plan_update(
    conn: LibvirtConnection,
    name: str,
    spec: NetworkSpec,
    *,
    host: Iterable[tuple[str, ipaddress.IPv4Network]] | None = None,
) -> UpdatePlan:
    _spec, _xml, _new, active, restart = _prepare(conn, name, spec, host)
    running = conn.run(lambda c: _running_users(c, name)) if active and restart else []
    return UpdatePlan(restart=restart, running=tuple(running))


def _stop(conn: LibvirtConnection, names: list[str], how: str) -> None:
    """Shut down (or power off) these VMs and wait for them; 409 if some still run."""

    def order(c: libvirt.virConnect) -> None:
        for vm in names:
            dom = c.lookupByName(vm)
            if not dom.isActive():
                continue
            if how == "poweroff":
                dom.destroy()
            else:
                dom.shutdownFlags(0)

    conn.run(order)
    for _ in range(SHUTDOWN_WAIT_S):
        still = conn.run(lambda c: [n for n in names if c.lookupByName(n).isActive()])
        if not still:
            return
        time.sleep(1)
    raise ApiException(
        409, "net.vms_still_running", "Still running after shutdown: " + ", ".join(still)
    )


def update_network(
    conn: LibvirtConnection,
    name: str,
    spec: NetworkSpec,
    *,
    host: Iterable[tuple[str, ipaddress.IPv4Network]] | None = None,
    stop_vms: Literal["shutdown", "poweroff"] | None = None,
) -> None:
    """Change a network. When it must restart while VMs use it, they are stopped
    first (only when asked: stop_vms), then started again."""
    spec, xml, new_xml, active, restart = _prepare(conn, name, spec, host)
    _uuid, _kind, _mode, _bridge, _iface, dhcp = parse(xml)
    running = conn.run(lambda c: _running_users(c, name)) if active and restart else []
    if running and stop_vms is None:
        raise ApiException(
            409, "net.in_use", "Power off the VMs using it first: " + ", ".join(running)
        )
    if running:
        _stop(conn, running, stop_vms or "shutdown")

    def op(c: libvirt.virConnect) -> None:
        c.networkDefineXML(new_xml)
        if not active:
            return
        net = c.networkLookupByName(name)
        if restart:
            net.destroy()
            net.create()
            return
        if spec.dhcp is not None and dhcp is not None and dhcp != spec.dhcp:
            old = etree.Element("range", start=dhcp.start, end=dhcp.end)
            section = etree.Element("range", start=spec.dhcp.start, end=spec.dhcp.end)
            net.update(
                libvirt.VIR_NETWORK_UPDATE_COMMAND_DELETE,
                libvirt.VIR_NETWORK_SECTION_IP_DHCP_RANGE,
                -1,
                etree.tostring(old).decode(),
                libvirt.VIR_NETWORK_UPDATE_AFFECT_LIVE,
            )
            net.update(
                libvirt.VIR_NETWORK_UPDATE_COMMAND_ADD_LAST,
                libvirt.VIR_NETWORK_SECTION_IP_DHCP_RANGE,
                -1,
                etree.tostring(section).decode(),
                libvirt.VIR_NETWORK_UPDATE_AFFECT_LIVE,
            )

    conn.run(op)

    def restart_vms(c: libvirt.virConnect) -> None:
        for vm in running:
            dom = c.lookupByName(vm)
            if not dom.isActive():
                dom.create()

    if running:
        conn.run(restart_vms)


def rename_network(conn: LibvirtConnection, name: str, new_name: str) -> None:
    if not NAME_RE.match(new_name):
        raise ApiException(422, "net.bad_name", f"invalid network name: {new_name}")

    def op(c: libvirt.virConnect) -> None:
        if new_name in {n.name() for n in c.listAllNetworks()}:
            raise ApiException(409, "net.exists", f"{new_name} already exists")
        if running := _running_users(c, name):
            raise ApiException(409, "net.in_use", "Running VMs use it: " + ", ".join(running))
        net = c.networkLookupByName(name)
        active, autostart = bool(net.isActive()), bool(net.autostart())
        root = etree.fromstring(_config_xml(net).encode(), parser=_PARSER)
        root.find("name").text = new_name  # type: ignore[union-attr]
        for uuid in root.findall("uuid"):
            root.remove(uuid)
        if active:
            net.destroy()
        net.undefine()
        renamed = c.networkDefineXML(etree.tostring(root).decode())
        renamed.setAutostart(int(autostart))
        if active:
            renamed.create()
        # VMs refer to networks by name: follow the rename in their config.
        for dom in c.listAllDomains(libvirt.VIR_CONNECT_LIST_DOMAINS_PERSISTENT):
            dom_root = etree.fromstring(
                dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE).encode(), parser=_PARSER
            )
            changed = False
            for src in dom_root.iterfind("devices/interface[@type='network']/source"):
                if src.get("network") == name:
                    src.set("network", new_name)
                    changed = True
            if changed:
                c.defineXML(etree.tostring(dom_root).decode())

    conn.run(op)


def delete_network(conn: LibvirtConnection, name: str) -> None:
    def op(c: libvirt.virConnect) -> None:
        if users := sorted(_domain_usage(c).get(name, ())):
            raise ApiException(409, "net.in_use", "Used by: " + ", ".join(users))
        net = c.networkLookupByName(name)
        if net.isActive():
            net.destroy()
        if net.isPersistent():
            net.undefine()

    conn.run(op)


def set_state(
    conn: LibvirtConnection, name: str, *, active: bool | None, autostart: bool | None
) -> None:
    def op(c: libvirt.virConnect) -> None:
        net = c.networkLookupByName(name)
        if autostart is not None:
            net.setAutostart(int(autostart))
        if active is True and not net.isActive():
            net.create()
        elif active is False and net.isActive():
            net.destroy()

    conn.run(op)


def restore_defaults(
    conn: LibvirtConnection, host: Iterable[tuple[str, ipaddress.IPv4Network]] | None = None
) -> list[str]:
    """Create kvmnet1 and kvmnet8 if missing, or reset their settings; returns names touched."""
    host = list(host_subnets() if host is None else host)
    touched = []
    for name, (kind, number) in DEFAULTS.items():
        existing = next((n for n in list_networks(conn) if n.name == name), None)
        if existing is not None and existing.subnet:
            subnet = ipaddress.IPv4Network(existing.subnet)
        else:
            subnet = free_subnet(conn, host, DEFAULT_SUBNET_STARTS[name])
        spec = NetworkSpec(kind, subnet, True, default_dhcp(subnet))
        if existing is None:
            create_network(conn, name, number, spec, host=host)
        elif existing.kind != "other":
            update_network(conn, name, spec, host=host)
        else:
            continue
        touched.append(name)
    return touched
