"""Desktop mode: the frontend runs in a native pywebview window."""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Literal

from ..app import create_app, find_frontend_dir
from ..auth.token import new_token
from ..config import Config
from ..libvirt_conn import LibvirtConnection
from .server import BackgroundServer, bind_loopback


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _pick_gui() -> Literal["qt", "gtk"] | None:
    """Prefer Qt WebEngine, fall back to GTK WebKit."""
    os.environ.setdefault("QT_API", "pyqt6")
    if _has_module("qtpy") and _has_module("PyQt6.QtWebEngineWidgets"):
        return "qt"
    if _has_module("gi"):
        import gi

        for webkit in ("4.1", "4.0"):
            try:
                gi.require_version("WebKit2", webkit)
            except ValueError:
                continue
            return "gtk"
    return None


def run(config: Config) -> int:
    try:
        import webview
    except ImportError:
        print("pywebview is not installed. Use --mode web instead.", file=sys.stderr)
        return 1

    gui = _pick_gui()
    if gui is None:
        print(
            "No web engine found for the window. Install python3-pyqt6-webengine "
            "(or webkit2gtk4.1), or start with --mode web.",
            file=sys.stderr,
        )
        return 1

    token = new_token()
    conn = LibvirtConnection(config.libvirt.uri)
    app = create_app(config, conn, token, mode="desktop", frontend_dir=find_frontend_dir())
    server = BackgroundServer(app, bind_loopback(0))
    server.start()
    try:
        webview.create_window(
            "KVM Studio",
            f"http://127.0.0.1:{server.port}/#token={token}",
            width=1280,
            height=800,
            min_size=(900, 600),
        )
        webview.start(gui=gui)
    finally:
        server.stop()
        conn.close()
    return 0
