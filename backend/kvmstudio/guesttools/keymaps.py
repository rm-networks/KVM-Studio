"""Characters to Linux input key codes, for the guest's keyboard layout.

virDomainSendKey sends physical keys: what the guest types depends on its own
layout. "a" is the KEY_Q position on a French AZERTY keyboard, for instance.
"""

from __future__ import annotations

from typing import Literal

Layout = Literal["fr", "us"]

# Linux input-event-codes.h
KEY = {
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    "MINUS": 12, "EQUAL": 13, "TAB": 15,
    "Q": 16, "W": 17, "E": 18, "R": 19, "T": 20, "Y": 21, "U": 22, "I": 23, "O": 24, "P": 25,
    "LEFTBRACE": 26, "RIGHTBRACE": 27, "ENTER": 28,
    "A": 30, "S": 31, "D": 32, "F": 33, "G": 34, "H": 35, "J": 36, "K": 37, "L": 38,
    "SEMICOLON": 39, "APOSTROPHE": 40, "GRAVE": 41, "LEFTSHIFT": 42, "BACKSLASH": 43,
    "Z": 44, "X": 45, "C": 46, "V": 47, "B": 48, "N": 49, "M": 50,
    "COMMA": 51, "DOT": 52, "SLASH": 53, "SPACE": 57, "102ND": 86,
    "RIGHTALT": 100, "LEFTMETA": 125,
}  # fmt: skip

SHIFT = KEY["LEFTSHIFT"]
ALTGR = KEY["RIGHTALT"]

Stroke = tuple[int, ...]  # keys pressed together, modifiers first


def _us() -> dict[str, Stroke]:
    table: dict[str, Stroke] = {" ": (KEY["SPACE"],), "\n": (KEY["ENTER"],), "\t": (KEY["TAB"],)}
    for letter in "abcdefghijklmnopqrstuvwxyz":
        table[letter] = (KEY[letter.upper()],)
        table[letter.upper()] = (SHIFT, KEY[letter.upper()])
    shifted_digits = "!@#$%^&*()"
    for i, digit in enumerate("1234567890"):
        table[digit] = (KEY[digit],)
        table[shifted_digits[i]] = (SHIFT, KEY[digit])
    for key, plain, shifted in [
        ("MINUS", "-", "_"), ("EQUAL", "=", "+"), ("LEFTBRACE", "[", "{"),
        ("RIGHTBRACE", "]", "}"), ("SEMICOLON", ";", ":"), ("APOSTROPHE", "'", '"'),
        ("GRAVE", "`", "~"), ("BACKSLASH", "\\", "|"), ("COMMA", ",", "<"),
        ("DOT", ".", ">"), ("SLASH", "/", "?"),
    ]:  # fmt: skip
        table[plain] = (KEY[key],)
        table[shifted] = (SHIFT, KEY[key])
    return table


def _fr() -> dict[str, Stroke]:
    table: dict[str, Stroke] = {" ": (KEY["SPACE"],), "\n": (KEY["ENTER"],), "\t": (KEY["TAB"],)}
    # AZERTY letters: physical key under each letter.
    moved = {"a": "Q", "z": "W", "q": "A", "w": "Z", "m": "SEMICOLON"}
    for letter in "abcdefghijklmnopqrstuvwxyz":
        code = KEY[moved.get(letter, letter.upper())]
        table[letter] = (code,)
        table[letter.upper()] = (SHIFT, code)
    # Number row: symbols unshifted, digits with Shift, more with AltGr.
    for digit, plain, altgr in [
        ("1", "&", None), ("2", "é", "~"), ("3", '"', "#"), ("4", "'", "{"),
        ("5", "(", "["), ("6", "-", "|"), ("7", "è", "`"), ("8", "_", "\\"),
        ("9", "ç", "^"), ("0", "à", "@"),
    ]:  # fmt: skip
        table[plain] = (KEY[digit],)
        table[digit] = (SHIFT, KEY[digit])
        if altgr:
            table[altgr] = (ALTGR, KEY[digit])
    for key, plain, shifted, altgr in [
        ("MINUS", ")", "°", "]"), ("EQUAL", "=", "+", "}"), ("RIGHTBRACE", "$", "£", "¤"),
        ("APOSTROPHE", "ù", "%", None), ("BACKSLASH", "*", "µ", None),
        ("102ND", "<", ">", None), ("M", ",", "?", None), ("COMMA", ";", ".", None),
        ("DOT", ":", "/", None), ("SLASH", "!", "§", None),
    ]:  # fmt: skip
        table[plain] = (KEY[key],)
        table[shifted] = (SHIFT, KEY[key])
        if altgr:
            table[altgr] = (ALTGR, KEY[key])
    return table


TABLES: dict[Layout, dict[str, Stroke]] = {"us": _us(), "fr": _fr()}


class UnsupportedCharacter(ValueError):
    pass


def strokes(text: str, layout: Layout) -> list[Stroke]:
    table = TABLES[layout]
    missing = sorted({c for c in text if c not in table})
    if missing:
        raise UnsupportedCharacter(f"cannot type {''.join(missing)!r} with the {layout} layout")
    return [table[c] for c in text]
