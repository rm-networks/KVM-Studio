from __future__ import annotations


class HelperError(Exception):
    """A refusal sent back to the client as {"ok": false, "error": code}."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
