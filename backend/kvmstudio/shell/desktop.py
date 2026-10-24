"""Desktop mode: the frontend runs in a native pywebview window."""

from __future__ import annotations

import contextlib
import importlib.util
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Literal

from ..auth.token import new_token
from ..config import Config, default_config_path
from ..frontend import find_frontend_dir
from .backend_process import BackendError, BackendProcess
from .clipboard import DesktopApi, make_clipboard
from .restart import exec_restart

# Smoke test: close the window that many seconds after the page loaded.
SMOKE_ENV = "KVMSTUDIO_SMOKE_SECONDS"

# Must match packaging/desktop/kvm-studio.desktop: on Wayland the compositor
# takes the window icon from the desktop entry with this id.
DESKTOP_ID = "kvm-studio"


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


def _set_app_id(gui: Literal["qt", "gtk"]) -> None:
    if gui == "qt":
        from qtpy.QtGui import QGuiApplication

        QGuiApplication.setDesktopFileName(DESKTOP_ID)
    else:
        from gi.repository import GLib

        GLib.set_prgname(DESKTOP_ID)


def run(config: Config, config_path: Path | None = None, page: str | None = None) -> int:
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

    _set_app_id(gui)
    api = DesktopApi(make_clipboard(gui))
    frontend_dir = find_frontend_dir()
    icon = frontend_dir / "logo.png" if frontend_dir else None

    token = new_token()
    backend = BackendProcess(config_path or default_config_path(), "desktop", token)
    try:
        port = backend.start()
    except BackendError as exc:
        print(exc, file=sys.stderr)
        return 1
    restart = threading.Event()
    try:
        query = f"?page={page}" if page else ""
        width, height = (760, 600) if page else (1280, 800)
        window = webview.create_window(
            "KVM Studio",
            f"http://127.0.0.1:{port}/{query}#token={token}",
            width=width,
            height=height,
            min_size=(700, 520) if page else (900, 600),
            js_api=api,
        )
        if window is None:
            print("could not create the window", file=sys.stderr)
            return 1
        api._attach(window)
        if seconds := os.environ.get(SMOKE_ENV):
            _close_after_load(window, float(seconds))

        def watch_backend() -> None:
            # A restart request (mode change) ends the backend: close the window.
            while backend.alive():
                time.sleep(0.5)
            if backend.wants_restart():
                restart.set()
            with contextlib.suppress(Exception):  # already closed by the user
                window.destroy()

        threading.Thread(target=watch_backend, daemon=True).start()
        # Lets the network editor export its JSON file.
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.start(gui=gui, icon=str(icon) if icon and icon.is_file() else None)
    finally:
        backend.stop()
    if restart.is_set():
        exec_restart()
    return 0


def _close_after_load(window: Any, seconds: float) -> None:
    def on_loaded() -> None:
        title = window.evaluate_js("document.title")
        print(f"SMOKE loaded {title}", flush=True)
        threading.Timer(seconds, window.destroy).start()

    window.events.loaded += on_loaded
