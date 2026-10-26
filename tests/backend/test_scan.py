"""Scanning a folder for virtual machines, then importing them."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import libvirt
from fastapi.testclient import TestClient

from kvmstudio.libvirt_conn import LibvirtConnection

from .helpers import AUTH, add_domain, needs_qemu_img, qcow2
from .helpers import domain_xml as make_xml

ROUTER_XML = """<domain type='test'>
  <name>Router</name>
  <uuid>6f0e1c55-2a51-4f43-9d55-7d1c0f1e2a01</uuid>
  <memory>65536</memory>
  <os><type>hvm</type></os>
  <devices>
    <disk type='file' device='disk'><source file='/old/place/Router.qcow2'/>
      <target dev='vda'/></disk>
  </devices>
</domain>"""


def tree(tmp_path: Path) -> Path:
    top = tmp_path / "old-disk"
    qcow2(top / "KVM-Studio" / "VM" / "Labs" / "Web" / "Web.qcow2")
    qcow2(top / "Network" / "Router" / "Router.qcow2")
    (top / "Network" / "Router" / "Router.xml").write_text(ROUTER_XML)
    qcow2(top / "Known" / "known.qcow2")
    return top


@needs_qemu_img
def test_scan_lists_vms_and_marks_the_known_ones(
    tmp_path: Path, lib_client: TestClient, conn: LibvirtConnection, define: list[Any]
) -> None:
    top = tree(tmp_path)
    add_domain(conn, define, make_xml("Mine", [("disk", str(top / "Known" / "known.qcow2"))]))
    found = lib_client.get("/api/scan", headers=AUTH, params={"path": str(top)}).json()
    by_name = {f["name"]: f for f in found}
    assert set(by_name) == {"Web", "Router", "Known"}
    assert (by_name["Web"]["folder"], by_name["Web"]["known"]) == ("Labs", None)
    router = by_name["Router"]
    assert router["definition"] == str(top / "Network" / "Router" / "Router.xml")
    # The definition points to the old place: the disk next to it is used.
    assert router["disks"] == [str(top / "Network" / "Router" / "Router.qcow2")]
    assert router["folder"] == "Network"
    assert by_name["Known"]["known"] == "Mine"


@needs_qemu_img
def test_import_keeps_copies_or_moves_after_a_plan(
    tmp_path: Path,
    library: Path,
    lib_client: TestClient,
    conn: LibvirtConnection,
    define: list[Any],
) -> None:
    top = tree(tmp_path)
    found = {
        f["name"]: f
        for f in lib_client.get("/api/scan", headers=AUTH, params={"path": str(top)}).json()
    }
    choices = [
        {"id": found["Web"]["id"], "mode": "keep"},
        {"id": found["Router"]["id"], "mode": "move"},
    ]
    body = {"path": str(top), "choices": choices}
    plan = lib_client.post("/api/scan/plan", headers=AUTH, json=body).json()
    router_disk = top / "Network" / "Router" / "Router.qcow2"
    target = library / "Network" / "Router" / "Router.qcow2"
    assert plan == {"moves": [[str(router_disk), str(target)]]}

    result = lib_client.post("/api/scan/import", headers=AUTH, json=body).json()
    try:
        assert result == {"imported": ["Web", "Router"], "failed": []}
        assert target.is_file()
        assert not router_disk.exists()
        web_disk = top / "KVM-Studio" / "VM" / "Labs" / "Web" / "Web.qcow2"
        assert web_disk.is_file()
        vms = {v["name"]: v for v in lib_client.get("/api/vms", headers=AUTH).json()}
        assert vms["Web"]["folder"] == "Labs"
        assert vms["Router"]["folder"] == "Network"
        assert vms["Router"]["managed"]
        assert "Labs" in lib_client.get("/api/library", headers=AUTH).json()["folders"]
        router = conn.run(lambda c: c.lookupByName("Router"))
        assert str(target) in router.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)
        # Already in libvirt now: a second import is refused.
        again = lib_client.post("/api/scan/import", headers=AUTH, json=body)
        assert again.status_code == 409
    finally:

        def undefine(c: libvirt.virConnect) -> None:
            for name in ("Web", "Router"):
                c.lookupByName(name).undefine()

        conn.run(undefine)
