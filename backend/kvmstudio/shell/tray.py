"""Notification area icon for web mode, so one can tell KVM Studio is running.

Qt shows it as a StatusNotifierItem on KDE (and on GNOME with the AppIndicator
extension). Where the desktop shows no such icons, or Qt is missing, run_tray()
returns None and the caller keeps running without it.
"""

from __future__ import annotations

import importlib
import os
import signal
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

Outcome = Literal["quit", "desktop", "backend_exited"]

LABELS: dict[str, dict[str, str]] = {
    "fr": {
        "open": "Ouvrir dans le navigateur",
        "copy": "Copier l'adresse",
        "desktop": "Passer en mode fenêtre",
        "quit": "Quitter",
        "tooltip": "KVM Studio (mode web) : {url}",
    },
    "en": {
        "open": "Open in the Browser",
        "copy": "Copy the Address",
        "desktop": "Switch to Window Mode",
        "quit": "Quit",
        "tooltip": "KVM Studio (web mode): {url}",
    },
}


def labels(language: str) -> dict[str, str]:
    return LABELS.get(language, LABELS["en"])


def _has_display() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def run_tray(
    url: str,
    icon: Path | None,
    language: str,
    backend_alive: Callable[[], bool],
) -> Outcome | None:
    """Show the icon and block until the user quits; None if no tray is available."""
    if not _has_display():
        return None
    os.environ.setdefault("QT_API", "pyqt6")
    try:
        core: Any = importlib.import_module("qtpy.QtCore")
        gui: Any = importlib.import_module("qtpy.QtGui")
        widgets: Any = importlib.import_module("qtpy.QtWidgets")
    except ImportError:
        return None

    gui.QGuiApplication.setDesktopFileName("kvm-studio")
    app = widgets.QApplication.instance() or widgets.QApplication([])
    if not widgets.QSystemTrayIcon.isSystemTrayAvailable():
        return None
    app.setQuitOnLastWindowClosed(False)
    text = labels(language)
    outcome: list[Outcome] = []

    def finish(result: Outcome) -> None:
        outcome.append(result)
        app.quit()

    tray = widgets.QSystemTrayIcon()
    if icon is not None and icon.is_file():
        tray.setIcon(gui.QIcon(str(icon)))
    tray.setToolTip(text["tooltip"].format(url=url.split("#", 1)[0]))
    menu = widgets.QMenu()
    menu.addAction(text["open"]).triggered.connect(lambda: webbrowser.open(url))
    menu.addAction(text["copy"]).triggered.connect(
        lambda: widgets.QApplication.clipboard().setText(url)
    )
    menu.addSeparator()
    menu.addAction(text["desktop"]).triggered.connect(lambda: finish("desktop"))
    menu.addAction(text["quit"]).triggered.connect(lambda: finish("quit"))
    tray.setContextMenu(menu)
    # A left click opens the page, like most tray icons.
    tray.activated.connect(
        lambda reason: (
            webbrowser.open(url)
            if reason == widgets.QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
    )
    tray.show()

    # Watch the backend, and give Python a chance to handle Ctrl+C.
    timer = core.QTimer()
    timer.timeout.connect(lambda: None if backend_alive() else finish("backend_exited"))
    timer.start(500)
    previous = signal.signal(signal.SIGINT, lambda *_: finish("quit"))
    try:
        app.exec()
    finally:
        signal.signal(signal.SIGINT, previous)
        timer.stop()
        tray.hide()
    return outcome[0] if outcome else "quit"
