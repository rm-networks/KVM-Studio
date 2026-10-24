"""The desktop window starts, loads the page and closes, without crashing.

Runs headless (QT_QPA_PLATFORM=offscreen). Skipped where Qt WebEngine is missing.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


pytestmark = pytest.mark.skipif(
    not (_has("qtpy") and _has("PyQt6.QtWebEngineWidgets")), reason="needs Qt WebEngine"
)


def test_desktop_mode_starts_headless(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[libvirt]\nuri = "test:///default"\n')
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "KVMSTUDIO_SMOKE_SECONDS": "1",
        # Chromium refuses to sandbox as root (CI containers).
        "QTWEBENGINE_CHROMIUM_FLAGS": "--no-sandbox --disable-gpu",
    }
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "kvmstudio", "--mode", "desktop", "--config", str(config)],
        capture_output=True,
        text=True,
        env=env,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "SMOKE loaded" in result.stdout


def test_backend_process_reports_its_port(tmp_path: Path) -> None:
    from kvmstudio.shell.backend_process import BackendProcess

    config = tmp_path / "config.toml"
    config.write_text('[libvirt]\nuri = "test:///default"\n')
    backend = BackendProcess(config, "desktop", "tok")
    port = backend.start()
    try:
        assert port > 0
        assert backend.alive()
    finally:
        backend.stop()
    assert not backend.alive()
