"""Tray icon menu and the Qt error guard, without a desktop."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, ClassVar

import pytest

from kvmstudio import APP_NAME, i18n
from kvmstudio.config import Config
from kvmstudio.shell import session_client, tray, web


class FakeBox:
    """QMessageBox stand-in: records the texts and clicks the first button."""

    shown: ClassVar[list[tuple[str, str, str]]] = []

    class Icon:
        Information = Warning = 0

    class ButtonRole:
        AcceptRole = RejectRole = ActionRole = DestructiveRole = 0

    def __init__(self, _icon: int, title: str, text: str) -> None:
        self.title, self.text, self.info = title, text, ""
        self.buttons: list[str] = []

    def setInformativeText(self, info: str) -> None:
        self.info = info

    def addButton(self, label: str, _role: int) -> str:
        self.buttons.append(label)
        return label

    def setCheckBox(self, box: FakeCheck) -> None:
        self.check = box

    def __del__(self) -> None:
        if check := getattr(self, "check", None):
            check.owner_alive = False

    def setDefaultButton(self, _button: str) -> None:
        pass

    def exec(self) -> None:
        FakeBox.shown.append((self.title, self.text, self.info))

    def clickedButton(self) -> str:
        return self.buttons[0]


class FakeCheck:
    """Like Qt, the check box is deleted along with the dialog that owns it."""

    def __init__(self, _label: str) -> None:
        self.owner_alive = True

    def isChecked(self) -> bool:
        if not self.owner_alive:
            raise RuntimeError("wrapped C/C++ object of type QCheckBox has been deleted")
        return True


class FakeWidgets:
    QMessageBox = FakeBox
    QCheckBox = FakeCheck


class FakeClient:
    def __init__(self, policy: str) -> None:
        self.policy = policy
        self.hidden = False

    def running(self) -> list[str]:
        return ["test-vm"]

    def workspace(self) -> dict[str, Any]:
        return {"on_close": self.policy, "close_reminder": True}

    def act(self, _action: str) -> list[str]:
        return []

    def hide_reminder(self) -> None:
        self.hidden = True


@pytest.mark.parametrize("language", i18n.LANGUAGES)
@pytest.mark.parametrize("policy", ["keep", "ask"])
@pytest.mark.parametrize("reason", ["quit", "switch"])
def test_confirm_close_with_running_vms(language: i18n.Language, policy: str, reason: str) -> None:
    FakeBox.shown = []
    client: Any = FakeClient(policy)
    assert tray.confirm_close(FakeWidgets, None, client, reason, language) is True
    (_title, text, info) = FakeBox.shown[0]
    assert "test-vm" in text
    assert info == i18n.t("close.why", language)
    assert APP_NAME in info
    # "Do not show this again" is ticked by the fake: it is taken into account.
    assert client.hidden is (policy == "keep")


GUARDED = textwrap.dedent(
    """
    from PyQt6 import QtCore, QtWidgets
    from kvmstudio.shell import qt_guard

    app = QtWidgets.QApplication([])
    QtWidgets.QMessageBox.exec = lambda self: print("message:", self.text(), flush=True)
    qt_guard.install(QtWidgets, "en")

    def broken():
        raise RuntimeError("test-broken-slot")

    timer = QtCore.QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(broken)
    timer.start(0)
    QtCore.QTimer.singleShot(200, lambda: (print("still running", flush=True), app.quit()))
    app.exec()
    """
)


def test_an_error_in_a_slot_does_not_end_the_process() -> None:
    # Depending on the PyQt version, an unhandled error in a slot aborts the
    # process (qFatal); with the guard it is logged and shown instead.
    pytest.importorskip("PyQt6.QtWidgets")
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    run = subprocess.run(  # noqa: S603 (our own script)
        [sys.executable, "-c", GUARDED],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert "still running" in run.stdout
    assert "message: " + i18n.t("error.text", "en") in run.stdout
    assert "test-broken-slot" in run.stderr  # the traceback is logged


def test_the_terminal_never_shows_the_session_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    tokens: list[str] = []

    class Backend:
        def __init__(self, _path: Path, _mode: str, token: str, _port: int) -> None:
            tokens.append(token)

        def start(self) -> int:
            return 60080

        def alive(self) -> bool:
            return False

        def wants_restart(self) -> bool:
            return False

        def stop(self) -> None:
            pass

    links: list[str] = []

    def link(self: Any, purpose: str = "open") -> str:
        links.append(purpose)
        return "http://127.0.0.1:60080/#code=single-use"

    monkeypatch.setattr(web, "BackendProcess", Backend)
    monkeypatch.setattr(session_client.SessionClient, "link", link)
    monkeypatch.setattr(web, "run_tray", lambda *_: "quit")
    config = Config()
    assert web.run(config, tmp_path / "config.toml", open_browser=False, reload=False) == 0
    out = capsys.readouterr()
    assert tokens
    assert tokens[0] not in out.out + out.err
    assert "#token=" not in out.out
    assert "#code=single-use" in out.out
    assert links == ["copy"]
