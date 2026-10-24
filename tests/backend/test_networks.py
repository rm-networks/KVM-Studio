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
        (host_only(dhcp={"start": "192.168.150.1", "end": "192.168.150.9"}), "net.bad_dhcp"),
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
