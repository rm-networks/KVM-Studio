"""ISO libraries are declared to the helper, then written to config.toml.

The helper checks the folder (the user's own, outside system folders) and
keeps its own list: only folders it knows can have their rights fixed. When
removing one, it takes back the ACL entries it added there. Without the
helper (running from the sources), the library is only written to config.toml.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .. import helper_client
from ..config import Config, IsoLibrary, save_config
from ..errors import ApiException

# The helper did not take part (not running, or an older one): the library
# still works for browsing.
WITHOUT_HELPER = {"helper.unavailable", "helper.unknown_operation"}
# Removing: nothing the helper knows of, config.toml only.
NOT_THE_HELPERS = WITHOUT_HELPER | {"helper.not_declared", "helper.admin_library"}


@dataclass(slots=True)
class Change:
    config: Config
    declared: bool = True
    removed_acls: list[str] = field(default_factory=list)


def _same(a: Path, b: Path) -> bool:
    return os.path.normpath(a) == os.path.normpath(b)


def declared_paths() -> list[str] | None:
    """Folders the helper may fix (helper.toml and the user's), None without helper."""
    try:
        result = helper_client.call("list_iso_libraries", {})
    except ApiException as exc:
        if exc.code in WITHOUT_HELPER:
            return None
        raise
    return [str(lib["path"]) for lib in result.get("libraries", [])]


def _save(config: Config, config_path: Path | None) -> None:
    if config_path is not None:
        save_config(config, config_path)


def add(config: Config, config_path: Path | None, name: str, path: Path, recursive: bool) -> Change:
    if not path.is_absolute() or not path.is_dir():
        raise ApiException(422, "prefs.iso_missing", f"{path} is not a folder")
    declared = True
    try:
        folder = Path(helper_client.call("add_iso_library", {"path": str(path)})["path"])
    except ApiException as exc:
        if exc.code not in WITHOUT_HELPER:
            raise
        declared = False
        folder = path.resolve()
    libraries = [lib for lib in config.iso_libraries if not _same(lib.path, folder)]
    known = next((lib for lib in config.iso_libraries if _same(lib.path, folder)), None)
    entry = IsoLibrary(
        name=name,
        path=folder,
        recursive=recursive,
        extensions=known.extensions if known else [".iso", ".img"],
    )
    new = config.model_copy(update={"iso_libraries": [*libraries, entry]})
    _save(new, config_path)
    return Change(new, declared)


def remove(config: Config, config_path: Path | None, path: Path) -> Change:
    removed: list[str] = []
    try:
        removed = list(helper_client.call("remove_iso_library", {"path": str(path)})["removed"])
    except ApiException as exc:
        if exc.code not in NOT_THE_HELPERS:
            raise
    libraries = [lib for lib in config.iso_libraries if not _same(lib.path, path)]
    new = config.model_copy(update={"iso_libraries": libraries})
    _save(new, config_path)
    return Change(new, removed_acls=removed)


def _folders(config: Config) -> list[str]:
    return sorted(os.path.normpath(lib.path) for lib in config.iso_libraries)


def same_folders(old: Config, new: Config) -> bool:
    """Saving Preferences may rename a library, not add or remove one."""
    return _folders(old) == _folders(new)
