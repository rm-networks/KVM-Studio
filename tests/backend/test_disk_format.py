"""Disk formats come from the definition or the file name, never from the content.

A VM writes what it wants in its raw disk, a qcow2 header too, whose backing
file may name any file of the host. Every way to bring an existing disk in
(Add Hard Disk, a new VM from a disk, clone, scanner, library import) must
leave that file unread.
"""

from __future__ import annotations

import contextlib
import shutil
from collections.abc import Iterator
from pathlib import Path

import libvirt
import pytest
from fastapi.testclient import TestClient
from lxml import etree

from kvmstudio.config import Config
from kvmstudio.errors import ApiException
from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.services import clone, create, disks, qemu_img, scan
from kvmstudio.services.tasks import Task

from .helpers import AUTH, add_domain
from .helpers import domain_xml as make_xml

pytestmark = pytest.mark.skipif(not shutil.which("qemu-img"), reason="no qemu-img")

SECRET = b"test-SECRET-content"


@pytest.fixture
def secret(tmp_path: Path) -> Path:
    path = tmp_path / "outside" / "test-secret.txt"
    path.parent.mkdir()
    path.write_bytes(SECRET * 64)
    path.chmod(0o600)
    return path


def header_to(path: Path, backing: Path) -> Path:
    """A file holding a qcow2 header whose backing file is backing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    qemu_img._run(
        ["create", "-q", "-f", "qcow2", "-u", "-b", str(backing), "-F", "raw", str(path), "1M"]
    )
    return path


def plain_qcow2(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    qemu_img.create(path, "qcow2", 1, preallocate=False)
    return path


def holds_secret(path: Path) -> bool:
    return SECRET in path.read_bytes()


def disk_elements(conn: LibvirtConnection, name: str) -> list[etree._Element]:
    xml = conn.run(lambda c: c.lookupByName(name).XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))
    return list(etree.fromstring(xml.encode()).iterfind("devices/disk[@device='disk']"))


def driver_type(disk: etree._Element) -> str | None:
    driver = disk.find("driver")
    return driver.get("type") if driver is not None else None


@pytest.fixture
def vm(conn: LibvirtConnection, lib_config: Config) -> Iterator[str]:
    new = create.NewVm(
        name="test-fmt-vm",
        folder="",
        profile="linux",
        iso=None,
        existing_disk=None,
        disk_gib=1,
        disk_bus="virtio",
        disk_format="qcow2",
        preallocate=False,
        memory_mib=512,
        vcpus=1,
        nics=[],
        uefi=False,
        tpm=False,
    )
    uuid = create.create_vm(conn, lib_config, new)
    yield uuid
    for dom in conn.run(lambda c: c.listAllDomains()):
        if dom.name().startswith("test-"):
            with contextlib.suppress(libvirt.libvirtError):
                if dom.isActive():
                    dom.destroy()
                dom.undefine()


def test_qemu_img_is_always_told_the_format(tmp_path: Path, secret: Path) -> None:
    evil = header_to(tmp_path / "vm.img", secret)
    assert qemu_img.format_from_name(evil) == "raw"
    assert qemu_img.format_from_name(tmp_path / "a.QCOW2") == "qcow2"
    assert qemu_img.backing_files(evil, "raw") == []
    info = qemu_img.image_info(evil, "raw")
    assert info is not None
    assert info["format"] == "raw"
    copy = tmp_path / "copy.raw"
    qemu_img.convert(evil, "raw", copy, "raw")
    assert not holds_secret(copy)


def test_a_guest_chain_is_not_opened_outside_the_library(
    lib_config: Config, library: Path, secret: Path
) -> None:
    evil = header_to(library / "test-evil.qcow2", secret)
    secret.chmod(0)  # opening it would fail: a refusal proves it was not opened
    seen: list[Path] = []

    def stop(path: Path) -> bool:
        seen.append(path)
        return True

    chain = qemu_img.backing_files(evil, "qcow2", stop=stop)
    assert chain == [str(secret)]
    assert seen == [secret]


@pytest.mark.parametrize("confined", [False, True])
def test_add_existing_raw_disk_with_a_qcow2_header(
    conn: LibvirtConnection,
    lib_config: Config,
    library: Path,
    secret: Path,
    vm: str,
    confined: bool,
) -> None:
    evil = header_to(library / "test-shared" / "test-evil.img", secret)
    disks.add(conn, lib_config, vm, bus="virtio", existing=str(evil), confined=confined)
    added = disk_elements(conn, "test-fmt-vm")[-1]
    assert driver_type(added) == "raw"
    assert added.find("backingStore") is None


def test_add_existing_qcow2_with_a_base(
    conn: LibvirtConnection, lib_config: Config, library: Path, secret: Path, vm: str
) -> None:
    evil = header_to(library / "test-shared" / "test-evil.qcow2", secret)
    with pytest.raises(ApiException) as err:
        disks.add(conn, lib_config, vm, bus="virtio", existing=str(evil), confined=True)
    assert (err.value.status, err.value.code) == (403, "path.not_allowed")
    assert len(disk_elements(conn, "test-fmt-vm")) == 1
    # The owner is free: a template or a base anywhere, the chain is logged.
    disks.add(conn, lib_config, vm, bus="virtio", existing=str(evil))
    assert driver_type(disk_elements(conn, "test-fmt-vm")[-1]) == "qcow2"


def test_add_existing_qcow2_without_base_gets_an_empty_backing_store(
    conn: LibvirtConnection, lib_config: Config, library: Path, vm: str
) -> None:
    alone = plain_qcow2(library / "test-shared" / "test-alone.qcow2")
    disks.add(conn, lib_config, vm, bus="virtio", existing=str(alone), confined=True)
    added = disk_elements(conn, "test-fmt-vm")[-1]
    store = added.find("backingStore")
    assert store is not None
    assert len(store) == 0


def test_guest_cannot_attach_the_disk_of_another_vm(
    conn: LibvirtConnection, lib_config: Config, library: Path, vm: str
) -> None:
    other = create.NewVm(
        name="test-fmt-other",
        folder="",
        profile="linux",
        iso=None,
        existing_disk=None,
        disk_gib=1,
        disk_bus="virtio",
        disk_format="qcow2",
        preallocate=False,
        memory_mib=512,
        vcpus=1,
        nics=[],
        uefi=False,
        tpm=False,
    )
    create.create_vm(conn, lib_config, other)
    theirs = library / "test-fmt-other" / "test-fmt-other.qcow2"
    with pytest.raises(ApiException) as err:
        disks.add(conn, lib_config, vm, bus="virtio", existing=str(theirs), confined=True)
    assert (err.value.status, err.value.code) == (403, "disk.in_use")


def new_from(name: str, existing: Path, mode: create.ExistingMode, confined: bool) -> create.NewVm:
    return create.NewVm(
        name=name,
        folder="",
        profile="linux",
        iso=None,
        existing_disk=str(existing),
        existing_mode=mode,
        disk_gib=0,
        disk_bus="virtio",
        disk_format="qcow2",
        preallocate=False,
        memory_mib=512,
        vcpus=1,
        nics=[],
        uefi=False,
        tpm=False,
        confined=confined,
    )


@pytest.mark.parametrize("confined", [False, True])
def test_new_vm_from_a_raw_disk_with_a_qcow2_header(
    conn: LibvirtConnection,
    lib_config: Config,
    library: Path,
    secret: Path,
    vm: str,
    confined: bool,
) -> None:
    evil = header_to(library / "test-shared" / "test-evil.img", secret)
    create.create_vm(conn, lib_config, new_from("test-fmt-copy", evil, "copy", confined))
    copy = library / "test-fmt-copy" / "test-fmt-copy.raw"
    assert not holds_secret(copy)
    assert driver_type(disk_elements(conn, "test-fmt-copy")[0]) == "raw"
    create.create_vm(conn, lib_config, new_from("test-fmt-here", evil, "in_place", confined))
    assert driver_type(disk_elements(conn, "test-fmt-here")[0]) == "raw"


def test_guest_new_vm_refuses_a_base_outside_the_library(
    conn: LibvirtConnection, lib_config: Config, library: Path, secret: Path, vm: str
) -> None:
    evil = header_to(library / "test-shared" / "test-evil.qcow2", secret)
    for mode in ("copy", "in_place"):
        with pytest.raises(ApiException) as err:
            create.create_vm(conn, lib_config, new_from("test-fmt-no", evil, mode, True))
        assert err.value.status == 403
    assert not (library / "test-fmt-no" / "test-fmt-no.qcow2").exists()


def run_clone(conn: LibvirtConnection, plan: clone.ClonePlan) -> None:
    clone.run(conn, plan, Task("test-clone", "clone"))


@pytest.mark.parametrize("confined", [False, True])
def test_clone_copies_a_raw_disk_as_raw(
    conn: LibvirtConnection,
    lib_config: Config,
    define: list[libvirt.virDomain],
    library: Path,
    secret: Path,
    confined: bool,
) -> None:
    evil = header_to(library / "test-src" / "test-src.img", secret)
    src = add_domain(conn, define, make_xml("test-src", [("disk", str(evil))]))
    name = f"test-copy-{int(confined)}"
    plan = clone.prepare(conn, lib_config, src.UUIDString(), "full", name, "", confined=confined)
    run_clone(conn, plan)
    copied = disk_elements(conn, name)[0]
    assert driver_type(copied) == "raw"
    assert not holds_secret(Path(copied.find("source").get("file")))  # type: ignore[union-attr,arg-type]
    for dom in conn.run(lambda c: c.listAllDomains()):
        if dom.name() == name:
            define.append(dom)


def test_guest_clone_refuses_a_base_outside_the_library(
    conn: LibvirtConnection,
    lib_config: Config,
    define: list[libvirt.virDomain],
    library: Path,
    secret: Path,
) -> None:
    evil = header_to(library / "test-src" / "test-src.qcow2", secret)
    src = add_domain(conn, define, make_xml("test-src", [("disk", str(evil))]))
    kinds: list[clone.Kind] = ["full", "linked"]
    for kind in kinds:
        with pytest.raises(ApiException) as err:
            clone.prepare(conn, lib_config, src.UUIDString(), kind, "test-c", "", confined=True)
        assert (err.value.status, err.value.code) == (403, "path.not_allowed")


def test_full_clone_has_an_empty_backing_store(
    conn: LibvirtConnection, lib_config: Config, define: list[libvirt.virDomain], library: Path
) -> None:
    disk = plain_qcow2(library / "test-src" / "test-src.qcow2")
    src = add_domain(conn, define, make_xml("test-src", [("disk", str(disk))]))
    plan = clone.prepare(conn, lib_config, src.UUIDString(), "full", "test-full", "")
    run_clone(conn, plan)
    for dom in conn.run(lambda c: c.listAllDomains()):
        if dom.name() == "test-full":
            define.append(dom)
    store = disk_elements(conn, "test-full")[0].find("backingStore")
    assert store is not None
    assert len(store) == 0


def test_scanner_copies_a_raw_disk_as_raw(
    conn: LibvirtConnection,
    lib_config: Config,
    define: list[libvirt.virDomain],
    tmp_path: Path,
    secret: Path,
) -> None:
    found = tmp_path / "test-backup" / "test-scanned"
    evil = header_to(found / "test-scanned.img", secret)
    (found / "test-scanned.xml").write_text(
        make_xml("test-scanned", [("disk", str(evil))]).replace(
            "<source", "<driver name='qemu' type='raw'/><source"
        )
    )
    items = scan.scan(conn, str(tmp_path / "test-backup"))
    assert [i.name for i in items] == ["test-scanned"]
    outcome = scan.import_found(
        conn, lib_config, str(tmp_path / "test-backup"), [scan.Choice(items[0].id, "copy")]
    )
    assert outcome.imported == ["test-scanned"], outcome.failed
    for dom in conn.run(lambda c: c.listAllDomains()):
        if dom.name() == "test-scanned":
            define.append(dom)
    disk = disk_elements(conn, "test-scanned")[0]
    assert driver_type(disk) == "raw"
    assert not holds_secret(Path(disk.find("source").get("file")))  # type: ignore[union-attr,arg-type]


def test_library_import_copies_a_raw_disk_as_raw(
    lib_client: TestClient,
    conn: LibvirtConnection,
    define: list[libvirt.virDomain],
    tmp_path: Path,
    library: Path,
    secret: Path,
) -> None:
    evil = header_to(tmp_path / "images" / "test-imp.img", secret)
    dom = add_domain(conn, define, make_xml("test-imp", [("disk", str(evil))]))
    r = lib_client.post(f"/api/vms/{dom.UUIDString()}/import", headers=AUTH, json={"folder": ""})
    assert r.status_code == 200, r.text
    copy = library / "test-imp" / "test-imp.raw"
    assert not holds_secret(copy)
    assert driver_type(disk_elements(conn, "test-imp")[0]) == "raw"
