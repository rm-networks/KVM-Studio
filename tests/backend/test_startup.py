"""Startup errors shown in a window when the program has no terminal."""

from __future__ import annotations

import io
import sys

import pytest

from kvmstudio import cli, startup


class NoTerminal(io.StringIO):
    def isatty(self) -> bool:
        return False


@pytest.fixture
def shown(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.setattr(sys, "stderr", NoTerminal())
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    got: list[str] = []
    monkeypatch.setattr(startup, "show_error", got.append)
    return got


def test_a_failed_start_shows_its_messages(
    shown: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fails() -> int:
        print("the backend did not start", file=sys.stderr)
        return 1

    monkeypatch.setattr(cli, "main", fails)
    assert startup.run() == 1
    assert shown == ["the backend did not start"]


def test_an_import_error_shows_the_traceback(
    shown: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> int:
        raise ImportError("cannot import name 'InvalidHashError'")

    monkeypatch.setattr(cli, "main", broken)
    assert startup.run() == 1
    assert "InvalidHashError" in shown[0]
    assert shown[0].startswith("Traceback")


def test_a_normal_exit_shows_nothing(shown: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    def warns() -> int:
        print("a warning only", file=sys.stderr)
        return 0

    monkeypatch.setattr(cli, "main", warns)
    assert startup.run() == 0
    assert shown == []


def test_with_a_terminal_the_messages_stay_there(
    shown: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(startup, "_has_terminal", lambda: True)
    monkeypatch.setattr(cli, "main", lambda: 1)
    assert startup.run() == 1
    assert shown == []
