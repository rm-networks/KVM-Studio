"""Folders and disk images, for the Browse buttons of a web browser.

A browser cannot hand a path to the page: the backend lists the folders
instead. The owner sees the whole computer, as a file dialog would; a guest
of LAN sharing only the library and the ISO libraries (F-102).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..config import Config
from ..errors import ApiException
from ..paths import in_iso_library, in_library, iso_roots, library_root, resolve

DISK_SUFFIXES = (".qcow2", ".raw", ".img")
MAX_ENTRIES = 2000

Kind = Literal["disk", "folder"]


@dataclass(frozen=True, slots=True)
class Entry:
    name: str
    path: str
    folder: bool
    size: int


@dataclass(slots=True)
class Listing:
    path: str
    parent: str | None
    entries: list[Entry] = field(default_factory=list)
    places: list[tuple[str, str]] = field(default_factory=list)
    truncated: bool = False


def _places(config: Config, confined: bool) -> list[tuple[str, str]]:
    places: list[tuple[str, str]] = []
    if not confined:
        places.append(("home", str(Path.home())))
    root = library_root(config)
    if root is not None and root.is_dir():
        places.append(("library", str(resolve(root))))
    places += [("iso", str(resolve(p))) for p in iso_roots(config) if p.is_dir()]
    return places


def _allowed(path: Path, config: Config, confined: bool) -> bool:
    if not confined:
        return True
    root = library_root(config)
    tops = [resolve(root)] if root is not None else []
    tops += [resolve(p) for p in iso_roots(config)]
    return path in tops or in_library(path, config) or in_iso_library(path, config)


def listing(config: Config, path: str | None, kind: Kind, *, confined: bool) -> Listing:
    places = _places(config, confined)
    if not path:
        path = places[0][1] if places else "/"
    if not os.path.isabs(path):
        raise ApiException(422, "files.not_absolute", f"{path} is not an absolute path")
    here = resolve(path)
    if not _allowed(here, config, confined):
        raise ApiException(403, "path.not_allowed", f"{path} is outside the library")
    if not here.is_dir():
        raise ApiException(404, "files.no_folder", f"{path} is not a folder")
    parent = here.parent if here.parent != here else None
    if parent is not None and not _allowed(parent, config, confined):
        parent = None
    result = Listing(str(here), str(parent) if parent else None, places=places)
    try:
        children = sorted(os.scandir(here), key=lambda e: e.name.casefold())
    except OSError as exc:
        raise ApiException(403, "files.unreadable", f"Cannot read {here}: {exc.strerror}") from exc
    for child in children:
        if child.name.startswith("."):
            continue
        try:
            is_dir = child.is_dir()
            is_disk = (
                kind == "disk" and child.is_file() and child.name.lower().endswith(DISK_SUFFIXES)
            )
            size = child.stat().st_size if is_disk else 0
        except OSError:
            continue
        if is_dir or is_disk:
            if len(result.entries) >= MAX_ENTRIES:
                result.truncated = True
                break
            result.entries.append(Entry(child.name, str(here / child.name), is_dir, size))
    return result
