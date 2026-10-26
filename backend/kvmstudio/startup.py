"""Startup errors in a window when there is no terminal to read them.

Started from the application menu, the program has nowhere visible to print:
a missing or incompatible library would make it fail in silence. Only the
standard library is imported here, so that this still works when the rest of
the package does not import.
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import TextIO

APP = "KVM Studio"
KEPT = 20_000


class _Recorder:
    """stderr as it was, plus a copy of the last messages written to it."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self.text = ""

    def write(self, text: str) -> int:
        self.text = (self.text + text)[-KEPT:]
        return self._stream.write(text)

    def flush(self) -> None:
        self._stream.flush()

    def isatty(self) -> bool:
        return False

    def __getattr__(self, name: str) -> object:
        return getattr(self._stream, name)


def _has_terminal() -> bool:
    try:
        return sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False


def _has_display() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def run() -> int:
    if _has_terminal() or not _has_display():
        from .cli import main

        return main()
    recorder = _Recorder(sys.stderr)
    sys.stderr = recorder
    code: int | str | None
    try:
        from .cli import main

        code = main()
    except SystemExit as exc:
        code = exc.code
    except Exception:
        traceback.print_exc()
        code = 1
    finally:
        sys.stderr = recorder._stream
    if code not in (0, None) and recorder.text.strip():
        show_error(recorder.text.strip())
    return code if isinstance(code, int) else 1


def _texts() -> tuple[str, str]:
    try:
        from .i18n import t

        return t("startup.failed_title"), t("startup.failed")
    except Exception:
        return f"{APP} did not start", f"{APP} did not start. The messages below say why."


def show_error(details: str) -> None:
    """A message box with the messages unfolded on demand: Qt, else GTK, else nothing."""
    title, text = _texts()
    if not _qt_box(title, text, details):
        _gtk_box(title, text, details)


def _qt_box(title: str, text: str, details: str) -> bool:
    try:
        from qtpy.QtWidgets import QApplication, QMessageBox
    except Exception:
        return False
    app = QApplication.instance() or QApplication([APP])
    box = QMessageBox(QMessageBox.Icon.Critical, title, text)
    box.setDetailedText(details)
    # The last line of a traceback or message is usually the one that tells.
    box.setInformativeText(details.splitlines()[-1][:300])
    box.exec()
    del app
    return True


def _gtk_box(title: str, text: str, details: str) -> bool:
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
    except Exception:
        return False
    dialog = Gtk.MessageDialog(
        message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE, text=title
    )
    dialog.format_secondary_text(text)
    expander = Gtk.Expander(label=details.splitlines()[-1][:300])
    view = Gtk.TextView(editable=False, monospace=True)
    view.get_buffer().set_text(details)
    scroller = Gtk.ScrolledWindow(min_content_height=200, min_content_width=520)
    scroller.add(view)
    expander.add(scroller)
    dialog.get_message_area().pack_start(expander, True, True, 0)
    dialog.show_all()
    dialog.run()
    dialog.destroy()
    return True
