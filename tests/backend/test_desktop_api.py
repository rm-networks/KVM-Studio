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


def test_only_intended_methods_are_public() -> None:
    # pywebview exposes every public method to the page.
    public = [name for name in dir(DesktopApi) if not name.startswith("_")]
    assert public == ["choose_folder", "read_clipboard", "write_clipboard"]


def test_folder_picker_without_window() -> None:
    assert DesktopApi(FakeClipboard()).choose_folder() is None
