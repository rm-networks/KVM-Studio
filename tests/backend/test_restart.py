from __future__ import annotations

import http.client
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kvmstudio.app import create_app
from kvmstudio.config import Config, load_config
from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.shell import tray
from kvmstudio.shell.backend_process import BackendProcess
from kvmstudio.shell.restart import RESTART_EXIT, restart_argv
from kvmstudio.shell.web import switch_to_desktop

from .conftest import TOKEN
from .helpers import AUTH


def test_restart_argv_drops_the_mode() -> None:
    assert restart_argv(["--mode", "desktop", "--config", "/x.toml"]) == ["--config", "/x.toml"]
    assert restart_argv(["--mode=web", "--no-browser"]) == ["--no-browser"]
    assert restart_argv([]) == []


def test_restart_without_a_shell_is_refused(
    config: Config, conn: LibvirtConnection, frontend_dir: Path
) -> None:
    app = create_app(config, conn, TOKEN, mode="web", frontend_dir=frontend_dir)
    response = TestClient(app, base_url="http://127.0.0.1").post("/api/restart", headers=AUTH)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "restart.unavailable"


def test_restart_calls_the_shell(
    config: Config, conn: LibvirtConnection, frontend_dir: Path
) -> None:
    calls: list[bool] = []
    app = create_app(
        config,
        conn,
        TOKEN,
        mode="web",
        frontend_dir=frontend_dir,
        on_restart=lambda: calls.append(True),
    )
    response = TestClient(app, base_url="http://127.0.0.1").post("/api/restart", headers=AUTH)
    assert response.status_code == 202
    assert calls == [True]


def test_backend_child_exits_with_the_restart_status(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[libvirt]\nuri = "test:///default"\n')
    backend = BackendProcess(config, "web", "tok")
    port = backend.start()
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    client.request("POST", "/api/restart", headers={"Authorization": "Bearer tok"})
    assert client.getresponse().status == 202
    deadline = time.monotonic() + 10
    while backend.alive() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert backend.returncode == RESTART_EXIT
    assert backend.wants_restart()
    backend.stop()


def test_switch_to_desktop_saves_the_mode(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[interface]\nmode = "web"\n[ui]\nlanguage = "en"\n')
    switch_to_desktop(config)
    # Desktop is the default: the key leaves the file.
    assert 'mode = "web"' not in config.read_text()
    loaded = load_config(config)
    assert loaded.interface.mode == "desktop"
    assert loaded.ui.language == "en"


def test_tray_falls_back_without_a_display(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert tray.run_tray("http://127.0.0.1:60080/#token=x", None, "fr", lambda: True) is None


def test_tray_falls_back_without_a_notification_area(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("PyQt6.QtWidgets")
    monkeypatch.setenv("DISPLAY", os.environ.get("DISPLAY", ":0"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")  # no system tray there
    assert tray.run_tray("http://127.0.0.1:60080/#token=x", None, "fr", lambda: True) is None


def test_tray_labels() -> None:
    assert tray.labels("fr")["desktop"] == "Passer en mode fenêtre"
    assert tray.labels("de") == tray.labels("en")
