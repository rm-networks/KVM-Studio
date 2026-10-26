"""Messages the backend shows itself: command line, tray icon, window title.

The catalogs are locale/<language>.json, English being the source. Messages
use str.format fields; {app} is always the product name.
"""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Any, Literal

from . import APP_NAME

Language = Literal["en", "fr"]
LANGUAGES: tuple[Language, ...] = ("en", "fr")


def resolve(setting: str) -> Language:
    """A language setting as an actual language: English unless French is chosen."""
    return "fr" if setting == "fr" else "en"


@cache
def catalog(language: Language) -> dict[str, str]:
    text = files("kvmstudio").joinpath("locale", f"{language}.json").read_text("utf-8")
    data: dict[str, str] = json.loads(text)
    return data


_current: list[Language] = []


def set_language(setting: str) -> None:
    _current[:] = [resolve(setting)]


def current() -> Language:
    return _current[0] if _current else "en"


def t(key: str, language: Language | None = None, **fields: Any) -> str:
    lang = language or current()
    message = catalog(lang).get(key) or catalog("en")[key]
    return message.format(app=APP_NAME, **fields)
