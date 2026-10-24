"""ISO libraries: folders browsed read-only (rule 4). Nothing is ever written there."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..config import Config, IsoLibrary
from ..paths import is_strictly_within, resolve

MAX_DEPTH = 12  # guards against pathological trees


@dataclass(frozen=True, slots=True)
class IsoFile:
    library: str
    path: str  # absolute, resolved
    relative: str  # inside the library, with "/" separators
    size: int
    mtime: float


@dataclass(frozen=True, slots=True)
class LibraryStatus:
    name: str
    path: str
    available: bool


def _scan_library(lib: IsoLibrary) -> list[IsoFile]:
    root = resolve(lib.path)
    extensions = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in lib.extensions}
    found: list[IsoFile] = []

    def walk(folder: Path, depth: int) -> None:
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir(follow_symlinks=True):
                    if lib.recursive and depth < MAX_DEPTH:
                        target = Path(entry.path)
                        # A symlinked folder must stay inside the library.
                        if not entry.is_symlink() or is_strictly_within(target, root):
                            walk(target, depth + 1)
                    continue
                if Path(entry.name).suffix.lower() not in extensions:
                    continue
                real = resolve(entry.path)
                if not is_strictly_within(real, root):
                    continue
                stat = entry.stat(follow_symlinks=True)
            except OSError:
                continue
            found.append(
                IsoFile(
                    library=lib.name,
                    path=str(real),
                    relative=Path(entry.path).relative_to(root).as_posix(),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                )
            )

    walk(root, 0)
    return found


def scan(config: Config) -> tuple[list[LibraryStatus], list[IsoFile]]:
    statuses = []
    files: list[IsoFile] = []
    for lib in config.iso_libraries:
        available = lib.path.is_dir() and os.access(lib.path, os.R_OK | os.X_OK)
        statuses.append(LibraryStatus(lib.name, str(lib.path), available))
        if available:
            files.extend(_scan_library(lib))
    return statuses, files
