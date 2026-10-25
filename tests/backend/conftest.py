from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import libvirt
import pytest
from fastapi.testclient import TestClient

from kvmstudio import i18n
from kvmstudio.app import create_app
from kvmstudio.config import Config, IsoLibrary, LibvirtSettings, StorageSettings
from kvmstudio.libvirt_conn import LibvirtConnection

TEST_URI = "test:///default"
TOKEN = "test-token"


@pytest.fixture(autouse=True)
def english_desktop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Messages in the source language, whatever the machine running the tests."""
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    i18n._current.clear()


@pytest.fixture
def config() -> Config:
    return Config(libvirt=LibvirtSettings(uri=TEST_URI))


@pytest.fixture
def conn() -> Iterator[LibvirtConnection]:
    c = LibvirtConnection(TEST_URI)
    yield c
    c.close()


@pytest.fixture
def frontend_dir(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<!doctype html><title>KVM Studio</title>")
    return tmp_path


@pytest.fixture
def client(config: Config, conn: LibvirtConnection, frontend_dir: Path) -> TestClient:
    app = create_app(config, conn, TOKEN, mode="web", frontend_dir=frontend_dir)
    return TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "data" / "KVM-Studio" / "VM"
    root.mkdir(parents=True)
    return root


@pytest.fixture
def lib_config(tmp_path: Path, library: Path) -> Config:
    iso = tmp_path / "iso"
    iso.mkdir()
    return Config(
        libvirt=LibvirtSettings(uri=TEST_URI),
        storage=StorageSettings(vm_default_location=tmp_path / "data"),
        iso_libraries=[IsoLibrary(name="ISO", path=iso)],
    )


@pytest.fixture
def lib_client(lib_config: Config, conn: LibvirtConnection, frontend_dir: Path) -> TestClient:
    app = create_app(lib_config, conn, TOKEN, mode="web", frontend_dir=frontend_dir)
    return TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture
def define(conn: LibvirtConnection) -> Iterator[list[libvirt.virDomain]]:
    created: list[libvirt.virDomain] = []
    yield created
    for dom in created:
        try:
            if dom.isActive():
                dom.destroy()
            dom.undefine()
        except libvirt.libvirtError:
            pass
