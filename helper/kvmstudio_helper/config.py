"""/etc/kvm-studio/helper.toml, owned by root and edited by the administrator.

Only the ISO libraries listed here can be touched by the helper: the user's own
config.toml is never trusted for that.
"""

from __future__ import annotations

import os
import pwd
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path("/etc/kvm-studio/helper.toml")
DEFAULT_SOCKET = Path("/run/kvmstudio-helper.sock")
DEFAULT_EXTENSIONS = (".iso", ".img")
# Account QEMU runs as with qemu:///system (Fedora, then Debian/Ubuntu).
QEMU_USERS = ("qemu", "libvirt-qemu")


@dataclass(frozen=True, slots=True)
class IsoLibrary:
    path: Path
    extensions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HelperConfig:
    socket: Path
    qemu_uid: int | None
    iso_libraries: tuple[IsoLibrary, ...]


class ConfigError(ValueError):
    pass


def _check_keys(table: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = set(table) - allowed
    if unknown:
        raise ConfigError(f"{where}: unknown keys {', '.join(sorted(unknown))}")


def _qemu_uid(name: object) -> int | None:
    if name is not None:
        if not isinstance(name, str):
            raise ConfigError("qemu_user must be a string")
        try:
            return pwd.getpwnam(name).pw_uid
        except KeyError:
            raise ConfigError(f"qemu_user: no account named {name}") from None
    for candidate in QEMU_USERS:
        try:
            return pwd.getpwnam(candidate).pw_uid
        except KeyError:
            continue
    return None


def _library(table: object, index: int) -> IsoLibrary:
    where = f"iso_libraries[{index}]"
    if not isinstance(table, dict):
        raise ConfigError(f"{where} must be a table")
    _check_keys(table, {"path", "extensions"}, where)
    path = table.get("path")
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise ConfigError(f"{where}.path must be an absolute path")
    extensions = table.get("extensions", list(DEFAULT_EXTENSIONS))
    if not isinstance(extensions, list) or not all(
        isinstance(e, str) and e.startswith(".") for e in extensions
    ):
        raise ConfigError(f'{where}.extensions must be a list like [".iso"]')
    return IsoLibrary(Path(path), tuple(e.lower() for e in extensions))


def parse(data: dict[str, Any]) -> HelperConfig:
    _check_keys(data, {"socket", "qemu_user", "iso_libraries"}, "helper.toml")
    socket = data.get("socket", str(DEFAULT_SOCKET))
    if not isinstance(socket, str) or not Path(socket).is_absolute():
        raise ConfigError("socket must be an absolute path")
    libraries = data.get("iso_libraries", [])
    if not isinstance(libraries, list):
        raise ConfigError("iso_libraries must be an array of tables")
    return HelperConfig(
        socket=Path(socket),
        qemu_uid=_qemu_uid(data.get("qemu_user")),
        iso_libraries=_unique([_library(t, i) for i, t in enumerate(libraries)]),
    )


def _unique(libraries: list[IsoLibrary]) -> tuple[IsoLibrary, ...]:
    """The same folder declared twice counts once (extensions merged)."""
    merged: dict[str, IsoLibrary] = {}
    for lib in libraries:
        key = os.path.normpath(lib.path)
        if key in merged:
            known = merged[key]
            extra = tuple(e for e in lib.extensions if e not in known.extensions)
            merged[key] = IsoLibrary(known.path, known.extensions + extra)
        else:
            merged[key] = IsoLibrary(Path(key), lib.extensions)
    return tuple(merged.values())


def load(path: Path = DEFAULT_PATH) -> HelperConfig:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        data = {}
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    return parse(data)
