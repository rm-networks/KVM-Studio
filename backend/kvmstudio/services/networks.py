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
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

import libvirt
from lxml import etree

from ..errors import ApiException
from ..libvirt_conn import LibvirtConnection

Kind = Literal["host_only", "nat", "other"]
EditableKind = Literal["host_only", "nat"]

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
    for old in [ip for ip in root.findall("ip") if ip.get("family", "ipv4") == "ipv4"]:
        root.remove(old)
    if spec.kind == "nat":
        bridge_el = root.find("bridge")
        position = list(root).index(bridge_el) if bridge_el is not None else len(root)
        root.insert(position, etree.Element("forward", mode="nat"))
    if spec.host_adapter and spec.subnet is not None:
        gateway = next(spec.subnet.hosts())
        ip = etree.SubElement(root, "ip", address=str(gateway), netmask=str(spec.subnet.netmask))
        if spec.dhcp is not None:
            dhcp = etree.SubElement(ip, "dhcp")
            etree.SubElement(dhcp, "range", start=spec.dhcp.start, end=spec.dhcp.end)
    return etree.tostring(root, pretty_print=True).decode()


# Validation


def default_dhcp(subnet: ipaddress.IPv4Network) -> DhcpRange:
    """Upper half of the subnet, as VMware does (.128 to .254 on a /24)."""
    hosts = list(subnet.hosts())
    half = hosts[len(hosts) // 2 :]
    return DhcpRange(str(half[0]), str(half[-1]))


def check_spec(spec: NetworkSpec) -> None:
    def bad(code: str, detail: str) -> ApiException:
        return ApiException(422, f"net.{code}", detail)

    if spec.kind == "nat" and not spec.host_adapter:
        raise bad("nat_needs_adapter", "A NAT network always has a host address")
    if spec.host_adapter or spec.dhcp is not None:
        if spec.subnet is None:
            raise bad("subnet_required", "A subnet is required")
        if not (8 <= spec.subnet.prefixlen <= 30):
            raise bad("bad_prefix", "Use a prefix between /8 and /30")
        if not spec.subnet.is_private:
            raise bad("not_private", "Use a private address range")
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
        gateway = next(spec.subnet.hosts())
        usable = set(spec.subnet.hosts())
        if start not in usable or end not in usable or start > end:
            raise bad("bad_dhcp", "The DHCP range must lie inside the subnet")
        if start <= gateway <= end:
            raise bad("bad_dhcp", f"The DHCP range must not include the host address {gateway}")


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
            uuid, kind, mode, bridge, iface, dhcp = parse(net.XMLDesc(0))
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


def update_network(
    conn: LibvirtConnection,
    name: str,
    spec: NetworkSpec,
    *,
    host: Iterable[tuple[str, ipaddress.IPv4Network]] | None = None,
) -> None:
    check_spec(spec)

    def current(c: libvirt.virConnect) -> tuple[str, bool]:
        net = c.networkLookupByName(name)
        return _config_xml(net), bool(net.isActive())

    xml, active = conn.run(current)
    _uuid, kind, _mode, bridge, iface, dhcp = parse(xml)
    if kind == "other":
        raise ApiException(409, "net.not_editable", f"{name} is not a host-only or NAT network")
    _check_overlap(conn, spec.subnet, name, host_subnets() if host is None else host)
    new_xml = apply_spec(xml, name, bridge or name, spec)
    # Only the DHCP range moved: libvirt can change that on the running network.
    range_only = (
        kind == spec.kind
        and iface is not None
        and spec.host_adapter
        and iface.network == spec.subnet
        and dhcp is not None
        and spec.dhcp is not None
    )

    def op(c: libvirt.virConnect) -> None:
        if active and not range_only and (running := _running_users(c, name)):
            raise ApiException(
                409, "net.in_use", "Power off the VMs using it first: " + ", ".join(running)
            )
        c.networkDefineXML(new_xml)
        if not active:
            return
        net = c.networkLookupByName(name)
        if range_only and spec.dhcp is not None and dhcp != spec.dhcp:
            section = etree.Element("range", start=spec.dhcp.start, end=spec.dhcp.end)
            old = etree.Element("range", start=dhcp.start, end=dhcp.end)  # type: ignore[union-attr]
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
        elif not range_only:
            # Address and type changes only apply when the network restarts.
            net.destroy()
            net.create()

    conn.run(op)


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
