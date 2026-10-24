from __future__ import annotations

import os
import shutil
import struct
import threading
import uuid as uuidlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import libvirt
import pytest
from fastapi.testclient import TestClient

from kvmstudio.app import create_app
from kvmstudio.config import Config, IsoLibrary, LibvirtSettings
from kvmstudio.isolib import access
from kvmstudio.isolib.scan import scan
from kvmstudio.libvirt_conn import LibvirtConnection

from .conftest import TEST_URI, TOKEN
from .helpers import AUTH, touch


@pytest.fixture
def isos(tmp_path: Path) -> Path:
    root = tmp_path / "srv" / "iso"
    touch(root / "debian-13.iso")
    touch(root / "Windows" / "Win11_24H2.ISO")
    touch(root / "Windows" / "Server" / "SRV2025.iso")
    touch(root / "Firewalls" / "OPNsense" / "opnsense-25.7.img")
    touch(root / "notes.txt")
    touch(root / ".hidden" / "secret.iso")
    return root


@pytest.fixture
def iso_config(isos: Path) -> Config:
    return Config(
        libvirt=LibvirtSettings(uri=TEST_URI),
        iso_libraries=[IsoLibrary(name="ISO principales", path=isos)],
    )


@pytest.fixture
def iso_client(iso_config: Config, conn: LibvirtConnection, frontend_dir: Path) -> TestClient:
    app = create_app(iso_config, conn, TOKEN, mode="web", frontend_dir=frontend_dir)
    return TestClient(app, base_url="http://127.0.0.1")


def test_scan_walks_subfolders_read_only(iso_config: Config, isos: Path) -> None:
    before = sorted(p.relative_to(isos) for p in isos.rglob("*"))
    statuses, files = scan(iso_config)
    assert [s.available for s in statuses] == [True]
    assert sorted(f.relative for f in files) == [
        "Firewalls/OPNsense/opnsense-25.7.img",
        "Windows/Server/SRV2025.iso",
        "Windows/Win11_24H2.ISO",
        "debian-13.iso",
    ]
    assert sorted(p.relative_to(isos) for p in isos.rglob("*")) == before  # nothing written


def test_scan_without_subfolders(iso_config: Config) -> None:
    iso_config.iso_libraries[0].recursive = False
    _statuses, files = scan(iso_config)
    assert [f.relative for f in files] == ["debian-13.iso"]


def test_symlinks_cannot_escape_the_library(iso_config: Config, isos: Path, tmp_path: Path) -> None:
    outside = touch(tmp_path / "elsewhere" / "private.iso")
    (isos / "link.iso").symlink_to(outside)
    (isos / "linkdir").symlink_to(outside.parent)
    _statuses, files = scan(iso_config)
    assert all("private" not in f.path for f in files)


def test_missing_library_is_reported(tmp_path: Path) -> None:
    config = Config(iso_libraries=[IsoLibrary(name="USB", path=tmp_path / "unplugged")])
    statuses, files = scan(config)
    assert statuses[0].available is False
    assert files == []


def test_iso_listing_api(iso_client: TestClient) -> None:
    data: dict[str, Any] = iso_client.get("/api/isos", headers=AUTH).json()
    assert data["libraries"][0]["name"] == "ISO principales"
    assert len(data["isos"]) == 4
    item = next(i for i in data["isos"] if i["relative"] == "debian-13.iso")
    assert item["size"] == 512


# Access checks


def _identity(uid: int, gid: int, *groups: int) -> access.Identity:
    return access.Identity(uid, gid, frozenset({gid, *groups}), "qemu")


def problems_under(report: access.AccessReport, base: Path) -> list[tuple[str, str]]:
    """pytest's own temporary folders are private: judge only the tested tree."""
    return [(k, p) for k, p in report.problems if Path(p).is_relative_to(base) and Path(p) != base]


def test_mode_bits_for_another_user(tmp_path: Path) -> None:
    home = tmp_path / "home"
    iso = touch(home / "ISO" / "a.iso")
    qemu = _identity(65000, 65000)
    home.chmod(0o700)
    iso.chmod(0o644)
    try:
        report = access.check(str(iso), qemu, selinux=False)
        assert report.readable is False
        assert ("no_search", str(home)) in report.problems
        assert any("setfacl -m u:qemu:x" in c and str(home) in c for c in report.commands)
        home.chmod(0o711)
        assert problems_under(access.check(str(iso), qemu, selinux=False), tmp_path) == []
        iso.chmod(0o600)
        report = access.check(str(iso), qemu, selinux=False)
        assert ("no_read", str(iso)) in report.problems
    finally:
        home.chmod(0o755)


def test_acl_entries_are_honoured(tmp_path: Path) -> None:
    folder = tmp_path / "locked"
    iso = touch(folder / "b.iso")
    folder.chmod(0o700)
    qemu = _identity(65001, 65001)
    acl = struct.pack("<I", 2) + b"".join(
        struct.pack("<HHI", tag, perm, ident)
        for tag, perm, ident in [
            (access.ACL_USER_OBJ, 7, 0xFFFFFFFF),
            (access.ACL_USER, 1, 65001),  # u:qemu:x
            (access.ACL_GROUP_OBJ, 0, 0xFFFFFFFF),
            (access.ACL_MASK, 1, 0xFFFFFFFF),
            (access.ACL_OTHER, 0, 0xFFFFFFFF),
        ]
    )
    try:
        os.setxattr(folder, access.ACL_XATTR, acl)
    except OSError:
        pytest.skip("this filesystem has no POSIX ACLs")
    try:
        assert access.allowed(folder, qemu, access.X) is True
        assert access.allowed(folder, qemu, access.R) is False
        assert problems_under(access.check(str(iso), qemu, selinux=False), tmp_path) == []
    finally:
        folder.chmod(0o755)


def test_missing_file(tmp_path: Path) -> None:
    report = access.check(str(tmp_path / "nope.iso"), None, selinux=False)
    assert report.problems == [("missing", str(tmp_path / "nope.iso"))]


def test_qemu_identity_from_capabilities() -> None:
    caps = (
        "<capabilities><host><secmodel><model>selinux</model></secmodel>"
        "<secmodel><model>dac</model><baselabel type='kvm'>+107:+107</baselabel>"
        "</secmodel></host></capabilities>"
    )
    who = access.qemu_identity(caps)
    assert who is not None
    assert (who.uid, who.gid) == (107, 107)
    assert access.qemu_identity("<capabilities><host/></capabilities>") is None


def test_access_api_is_confined(iso_client: TestClient, isos: Path, tmp_path: Path) -> None:
    ok = iso_client.get(f"/api/isos/access?path={isos / 'debian-13.iso'}", headers=AUTH)
    assert ok.status_code == 200
    assert ok.json()["path"] == str(isos / "debian-13.iso")
    outside = touch(tmp_path / "etc-shadow-like")
    refused = iso_client.get(f"/api/isos/access?path={outside}", headers=AUTH)
    assert refused.status_code == 403
    sneaky = iso_client.get(f"/api/isos/access?path={isos}/../../etc-shadow-like", headers=AUTH)
    assert sneaky.status_code == 403


# CD/DVD media


@pytest.fixture
def cd_vm(conn: LibvirtConnection) -> Any:
    xml = (
        f"<domain type='test'><name>cd-{uuidlib.uuid4().hex[:6]}</name><memory>65536</memory>"
        "<os><type>hvm</type></os><devices>"
        "<disk type='file' device='cdrom'><target dev='sda' bus='sata'/><readonly/></disk>"
        "</devices></domain>"
    )
    dom = conn.run(lambda c: c.defineXML(xml))
    yield dom
    dom.undefine()


def test_change_and_eject_media(iso_client: TestClient, cd_vm: Any, isos: Path) -> None:
    uuid = cd_vm.UUIDString()
    drives = iso_client.get(f"/api/vms/{uuid}/cdroms", headers=AUTH).json()
    assert drives == [{"target": "sda", "bus": "sata", "path": None}]
    iso = str(isos / "debian-13.iso")
    response = iso_client.put(f"/api/vms/{uuid}/cdroms/sda", headers=AUTH, json={"path": iso})
    assert response.status_code == 204
    assert iso in cd_vm.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)
    iso_client.put(f"/api/vms/{uuid}/cdroms/sda", headers=AUTH, json={"path": None})
    assert iso_client.get(f"/api/vms/{uuid}/cdroms", headers=AUTH).json()[0]["path"] is None


def test_media_must_come_from_a_library(iso_client: TestClient, cd_vm: Any, tmp_path: Path) -> None:
    uuid = cd_vm.UUIDString()
    outside = touch(tmp_path / "rogue.iso")
    response = iso_client.put(
        f"/api/vms/{uuid}/cdroms/sda", headers=AUTH, json={"path": str(outside)}
    )
    assert response.status_code == 403
    missing = iso_client.put(f"/api/vms/{uuid}/cdroms/sdz", headers=AUTH, json={"path": None})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "vm.no_cdrom"


# Fix button: backend -> helper socket -> (simulated) setfacl


@pytest.fixture
def helper_socket(
    isos: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[list[list[str]]]:
    from kvmstudio_helper import server
    from kvmstudio_helper.config import HelperConfig
    from kvmstudio_helper.config import IsoLibrary as HelperLibrary

    ran: list[list[str]] = []
    real = server.handle
    monkeypatch.setattr(
        server,
        "handle",
        lambda raw, peer, cfg: real(
            raw, peer, cfg, authorizer=lambda a, p: True, runner=lambda argv, fds: ran.append(argv)
        ),
    )
    config = HelperConfig(tmp_path / "helper.sock", 107, (HelperLibrary(isos, (".iso",)),))
    monkeypatch.setenv("KVMSTUDIO_HELPER_SOCKET", str(config.socket))
    srv = server.HelperServer(config)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield ran
    srv.shutdown()
    srv.server_close()


def test_fix_access_goes_through_the_helper(
    iso_client: TestClient, isos: Path, helper_socket: list[list[str]]
) -> None:
    r = iso_client.post(
        "/api/isos/access/fix", json={"path": str(isos / "debian-13.iso")}, headers=AUTH
    )
    assert r.status_code == 200
    assert r.json()["path"] == str(isos / "debian-13.iso")
    assert [argv[:3] for argv in helper_socket] == [
        ["setfacl", "-m", "u:107:x"],
        ["setfacl", "-m", "u:107:r"],
    ]


def test_fix_access_refusals(
    iso_client: TestClient, isos: Path, tmp_path: Path, helper_socket: list[list[str]]
) -> None:
    outside = touch(tmp_path / "outside.iso")
    r = iso_client.post("/api/isos/access/fix", json={"path": str(outside)}, headers=AUTH)
    assert r.status_code == 403
    # Declared in config.toml but the helper only accepts .iso here.
    img = isos / "Firewalls" / "OPNsense" / "opnsense-25.7.img"
    r = iso_client.post("/api/isos/access/fix", json={"path": str(img)}, headers=AUTH)
    assert (r.status_code, r.json()["error"]["code"]) == (403, "helper.path_not_allowed")
    assert helper_socket == []


def test_fix_access_without_helper(
    iso_client: TestClient, isos: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KVMSTUDIO_HELPER_SOCKET", str(tmp_path / "none.sock"))
    r = iso_client.post(
        "/api/isos/access/fix", json={"path": str(isos / "debian-13.iso")}, headers=AUTH
    )
    assert (r.status_code, r.json()["error"]["code"]) == (503, "helper.unavailable")


def test_own_parent_folders_get_search_access(tmp_path: Path) -> None:
    if shutil.which("setfacl") is None:
        pytest.skip("needs setfacl")
    home = tmp_path / "home"
    library = home / "iso"
    iso = touch(library / "x.iso")
    home.chmod(0o700)
    who = access.Identity(65534, 65534, frozenset({65534}), "nobody")
    report = access.check(str(iso), who, selinux=False)
    assert ("no_search", str(home)) in report.problems
    done = access.grant_search_on_own_folders(report, who)
    assert str(home) in done
    assert access.allowed(home, who, access.X)
