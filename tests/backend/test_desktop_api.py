from __future__ import annotations

from kvmstudio.shell.clipboard import DesktopApi


class FakeClipboard:
    def __init__(self) -> None:
        self.text = ""

    def read(self) -> str:
        return self.text

    def write(self, text: str) -> None:
        self.text = text


def test_desktop_api_reads_and_writes_the_clipboard() -> None:
    board = FakeClipboard()
    api = DesktopApi(board)
    api.write_clipboard("Façade : 5 €")
    assert board.text == "Façade : 5 €"
    assert api.read_clipboard() == "Façade : 5 €"


def test_desktop_api_ignores_non_text() -> None:
    board = FakeClipboard()
    DesktopApi(board).write_clipboard(42)  # type: ignore[arg-type]
    assert board.text == ""


def test_only_clipboard_methods_are_public() -> None:
    public = [name for name in dir(DesktopApi) if not name.startswith("_")]
    assert public == ["read_clipboard", "write_clipboard"]
