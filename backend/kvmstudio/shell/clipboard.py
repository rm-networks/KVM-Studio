"""Host clipboard for the desktop window, exposed to the page through pywebview.

The embedded web engine does not grant the page access to the system clipboard,
so the frontend calls window.pywebview.api.read_clipboard() / write_clipboard().
pywebview runs those calls in worker threads, while toolkit clipboards must be
used from the GUI thread: each backend hops to it and waits for the result.
"""

from __future__ import annotations

import importlib
import threading
import webbrowser
from collections.abc import Callable
from typing import Any, Literal, Protocol

CLIPBOARD_TIMEOUT = 5.0


class HostClipboard(Protocol):
    def read(self) -> str: ...
    def write(self, text: str) -> None: ...


class DesktopApi:
    """Object handed to pywebview as js_api: every public method is callable from JS."""

    def __init__(self, clipboard: HostClipboard) -> None:
        self._clipboard = clipboard
        self._window: Any = None
        # pywebview only toggles: remember the state to set it.
        self._fullscreen = False
        # The page asks what to do with running VMs before the window closes.
        self._close_guarded = False
        self._close_allowed = False
        self._close_pending = False

    def _attach(self, window: Any) -> None:
        self._window = window

    def toggle_fullscreen(self) -> None:
        """The page's own Fullscreen API is not honoured by the embedded engine."""
        if self._window is not None:
            self._window.toggle_fullscreen()
            self._fullscreen = not self._fullscreen

    def set_fullscreen(self, on: bool) -> bool:
        """Full screen on or off for the console; returns the state before."""
        before = self._fullscreen
        if isinstance(on, bool) and on != before:
            self.toggle_fullscreen()
        return before

    def close_window(self) -> None:
        """Close for good (the uninstall assistant, Quit, or after the reminder)."""
        self._close_allowed = True
        if self._window is not None:
            self._window.destroy()

    def guard_close(self, on: bool) -> None:
        """The page handles closing requests itself (running VMs reminder)."""
        self._close_guarded = bool(on)

    def close_answered(self) -> None:
        """The page got the closing request: a second one is not a stuck page."""
        self._close_pending = False

    def _on_closing(self) -> bool:
        """pywebview closing event: False keeps the window open for the page to ask."""
        if self._close_allowed or not self._close_guarded or self._window is None:
            return True
        if self._close_pending:
            # The page never answered the previous request: do not trap the user.
            return True
        self._close_pending = True
        window = self._window
        threading.Thread(
            target=lambda: window.evaluate_js("window.dispatchEvent(new Event('kvmstudio:close'))"),
            daemon=True,
        ).start()
        return False

    def choose_folder(self, start: str | None = None) -> str | None:
        """Native folder picker (Preferences, ISO libraries)."""
        if self._window is None:
            return None
        import webview

        kind = getattr(webview, "FileDialog", None)
        folder_kind = kind.FOLDER if kind is not None else webview.FOLDER_DIALOG
        result = self._window.create_file_dialog(folder_kind, directory=start or "")
        return str(result[0]) if result else None

    def open_link(self, url: str) -> None:
        """A help link, in the default browser (the window never leaves the app)."""
        if isinstance(url, str) and url.startswith("https://"):
            webbrowser.open(url)

    def read_clipboard(self) -> str:
        return self._clipboard.read()

    def write_clipboard(self, text: str) -> None:
        if isinstance(text, str):
            self._clipboard.write(text)


def _qt_clipboard() -> HostClipboard:
    # Imported by name: Qt is optional and its stubs differ between machines.
    core = importlib.import_module("qtpy.QtCore")
    widgets = importlib.import_module("qtpy.QtWidgets")

    base: Any = core.QObject

    class Bridge(base):  # type: ignore[misc]
        @core.Slot(result=str)  # type: ignore[untyped-decorator]
        def read(self) -> str:
            return str(widgets.QApplication.clipboard().text())

        @core.Slot(str)  # type: ignore[untyped-decorator]
        def write(self, text: str) -> None:
            widgets.QApplication.clipboard().setText(text)

    # Created here, in the main thread, which is where pywebview runs the Qt loop.
    bridge = Bridge()
    blocking = core.Qt.ConnectionType.BlockingQueuedConnection

    def in_gui_thread() -> bool:
        return bool(core.QThread.currentThread() is bridge.thread())

    class QtClipboard:
        def read(self) -> str:
            if in_gui_thread():
                return str(bridge.read())
            return str(
                core.QMetaObject.invokeMethod(bridge, "read", blocking, core.Q_RETURN_ARG(str))
            )

        def write(self, text: str) -> None:
            if in_gui_thread():
                bridge.write(text)
            else:
                core.QMetaObject.invokeMethod(bridge, "write", blocking, core.Q_ARG(str, text))

    return QtClipboard()


def _gtk_clipboard() -> HostClipboard:
    repo = importlib.import_module("gi.repository")
    Gdk, GLib, Gtk = repo.Gdk, repo.GLib, repo.Gtk

    def in_gui_thread(fn: Callable[[], str]) -> str:
        result: list[str] = []
        done = threading.Event()

        def run() -> bool:
            try:
                result.append(fn())
            finally:
                done.set()
            return False

        GLib.idle_add(run)
        done.wait(CLIPBOARD_TIMEOUT)
        return result[0] if result else ""

    def board() -> Any:
        return Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

    class GtkClipboard:
        def read(self) -> str:
            return in_gui_thread(lambda: board().wait_for_text() or "")

        def write(self, text: str) -> None:
            def set_text() -> str:
                board().set_text(text, -1)
                board().store()
                return ""

            in_gui_thread(set_text)

    return GtkClipboard()


def make_clipboard(gui: Literal["qt", "gtk"]) -> HostClipboard:
    return _qt_clipboard() if gui == "qt" else _gtk_clipboard()
