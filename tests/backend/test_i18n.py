from __future__ import annotations

import ast
import json
import re
import string
from pathlib import Path

import pytest

from kvmstudio import APP_NAME, i18n

LOCALE = Path(i18n.__file__).parent / "locale"
ROOT = Path(__file__).resolve().parents[2]


def _fields(message: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(message) if f}


def test_both_catalogs_have_the_same_keys_and_fields() -> None:
    en = json.loads((LOCALE / "en.json").read_text())
    fr = json.loads((LOCALE / "fr.json").read_text())
    assert set(en) == set(fr)
    for key in en:
        assert _fields(en[key]) == _fields(fr[key]), key


def test_the_product_name_is_never_translated() -> None:
    for path in LOCALE.glob("*.json"):
        assert APP_NAME not in path.read_text(), path


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"LANG": "fr_FR.UTF-8"}, "fr"),
        ({"LANG": "en_US.UTF-8"}, "en"),
        ({"LANG": "de_DE.UTF-8"}, "en"),
        ({"LC_ALL": "fr_CA.UTF-8", "LANG": "en_US.UTF-8"}, "fr"),
        ({"LANG": "C.UTF-8"}, "en"),
        ({}, "en"),
    ],
)
def test_system_language(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected: str
) -> None:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    assert i18n.resolve("system") == expected
    assert i18n.resolve("fr") == "fr"
    assert i18n.resolve("en") == "en"


def test_messages_carry_the_product_name() -> None:
    assert i18n.t("uninstall.title", "fr") == f"Désinstaller {APP_NAME}"
    assert i18n.t("uninstall.title", "en") == f"Uninstall {APP_NAME}"


def test_every_key_used_in_the_backend_exists() -> None:
    en = json.loads((LOCALE / "en.json").read_text())
    used = set()
    for path in (ROOT / "backend" / "kvmstudio").rglob("*.py"):
        used |= set(re.findall(r"""\bt\(\s*["']([a-z_]+\.[a-z_]+)["']""", path.read_text()))
    assert used, "no translated message found"
    assert used <= set(en), used - set(en)


def _literal_text(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    return None


# Lines read by programs, not people: the smoke test and the backend child process.
INTERNAL = {"SMOKE loaded ", " is not set"}


def test_messages_shown_to_the_user_come_from_the_catalog() -> None:
    """print(), out() and argparse help= never carry words of their own."""
    problems = []
    for path in (ROOT / "backend" / "kvmstudio").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            args = list(node.args[:1]) if name in ("print", "out", "ask") else []
            args += [k.value for k in node.keywords if k.arg == "help"]
            for arg in args:
                text = _literal_text(arg)
                if text and text not in INTERNAL and re.search(r"[A-Za-z]{3,}", text):
                    problems.append(f"{path.relative_to(ROOT)}:{node.lineno} {text!r}")
    assert problems == []
