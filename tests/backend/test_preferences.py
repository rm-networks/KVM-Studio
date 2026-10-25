from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kvmstudio.app import create_app
from kvmstudio.config import Config, LibvirtSettings, load_config, save_config
from kvmstudio.libvirt_conn import LibvirtConnection

from .conftest import TEST_URI, TOKEN
from .helpers import AUTH


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    return tmp_path / "config" / "config.toml"


@pytest.fixture
def prefs_client(conn: LibvirtConnection, frontend_dir: Path, config_file: Path) -> TestClient:
    config = Config(libvirt=LibvirtSettings(uri=TEST_URI))
    app = create_app(
        config, conn, TOKEN, mode="desktop", frontend_dir=frontend_dir, config_path=config_file
    )
    return TestClient(app, base_url="http://127.0.0.1")


def current(client: TestClient) -> dict[str, Any]:
    data: dict[str, Any] = client.get("/api/preferences", headers=AUTH).json()
    return data


def test_read_preferences(prefs_client: TestClient, config_file: Path) -> None:
    data = current(prefs_client)
    assert data["config_path"] == str(config_file)
    assert data["library_root"] is None
    assert data["config"]["libvirt"]["uri"] == TEST_URI
    assert data["config"]["interface"]["mode"] == "desktop"


def test_save_preferences(prefs_client: TestClient, config_file: Path, tmp_path: Path) -> None:
    location = tmp_path / "Data" / "VM"
    location.mkdir(parents=True)
    config = current(prefs_client)["config"]
    config["storage"]["vm_default_location"] = str(location)
    config["ui"]["theme"] = "dark"

    result = prefs_client.put("/api/preferences", headers=AUTH, json=config).json()
    assert result == {
        "restart_required": False,
        "library_root": str(location / "KVM-Studio" / "VM"),
    }
    assert (location / "KVM-Studio" / "VM").is_dir()
    saved = load_config(config_file)
    assert saved.ui.theme == "dark"
    assert config_file.stat().st_mode & 0o777 == 0o600
    # The running app uses the new settings right away.
    assert current(prefs_client)["config"]["ui"]["theme"] == "dark"


def test_mode_change_needs_a_restart(prefs_client: TestClient) -> None:
    config = current(prefs_client)["config"]
    config["interface"]["mode"] = "web"
    result = prefs_client.put("/api/preferences", headers=AUTH, json=config).json()
    assert result["restart_required"] is True


def _missing_location(c: dict[str, Any], t: Path) -> None:
    c["storage"]["vm_default_location"] = str(t / "missing")


def _relative_location(c: dict[str, Any], _t: Path) -> None:
    c["storage"]["vm_default_location"] = "relative/dir"


def _share(c: dict[str, Any], _t: Path) -> None:
    c["web"]["share_on_lan"] = True


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (_missing_location, "prefs.location_missing"),
        (_relative_location, "prefs.location_relative"),
        (_share, "prefs.share_later"),
    ],
)
def test_invalid_preferences(
    prefs_client: TestClient, tmp_path: Path, change: Any, code: str, config_file: Path
) -> None:
    config = current(prefs_client)["config"]
    change(config, tmp_path)
    response = prefs_client.put("/api/preferences", headers=AUTH, json=config)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert not config_file.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere (CI container)")
def test_unwritable_location_is_explained(prefs_client: TestClient, tmp_path: Path) -> None:
    location = tmp_path / "root-owned"
    location.mkdir()
    location.chmod(0o555)
    try:
        config = current(prefs_client)["config"]
        config["storage"]["vm_default_location"] = str(location)
        response = prefs_client.put("/api/preferences", headers=AUTH, json=config)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "prefs.location_not_writable"
    finally:
        location.chmod(0o755)


def test_saved_file_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    config = Config.model_validate(
        {"storage": {"vm_default_location": str(tmp_path)}, "ui": {"language": "en"}}
    )
    save_config(config, path)
    text = path.read_text()
    assert text.startswith("# KVM Studio configuration")
    assert tomllib.loads(text)["ui"]["language"] == "en"
    assert load_config(path) == config


def test_iso_libraries_are_added_one_by_one(
    prefs_client: TestClient, config_file: Path, tmp_path: Path
) -> None:
    config = current(prefs_client)["config"]
    config["iso_libraries"] = [{"name": "x", "path": str(tmp_path)}]
    response = prefs_client.put("/api/preferences", headers=AUTH, json=config)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "prefs.iso_through_helper"


def test_iso_library_without_helper_is_kept_for_browsing(
    prefs_client: TestClient, config_file: Path, tmp_path: Path
) -> None:
    iso = tmp_path / "iso"
    iso.mkdir()
    assert current(prefs_client)["iso_declared"] is None
    body = {"name": "Main ISO", "path": str(iso), "recursive": True}
    result = prefs_client.post("/api/preferences/iso-libraries", headers=AUTH, json=body).json()
    assert result["declared"] is False
    assert load_config(config_file).iso_libraries[0].path == iso
    # Renaming goes through Preferences as before.
    config = current(prefs_client)["config"]
    config["iso_libraries"][0]["name"] = "ISO"
    assert prefs_client.put("/api/preferences", headers=AUTH, json=config).status_code == 200
    assert load_config(config_file).iso_libraries[0].name == "ISO"
    removed = prefs_client.post(
        "/api/preferences/iso-libraries/remove", headers=AUTH, json={"path": str(iso)}
    ).json()
    assert removed["config"]["iso_libraries"] == []
    assert load_config(config_file).iso_libraries == []


def test_missing_iso_folder(prefs_client: TestClient, tmp_path: Path, config_file: Path) -> None:
    body = {"name": "x", "path": str(tmp_path / "none")}
    response = prefs_client.post("/api/preferences/iso-libraries", headers=AUTH, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "prefs.iso_missing"
    assert not config_file.exists()
