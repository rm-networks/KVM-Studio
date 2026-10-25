from __future__ import annotations

import ipaddress
import uuid as uuidlib
from collections.abc import Iterator
from typing import Any

import libvirt
import pytest
from fastapi.testclient import TestClient
from lxml import etree

from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.services import networks as net

from .helpers import AUTH

HOST_LAN = ipaddress.IPv4Network("192.168.1.0/24")


@pytest.fixture(autouse=True)
def fake_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tests must not depend on the machine's real interfaces."""
    monkeypatch.setattr(net, "host_subnets", lambda: [("enp3s0", HOST_LAN)])
    monkeypatch.setattr(net, "interface_names", lambda: {"lo", "enp3s0", "virbr0"})


@pytest.fixture(autouse=True)
def cleanup(conn: LibvirtConnection) -> Iterator[None]:
    yield

    def op(c: libvirt.virConnect) -> None:
        for dom in c.listAllDomains():
            if dom.name().startswith("net-test"):
                if dom.isActive():
                    dom.destroy()
                if dom.isPersistent():
                    dom.undefine()
        for network in c.listAllNetworks():
            if network.name() != "default":
                if network.isActive():
                    network.destroy()
                if network.isPersistent():
                    network.undefine()

    conn.run(op)


def networks(client: TestClient) -> dict[str, dict[str, Any]]:
    return {n["name"]: n for n in client.get("/api/networks", headers=AUTH).json()}


def network_xml(conn: LibvirtConnection, name: str) -> etree._Element:
    xml = conn.run(lambda c: c.networkLookupByName(name).XMLDesc(0))
    return etree.fromstring(xml.encode())


def host_only(subnet: str = "192.168.150.0/24", **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "host_only",
        "subnet": subnet,
        "host_adapter": True,
        "dhcp": {
            "start": subnet.rsplit(".", 1)[0] + ".128",
            "end": subnet.rsplit(".", 1)[0] + ".254",
        },
    }
    body.update(extra)
    return body


def add_vm(conn: LibvirtConnection, network: str, *, start: bool) -> libvirt.virDomain:
    xml = (
        f"<domain type='test'><name>net-test-{uuidlib.uuid4().hex[:6]}</name>"
        "<memory>65536</memory><os><type>hvm</type></os><devices>"
        f"<interface type='network'><source network='{network}'/></interface>"
        "</devices></domain>"
    )
    dom = conn.run(lambda c: c.defineXML(xml))
    if start:
        dom.create()
    return dom


def test_lists_every_libvirt_network(client: TestClient) -> None:
    default = networks(client)["default"]
    assert default["kind"] == "nat"
    assert default["subnet"] == "192.168.122.0/24"
    assert default["host_ip"] == "192.168.122.1"
    assert default["dhcp"] == {"start": "192.168.122.2", "end": "192.168.122.254"}
    assert default["managed"] is False


def test_create_host_only_network(client: TestClient, conn: LibvirtConnection) -> None:
    response = client.post("/api/networks", headers=AUTH, json={**host_only(), "number": 3})
    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "kvmnet3"
    assert created["bridge"] == "kvmnet3"
    assert created["kind"] == "host_only"
    assert created["active"] is True
    assert created["autostart"] is True
    root = network_xml(conn, "kvmnet3")
    assert root.find("forward") is None
    assert root.find("ip").get("address") == "192.168.150.1"  # type: ignore[union-attr]
    assert root.find("ip/dhcp/range").get("start") == "192.168.150.128"  # type: ignore[union-attr]


def test_lab_segment_has_no_address(client: TestClient, conn: LibvirtConnection) -> None:
    body = {"kind": "host_only", "host_adapter": False, "name": "LAN-1", "number": 4}
    assert client.post("/api/networks", headers=AUTH, json=body).status_code == 201
    root = network_xml(conn, "LAN-1")
    assert root.find("ip") is None
    assert root.find("bridge").get("name") == "kvmnet4"  # type: ignore[union-attr]


def test_number_and_subnet_are_suggested(client: TestClient) -> None:
    suggestion = client.get("/api/networks/suggestion", headers=AUTH).json()
    assert suggestion["name"] == "kvmnet1"
    assert suggestion["subnet"] == "192.168.101.0/24"
    assert suggestion["dhcp"] == {"start": "192.168.101.128", "end": "192.168.101.254"}


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (host_only("192.168.122.0/24"), "net.overlap"),  # libvirt's default network
        (host_only("192.168.1.0/25", dhcp=None), "net.overlap"),  # the host LAN
        (host_only("8.8.8.0/24"), "net.not_private"),
        (host_only("10.0.0.0/31"), "net.bad_prefix"),
        (host_only(host_adapter=False), "net.dhcp_needs_adapter"),
        ({"kind": "nat", "subnet": "10.9.0.0/24", "host_adapter": False}, "net.nat_needs_adapter"),
        (host_only(dhcp={"start": "192.168.150.1", "end": "192.168.150.1"}), "net.bad_dhcp"),
        (host_only(host_ip="192.168.150.0"), "net.address_reserved"),
        (host_only(host_ip="192.168.150.255"), "net.address_reserved"),
        (host_only(host_ip="192.168.9.1"), "net.address_outside"),
        (host_only(gateway="custom"), "net.gateway_required"),
        (host_only(dhcp=None, gateway="host"), "net.needs_dhcp"),
        (host_only(dhcp={"start": "192.168.151.2", "end": "192.168.151.9"}), "net.bad_dhcp"),
        (host_only(subnet="nonsense"), "net.bad_subnet"),
        ({**host_only(), "name": "bad name"}, "net.bad_name"),
    ],
)
def test_invalid_networks_are_refused(client: TestClient, body: dict[str, Any], code: str) -> None:
    response = client.post("/api/networks", headers=AUTH, json=body)
    assert response.status_code in (409, 422)
    assert response.json()["error"]["code"] == code


def test_names_and_bridges_are_unique(client: TestClient) -> None:
    client.post("/api/networks", headers=AUTH, json={**host_only(), "number": 3})
    again = client.post(
        "/api/networks", headers=AUTH, json={**host_only("10.3.0.0/24"), "number": 3}
    )
    assert again.json()["error"]["code"] == "net.exists"
    other_name = {**host_only("10.4.0.0/24"), "number": 3, "name": "other"}
    assert client.post("/api/networks", headers=AUTH, json=other_name).json()["error"]["code"] == (
        "net.bridge_taken"
    )
    reserved = client.post(
        "/api/networks", headers=AUTH, json={**host_only("10.5.0.0/24"), "number": 0}
    )
    assert reserved.status_code == 422


def test_switch_host_only_to_nat(client: TestClient, conn: LibvirtConnection) -> None:
    client.post("/api/networks", headers=AUTH, json={**host_only(), "number": 3})
    body = {**host_only(), "kind": "nat"}
    # Running network: redefined then restarted (applied by libvirt on restart).
    assert client.put("/api/networks/kvmnet3", headers=AUTH, json=body).status_code == 204
    assert networks(client)["kvmnet3"]["active"] is True
    # The test driver only shows the new definition on a stopped network.
    client.patch("/api/networks/kvmnet3", headers=AUTH, json={"active": False})
    assert client.put("/api/networks/kvmnet3", headers=AUTH, json=body).status_code == 204
    assert network_xml(conn, "kvmnet3").find("forward").get("mode") == "nat"  # type: ignore[union-attr]


def test_changes_needing_a_restart_wait_for_running_vms(
    client: TestClient, conn: LibvirtConnection
) -> None:
    client.post("/api/networks", headers=AUTH, json={**host_only(), "number": 3})
    vm = add_vm(conn, "kvmnet3", start=True)
    response = client.put("/api/networks/kvmnet3", headers=AUTH, json=host_only("10.7.0.0/24"))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "net.in_use"
    assert vm.name() in response.json()["error"]["detail"]
    assert networks(client)["kvmnet3"]["used_by"] == [vm.name()]


def test_rename_follows_vm_configs(client: TestClient, conn: LibvirtConnection) -> None:
    client.post("/api/networks", headers=AUTH, json={**host_only(), "number": 3})
    vm = add_vm(conn, "kvmnet3", start=False)
    response = client.post("/api/networks/kvmnet3/rename", headers=AUTH, json={"name": "LAN-DMZ"})
    assert response.status_code == 204
    found = networks(client)
    assert "kvmnet3" not in found
    assert found["LAN-DMZ"]["bridge"] == "kvmnet3"
    assert found["LAN-DMZ"]["active"] is True
    xml = vm.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)
    assert "network='LAN-DMZ'" in xml or 'network="LAN-DMZ"' in xml


def test_rename_refuses_running_users(client: TestClient, conn: LibvirtConnection) -> None:
    client.post("/api/networks", headers=AUTH, json={**host_only(), "number": 3})
    add_vm(conn, "kvmnet3", start=True)
    response = client.post("/api/networks/kvmnet3/rename", headers=AUTH, json={"name": "x"})
    assert response.json()["error"]["code"] == "net.in_use"


def test_delete_only_unused_networks(client: TestClient, conn: LibvirtConnection) -> None:
    client.post("/api/networks", headers=AUTH, json={**host_only(), "number": 3})
    vm = add_vm(conn, "kvmnet3", start=False)
    response = client.delete("/api/networks/kvmnet3", headers=AUTH)
    assert response.status_code == 409
    assert vm.name() in response.json()["error"]["detail"]
    vm.undefine()
    assert client.delete("/api/networks/kvmnet3", headers=AUTH).status_code == 204
    assert "kvmnet3" not in networks(client)


def test_start_stop_and_autostart(client: TestClient) -> None:
    client.post("/api/networks", headers=AUTH, json={**host_only(), "number": 3})
    client.patch("/api/networks/kvmnet3", headers=AUTH, json={"active": False, "autostart": False})
    state = networks(client)["kvmnet3"]
    assert (state["active"], state["autostart"]) == (False, False)
    client.patch("/api/networks/kvmnet3", headers=AUTH, json={"active": True})
    assert networks(client)["kvmnet3"]["active"] is True


def test_unknown_network_is_a_404(client: TestClient) -> None:
    response = client.delete("/api/networks/nope", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "libvirt.no_network"


def test_default_networks(client: TestClient, conn: LibvirtConnection) -> None:
    assert client.post("/api/networks/defaults", headers=AUTH).json() == ["kvmnet1", "kvmnet8"]
    found = networks(client)
    assert found["kvmnet1"]["kind"] == "host_only"
    assert found["kvmnet1"]["subnet"] == "192.168.101.0/24"
    assert found["kvmnet1"]["dhcp"] is not None
    assert found["kvmnet8"]["kind"] == "nat"
    assert found["kvmnet8"]["subnet"] == "192.168.108.0/24"
    # Running it again resets settings but keeps the subnets.
    client.put(
        "/api/networks/kvmnet8", headers=AUTH, json={"kind": "host_only", "host_adapter": False}
    )
    client.post("/api/networks/defaults", headers=AUTH)
    again = networks(client)["kvmnet8"]
    assert again["kind"] == "nat"
    assert again["subnet"] == "192.168.108.0/24"


def test_default_subnets_avoid_what_is_taken(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    taken = ipaddress.IPv4Network("192.168.101.0/24")
    monkeypatch.setattr(net, "host_subnets", lambda: [("wlp2s0", taken)])
    client.post("/api/networks/defaults", headers=AUTH)
    assert networks(client)["kvmnet1"]["subnet"] == "192.168.102.0/24"


def test_export_then_import(client: TestClient) -> None:
    client.post("/api/networks", headers=AUTH, json={**host_only(), "number": 3})
    client.post(
        "/api/networks",
        headers=AUTH,
        json={"kind": "host_only", "host_adapter": False, "name": "LAN-2", "number": 5},
    )
    exported = client.get("/api/networks/export", headers=AUTH).json()
    assert exported["format"] == "kvm-studio-networks"
    assert sorted(n["name"] for n in exported["networks"]) == ["LAN-2", "kvmnet3"]  # not "default"

    client.delete("/api/networks/LAN-2", headers=AUTH)
    report = client.post("/api/networks/import", headers=AUTH, json=exported).json()
    assert report == {"created": ["LAN-2"], "skipped": ["kvmnet3"]}
    assert networks(client)["LAN-2"]["bridge"] == "kvmnet5"


def test_any_display_name_gets_a_kvmnet_bridge(client: TestClient, conn: LibvirtConnection) -> None:
    """Whatever the name, the interface is kvmnetN, so NetworkManager hides it."""
    body = {**host_only(), "name": "Host-Only-3"}
    created = client.post("/api/networks", headers=AUTH, json=body).json()
    assert created["name"] == "Host-Only-3"
    assert created["bridge"].startswith("kvmnet")
    assert network_xml(conn, "Host-Only-3").find("bridge").get("name") == created["bridge"]  # type: ignore[union-attr]
    client.post("/api/networks/Host-Only-3/rename", headers=AUTH, json={"name": "LAB"})
    assert networks(client)["LAB"]["bridge"] == created["bridge"]


NEW = {"name": "kvmnet5", "number": 5}


def test_host_address_anywhere_in_the_subnet_moves_the_dhcp_range(
    client: TestClient, conn: LibvirtConnection
) -> None:
    body = {**host_only(host_ip="192.168.150.254"), **NEW}
    assert client.post("/api/networks", headers=AUTH, json=body).status_code == 201
    created = networks(client)["kvmnet5"]
    assert created["host_ip"] == "192.168.150.254"
    # .128-.254 held the host address: it now ends right below it.
    assert created["dhcp"] == {"start": "192.168.150.128", "end": "192.168.150.253"}
    ip = network_xml(conn, "kvmnet5").find("ip")
    assert ip is not None
    assert ip.get("address") == "192.168.150.254"


def test_gateway_announced_on_host_only(client: TestClient, conn: LibvirtConnection) -> None:
    subnet = ipaddress.IPv4Network("192.168.150.0/24")
    dhcp = net.DhcpRange("192.168.150.128", "192.168.150.254")
    custom = net.NetworkSpec("host_only", subnet, True, dhcp, None, "custom", "192.168.150.254")
    xml = net.apply_spec(None, "lab", "kvmnet5", custom)
    root = etree.fromstring(xml.encode())
    option = root.find(f"{{{net.DNSMASQ_NS}}}options/{{{net.DNSMASQ_NS}}}option")
    assert option is not None
    assert option.get("value") == "dhcp-option=option:router,192.168.150.254"
    assert net.parse_gateway(xml) == ("custom", "192.168.150.254")
    # libvirt wants the dnsmasq options last.
    assert [etree.QName(c).localname for c in root][-2:] == ["ip", "options"]

    # None at all: an empty router option. Other dnsmasq options stay.
    root.find(f"{{{net.DNSMASQ_NS}}}options").append(  # type: ignore[union-attr]
        etree.Element(f"{{{net.DNSMASQ_NS}}}option", value="log-dhcp")
    )
    kept = etree.tostring(root).decode()
    none = net.NetworkSpec("host_only", subnet, True, dhcp, None, "none")
    xml = net.apply_spec(kept, "lab", "kvmnet5", none)
    assert net.parse_gateway(xml)[0] == "none"
    # libvirt already announces no gateway on a host-only network.
    assert "dhcp-option=3" not in xml
    assert "log-dhcp" in xml
    # The host itself: its address, which follows when it changes.
    host = net.NetworkSpec("host_only", subnet, True, dhcp, "192.168.150.254", "host")
    xml = net.apply_spec(xml, "lab", "kvmnet5", host)
    assert "dhcp-option=option:router,192.168.150.254" in xml
    assert net.parse_gateway(xml) == ("host", None)
    back = net.apply_spec(xml, "lab", "kvmnet5", net.NetworkSpec("host_only", subnet, True, dhcp))
    assert "router" not in back
    assert "dhcp-option=3" not in back
    assert "log-dhcp" in back

    client.post("/api/networks", headers=AUTH, json={**host_only(), **NEW}).raise_for_status()
    same = client.post("/api/networks/kvmnet5/plan", headers=AUTH, json=host_only(gateway="none"))
    assert same.json() == {"restart": False, "running": []}
    plan = client.post("/api/networks/kvmnet5/plan", headers=AUTH, json=host_only(gateway="host"))
    assert plan.json() == {"restart": True, "running": []}
    # NAT: the gateway is the host address, nothing else.
    nat = {**host_only(), "kind": "nat", "gateway": "custom", "gateway_ip": "192.168.150.9"}
    r = client.put("/api/networks/kvmnet5", headers=AUTH, json=nat)
    assert r.json()["error"]["code"] == "net.gateway_nat"


def test_restart_with_running_vms_needs_a_confirmation(
    client: TestClient, conn: LibvirtConnection
) -> None:
    client.post("/api/networks", headers=AUTH, json={**host_only(), **NEW}).raise_for_status()
    uuid = str(uuidlib.uuid4())
    xml = (
        f"<domain type='test'><name>net-test-vm</name><uuid>{uuid}</uuid>"
        "<memory unit='MiB'>64</memory><os><type>hvm</type></os><devices>"
        "<interface type='network'><source network='kvmnet5'/></interface>"
        "</devices></domain>"
    )
    conn.run(lambda c: c.defineXML(xml).create())
    moved = host_only(host_ip="192.168.150.2")
    plan = client.post("/api/networks/kvmnet5/plan", headers=AUTH, json=moved).json()
    assert plan == {"restart": True, "running": ["net-test-vm"]}
    r = client.put("/api/networks/kvmnet5", headers=AUTH, json=moved)
    assert r.json()["error"]["code"] == "net.in_use"
    r = client.put("/api/networks/kvmnet5", headers=AUTH, json={**moved, "stop_vms": "poweroff"})
    # (The test driver keeps the old live definition: checked on a real host.)
    assert r.status_code == 204
    # Started again once the network is back.
    assert conn.run(lambda c: c.lookupByName("net-test-vm").isActive())


def test_static_hosts_set_with_virsh_are_kept() -> None:
    subnet = ipaddress.IPv4Network("192.168.150.0/24")
    dhcp = net.DhcpRange("192.168.150.128", "192.168.150.254")
    xml = net.apply_spec(None, "lab", "kvmnet5", net.NetworkSpec("host_only", subnet, True, dhcp))
    root = etree.fromstring(xml.encode())
    dhcp_el = root.find("ip/dhcp")
    assert dhcp_el is not None
    etree.SubElement(dhcp_el, "host", mac="52:54:00:aa:bb:cc", ip="192.168.150.20")
    moved = net.NetworkSpec("host_only", subnet, True, dhcp, "192.168.150.254")
    again = net.apply_spec(etree.tostring(root).decode(), "lab", "kvmnet5", moved)
    assert "192.168.150.20" in again
    # Nothing of the kind is ever added by KVM Studio itself.
    assert "<host" not in xml


def test_port_forwards_go_through_the_helper(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kvmstudio import helper_client

    stored: dict[str, list[dict[str, Any]]] = {}
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake(op: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append((op, params))
        if op == "list_port_forwards":
            return {"networks": stored}
        stored[params["network"]] = params["rules"]
        if not params["rules"]:
            del stored[params["network"]]
        return {"rules": len(params["rules"])}

    monkeypatch.setattr(helper_client, "call", fake)
    rule = {"proto": "tcp", "host_port": 2222, "vm_ip": "192.168.150.9", "vm_port": 22}
    r = client.put("/api/networks/kvmnet5/forwards", headers=AUTH, json={"rules": [rule]})
    assert r.status_code == 200
    # Host address 127.0.0.1 unless written otherwise; nothing else is decided here.
    assert calls[0] == (
        "set_port_forwards",
        {"network": "kvmnet5", "rules": [{**rule, "host_address": "127.0.0.1", "description": ""}]},
    )
    got = client.get("/api/networks/kvmnet5/forwards", headers=AUTH).json()
    assert got["rules"][0]["vm_ip"] == "192.168.150.9"

    # Deleting the network takes its rules away.
    client.post("/api/networks", headers=AUTH, json={**host_only(), **NEW}).raise_for_status()
    assert client.delete("/api/networks/kvmnet5", headers=AUTH).status_code == 204
    assert calls[-1] == ("set_port_forwards", {"network": "kvmnet5", "rules": []})


def test_listening_ports(tmp_path: Any) -> None:
    header = "  sl  local_address rem_address   st\n"
    (tmp_path / "tcp").write_text(
        header
        + "   0: 0100007F:1F90 00000000:0000 0A 0\n"  # 127.0.0.1:8080 LISTEN
        + "   1: 0100007F:0016 0200007F:9C40 01 0\n"  # established, not a listener
    )
    (tmp_path / "udp6").write_text(header + "   0: 00000000000000000000000000000000:0035 0 07\n")
    assert net.listening_ports(str(tmp_path)) == {"tcp": [8080], "udp": [53]}
