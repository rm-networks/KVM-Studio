"""Paths received from a client: validated, resolved, then opened without races.

A path is resolved (symlinks and "..") before any check. The check alone is not
enough: the user owns the folders and could swap one for a symlink between the
check and the change. So the target is then opened one component at a time with
O_NOFOLLOW from the library root, and tools are given /proc/self/fd/N, which
always designates the file that was opened.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .config import IsoLibrary
from .errors import HelperError

MAX_PATH = 4096
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
# A library is never one of these, inside one, or above one.
SYSTEM_DIRS = tuple(
    Path(p)
    for p in (
        "/etc",
        "/usr",
        "/var",
        "/boot",
        "/root",
        "/proc",
        "/sys",
        "/dev",
        "/run",
        "/bin",
        "/sbin",
        "/lib",
        "/lib64",
    )
)


@dataclass(frozen=True, slots=True)
class Confined:
    root: Path
    relative: PurePosixPath
    library: IsoLibrary

    @property
    def path(self) -> Path:
        return self.root / self.relative


def client_path(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise HelperError("invalid_params", "path must be a non-empty string")
    if len(value) > MAX_PATH:
        raise HelperError("invalid_params", "path is too long")
    if _CONTROL.search(value):
        raise HelperError("invalid_params", "path contains control characters")
    path = Path(value)
    if not path.is_absolute():
        raise HelperError("invalid_params", "path must be absolute")
    return path


def system_folder(path: Path) -> bool:
    """path is "/", a system folder, inside one, or holds one."""
    if path == Path("/"):
        return True
    for system in SYSTEM_DIRS:
        for candidate in {system, system.resolve()}:
            if path.is_relative_to(candidate) or candidate.is_relative_to(path):
                return True
    return False


def declarable_folder(value: object, uid: int) -> Path:
    """A folder a user may declare as an ISO library, resolved."""
    path = client_path(value)
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise HelperError("not_found", f"{path} does not exist") from None
    try:
        st = resolved.stat()
    except OSError:
        raise HelperError("not_found", f"{path} does not exist") from None
    if not stat.S_ISDIR(st.st_mode):
        raise HelperError("not_a_folder", f"{resolved} is not a folder")
    if system_folder(resolved):
        raise HelperError("system_folder", f"{resolved} is a system folder or holds one")
    if st.st_uid != uid:
        raise HelperError("not_owner", f"{resolved} does not belong to you")
    return resolved


def _root_of(library: IsoLibrary) -> Path | None:
    """The library folder as it is now; a user's must still be theirs, link-free."""
    if library.owner is None:
        return library.path.resolve()
    if library.path.resolve() != library.path or system_folder(library.path):
        return None
    return library.path


def confine(path: Path, libraries: tuple[IsoLibrary, ...]) -> Confined:
    """Resolve path and return it if it lies strictly inside a declared library."""
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise HelperError("not_found", f"{path} does not exist") from None
    for library in libraries:
        root = _root_of(library)
        if root is not None and resolved != root and resolved.is_relative_to(root):
            return Confined(root, PurePosixPath(resolved.relative_to(root)), library)
    raise HelperError("path_not_allowed", f"{resolved} is not inside a declared ISO library")


def open_nofollow(path: Path) -> list[int]:
    """O_PATH descriptors from "/" down to path, refusing any symbolic link on the way."""
    fds = [os.open("/", os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)]
    try:
        for name in PurePosixPath(path).parts[1:]:
            fds.append(os.open(name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fds[-1]))
            if stat.S_ISLNK(os.fstat(fds[-1]).st_mode):
                raise OSError(f"{path} holds a symbolic link")
    except OSError:
        _close(fds)
        raise
    return fds


def _open_chain(target: Confined) -> list[int]:
    fds: list[int] = []
    try:
        above = open_nofollow(target.root)
        fds.append(above.pop())
        _close(above)
        if not stat.S_ISDIR(os.fstat(fds[0]).st_mode):
            raise HelperError("path_changed", f"{target.root} changed during the request")
        owner = target.library.owner
        if owner is not None and os.fstat(fds[0]).st_uid != owner:
            raise HelperError("path_changed", f"{target.root} changed during the request")
        parts = target.relative.parts
        for i, name in enumerate(parts):
            fd = os.open(name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fds[-1])
            fds.append(fd)
            mode = os.fstat(fd).st_mode
            last = i == len(parts) - 1
            if not (stat.S_ISREG(mode) if last else stat.S_ISDIR(mode)):
                raise HelperError("path_changed", f"{target.path} changed during the request")
    except OSError:
        _close(fds)
        raise HelperError("path_changed", f"{target.path} changed during the request") from None
    except HelperError:
        _close(fds)
        raise
    return fds


def _close(fds: list[int]) -> None:
    for fd in fds:
        os.close(fd)


@contextmanager
def opened_chain(target: Confined) -> Iterator[list[int]]:
    """O_PATH descriptors from the library root down to the file, in that order."""
    fds = _open_chain(target)
    try:
        yield fds
    finally:
        _close(fds)


def fd_path(fd: int) -> str:
    """Path a child process started with pass_fds=(fd,) uses to reach that file."""
    return f"/proc/self/fd/{fd}"
