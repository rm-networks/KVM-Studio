"""The helper's own record, in /var/lib/kvm-studio (root only).

- the ISO libraries users declared from Preferences, with their owner;
- every ACL entry the helper added for QEMU, so that removing a library takes
  away exactly those and never one that was there before.

helper.toml stays the administrator's file: its libraries are read with these
ones, the same folder counting once.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from .config import DEFAULT_EXTENSIONS, HelperConfig, IsoLibrary, merge_libraries
from .errors import HelperError

VERSION = 1

Bit = Literal["r", "x"]


@dataclass(frozen=True, slots=True)
class UserLibrary:
    path: str
    owner: int


@dataclass(frozen=True, slots=True)
class AclEntry:
    """u:<uid>:<bit> added by the helper on this inode."""

    path: str
    dev: int
    ino: int
    uid: int
    bit: Bit
    # No entry for that uid existed before: removing the bit removes the entry.
    created: bool
    # The file had no named entry at all: once ours is gone, no ACL is left either.
    bare: bool = False


@dataclass(slots=True)
class State:
    libraries: list[UserLibrary] = field(default_factory=list)
    acl: list[AclEntry] = field(default_factory=list)

    def user_library(self, path: Path) -> UserLibrary | None:
        return next((lib for lib in self.libraries if Path(lib.path) == path), None)

    def record(self, entry: AclEntry) -> None:
        if not any(
            (e.dev, e.ino, e.uid, e.bit) == (entry.dev, entry.ino, entry.uid, entry.bit)
            for e in self.acl
        ):
            self.acl.append(entry)


def _parse(data: object) -> State:
    if not isinstance(data, dict) or data.get("version") != VERSION:
        raise HelperError("failed", "unreadable helper state")
    try:
        return State(
            [UserLibrary(str(x["path"]), int(x["owner"])) for x in data.get("libraries", [])],
            [
                AclEntry(
                    str(x["path"]),
                    int(x["dev"]),
                    int(x["ino"]),
                    int(x["uid"]),
                    "r" if x["bit"] == "r" else "x",
                    bool(x["created"]),
                    bool(x.get("bare", False)),
                )
                for x in data.get("acl", [])
            ],
        )
    except (KeyError, TypeError, ValueError):
        raise HelperError("failed", "unreadable helper state") from None


_lock = threading.Lock()


def load(path: Path) -> State:
    try:
        text = path.read_text()
    except FileNotFoundError:
        return State()
    except OSError as exc:
        raise HelperError("failed", f"cannot read {path}: {exc}") from None
    try:
        return _parse(json.loads(text))
    except ValueError:
        raise HelperError("failed", "unreadable helper state") from None


def save(path: Path, state: State) -> None:
    data: dict[str, Any] = {"version": VERSION, **asdict(state)}
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


@contextmanager
def editing(path: Path) -> Iterator[State]:
    """The state, saved on exit unless an error went through. One request at a time."""
    with _lock:
        current = load(path)
        yield current
        save(path, current)


def libraries(config: HelperConfig, state: State | None = None) -> tuple[IsoLibrary, ...]:
    """helper.toml libraries, then the declared ones; the same folder counts once."""
    current = state if state is not None else load(config.state)
    declared = [
        IsoLibrary(Path(lib.path), DEFAULT_EXTENSIONS, lib.owner) for lib in current.libraries
    ]
    return merge_libraries([*config.iso_libraries, *declared])
