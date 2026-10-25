"""Display order of the library folders, kept in a small state file of KVM Studio.

The order is a preference of the user, not something on disk: folders stay
real folders with their names, and the file only lists, for each parent, the
names in the order chosen by drag and drop. Names it does not know come after,
by name.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

_lock = threading.Lock()
MAX_ENTRIES = 2000


def state_dir() -> Path:
    # The XDG spec says relative values must be ignored.
    xdg = os.environ.get("XDG_STATE_HOME", "")
    base = Path(xdg) if os.path.isabs(xdg) else Path.home() / ".local" / "state"
    return base / "kvm-studio"


def order_path() -> Path:
    return state_dir() / "library-order.json"


def load() -> dict[str, list[str]]:
    try:
        data = json.loads(order_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(parent): [str(n) for n in names if isinstance(n, str)]
        for parent, names in data.items()
        if isinstance(names, list)
    }


def _save(order: dict[str, list[str]]) -> None:
    path = order_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    kept = dict(list(order.items())[:MAX_ENTRIES])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def set_order(parent: str, names: list[str]) -> None:
    with _lock:
        order = load()
        order[parent] = list(dict.fromkeys(names))
        _save(order)


def place(parent: str, name: str, before: str | None) -> None:
    """Put name in parent's order, before another name or last."""
    with _lock:
        order = load()
        names = [n for n in order.get(parent, []) if n != name]
        index = names.index(before) if before in names else len(names)
        names.insert(index, name)
        order[parent] = names
        _save(order)


def moved(old: str, new: str) -> None:
    """A folder was renamed or moved: carry its own entries and those below it."""
    with _lock:
        order = load()
        if not order:
            return
        old_parent, _, old_name = old.rpartition("/")
        new_parent, _, new_name = new.rpartition("/")
        if old_parent == new_parent and old_name in order.get(old_parent, []):
            order[old_parent] = [new_name if n == old_name else n for n in order[old_parent]]
        elif old_name in order.get(old_parent, []):
            order[old_parent] = [n for n in order[old_parent] if n != old_name]
        rekeyed: dict[str, list[str]] = {}
        for parent, names in order.items():
            if parent == old or parent.startswith(old + "/"):
                rekeyed[new + parent[len(old) :]] = names
            else:
                rekeyed[parent] = names
        _save(rekeyed)
