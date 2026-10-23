"""Where KVM Studio may touch files, and the checks that keep it there.

Every path coming from a client is resolved (symlinks and "..") before being
compared to the allowed roots: the KVM Studio library root, and the declared
ISO libraries (read only). Anything else is refused with a 403.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .errors import ApiException

LIBRARY_DIRNAME = "KVM-Studio"
VMS_DIRNAME = "VM"


class PathNotAllowed(ApiException):
    def __init__(self, path: str) -> None:
        super().__init__(403, "path.not_allowed", f"{path} is outside the allowed folders")


def library_root(config: Config) -> Path | None:
    """<chosen location>/KVM-Studio/VM, or None until a location is configured."""
    location = config.storage.vm_default_location
    if location is None:
        return None
    return location / LIBRARY_DIRNAME / VMS_DIRNAME


def iso_roots(config: Config) -> list[Path]:
    return [lib.path for lib in config.iso_libraries]


def resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def is_within(path: str | Path, root: Path) -> bool:
    """True if path is root itself or below it, after resolving both."""
    return resolve(path).is_relative_to(resolve(root))


def is_strictly_within(path: str | Path, root: Path) -> bool:
    resolved, base = resolve(path), resolve(root)
    return resolved != base and resolved.is_relative_to(base)


def in_library(path: str | Path, config: Config) -> bool:
    root = library_root(config)
    return root is not None and is_strictly_within(path, root)


def in_iso_library(path: str | Path, config: Config) -> bool:
    return any(is_strictly_within(path, root) for root in iso_roots(config))


def confine(path: str, config: Config, *, allow_iso: bool = True) -> Path:
    """Return the resolved path if it is allowed, raise PathNotAllowed otherwise."""
    if in_library(path, config) or (allow_iso and in_iso_library(path, config)):
        return resolve(path)
    raise PathNotAllowed(path)
