"""Notification area icon for web mode, so one can tell KVM Studio is running.

Qt shows it as a StatusNotifierItem on KDE (and on GNOME with the AppIndicator
extension). Where the desktop shows no such icons, or Qt is missing, run_tray()
returns None and the caller keeps running without it.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import signal
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from .. import APP_NAME
from ..i18n import Language, resolve, t
from .session_client import SessionClient

Outcome = Literal["quit", "desktop", "backend_exited"]

# Clean shutdown: how long the guests get before offering to force.
SHUTDOWN_WAIT_S = 60


def confirm_close(
    widgets: Any, core: Any, client: SessionClient, reason: str, lang: Language
) -> bool:
    """Before quitting or switching to window mode: what about the running VMs?

    VMs are run by libvirt and QEMU and keep running, unless Preferences >
    Workspace says otherwise. Returns False when the user cancels.
    """
    try:
        names = client.running()
        workspace = client.workspace()
    except (OSError, ValueError, KeyError):
        return True  # no backend to ask: nothing to protect
    if not names:
        return True
    box = widgets.QMessageBox
    title = t("close.title_quit" if reason == "quit" else "close.title_switch", lang)
    listing = "\n".join(f"  {n}" for n in names)
    text = t("close.still_running", lang, count=len(names)) + "\n\n" + listing
    why = t("close.why", lang, app=APP_NAME)
    policy = workspace.get("on_close", "keep")

    def ask(buttons: list[tuple[str, Any]], info: str, checkbox: Any = None) -> int:
        dialog = box(box.Icon.Information, title, text)
        dialog.setInformativeText(info)
        made = [dialog.addButton(label, role) for label, role in buttons]
        if checkbox is not None:
            dialog.setCheckBox(checkbox)
        dialog.setDefaultButton(made[0])
        dialog.exec()
        clicked = dialog.clickedButton()
        return made.index(clicked) if clicked in made else len(made) - 1

    go = t("close.quit" if reason == "quit" else "close.restart", lang)
    cancel = (t("close.cancel", lang), box.ButtonRole.RejectRole)
    if policy == "keep":
        if not workspace.get("close_reminder", True):
            return True
        check = widgets.QCheckBox(t("close.dont_show", lang))
        if ask([(go, box.ButtonRole.AcceptRole), cancel], why, check) != 0:
            return False
        if check.isChecked():
            with contextlib.suppress(OSError, ValueError, KeyError):
                client.hide_reminder()
        return True
    if policy == "ask":
        choice = ask(
            [
                (t("close.keep_running", lang), box.ButtonRole.AcceptRole),
                (t("close.suspend", lang), box.ButtonRole.ActionRole),
                (t("close.shutdown", lang), box.ButtonRole.ActionRole),
                cancel,
            ],
            why,
        )
        if choice == 3:
            return False
        if choice == 0:
            return True
        policy = "suspend" if choice == 1 else "shutdown"
    try:
        left = client.act(policy)
    except (OSError, ValueError, KeyError):
        left = names
    if policy == "shutdown" and not left:
        progress = widgets.QProgressDialog(
            t("close.stopping", lang), t("close.cancel", lang), 0, SHUTDOWN_WAIT_S
        )
        progress.setWindowTitle(title)
        progress.setMinimumDuration(0)
        left = names
        for second in range(SHUTDOWN_WAIT_S):
            progress.setValue(second)
            for _ in range(10):
                core.QThread.msleep(100)
                widgets.QApplication.processEvents()
            if progress.wasCanceled():
                return False
            if second % 2 == 1:
                try:
                    left = client.running()
                except (OSError, ValueError, KeyError):
                    break
                if not left:
                    break
        progress.close()
    if not left:
        return True
    text = t("close.stuck", lang, count=len(left)) + "\n\n" + "\n".join(f"  {n}" for n in left)
    choice = ask(
        [
            (t("close.power_off", lang), box.ButtonRole.DestructiveRole),
            (t("close.leave_running", lang), box.ButtonRole.AcceptRole),
            cancel,
        ],
        t("close.power_off_warning", lang),
    )
    if choice == 2:
        return False
    if choice == 0:
        with contextlib.suppress(OSError, ValueError, KeyError):
            client.act("poweroff")
    return True


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
    # The StatusNotifierItem title the desktop shows next to the icon.
    app.setApplicationName("kvm-studio")
    app.setApplicationDisplayName(APP_NAME)
    if not widgets.QSystemTrayIcon.isSystemTrayAvailable():
        return None
    app.setQuitOnLastWindowClosed(False)
    lang = resolve(language)
    outcome: list[Outcome] = []

    def finish(result: Outcome) -> None:
        outcome.append(result)
        app.quit()

    tray = widgets.QSystemTrayIcon()
    if icon is not None and icon.is_file():
        tray.setIcon(gui.QIcon(str(icon)))
    tray.setToolTip(t("tray.tooltip", lang, url=url.split("#", 1)[0]))
    menu = widgets.QMenu()
    menu.addAction(t("tray.open", lang)).triggered.connect(lambda: webbrowser.open(url))
    menu.addAction(t("tray.copy", lang)).triggered.connect(
        lambda: widgets.QApplication.clipboard().setText(url)
    )
    menu.addSeparator()
    client = SessionClient(url)

    def leave(result: Outcome) -> None:
        reason = "quit" if result == "quit" else "switch"
        if confirm_close(widgets, core, client, reason, lang):
            finish(result)

    menu.addAction(t("tray.desktop", lang)).triggered.connect(lambda: leave("desktop"))
    menu.addAction(t("tray.quit", lang)).triggered.connect(lambda: leave("quit"))
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
