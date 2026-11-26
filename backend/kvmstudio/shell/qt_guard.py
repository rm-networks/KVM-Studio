"""Keep the Qt processes alive when a slot raises.

PyQt aborts the process on an exception left unhandled in a slot, unless
sys.excepthook was replaced. The hook installed here writes the traceback to
the log and shows a short message; the icon or the window stays open.
"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from types import TracebackType
from typing import Any

from ..i18n import Language, t

log = logging.getLogger(__name__)

Hook = Callable[[type[BaseException], BaseException, TracebackType | None], None]


def make_hook(widgets: Any, lang: Language) -> Hook:
    showing = threading.Lock()

    def hook(kind: type[BaseException], error: BaseException, trace: TracebackType | None) -> None:
        if issubclass(kind, KeyboardInterrupt):
            sys.__excepthook__(kind, error, trace)
            return
        log.error("unhandled error in the interface", exc_info=(kind, error, trace))
        # Only on the Qt thread, and one message at a time.
        app = widgets.QApplication.instance()
        if app is None or threading.current_thread() is not threading.main_thread():
            return
        if not showing.acquire(blocking=False):
            return
        try:
            box = widgets.QMessageBox
            dialog = box(box.Icon.Warning, t("error.title", lang), t("error.text", lang))
            dialog.setDetailedText(f"{kind.__name__}: {error}")
            dialog.exec()
        except Exception:  # the message itself must never abort
            log.exception("could not show the error message")
        finally:
            showing.release()

    return hook


def install(widgets: Any, lang: Language) -> None:
    sys.excepthook = make_hook(widgets, lang)
