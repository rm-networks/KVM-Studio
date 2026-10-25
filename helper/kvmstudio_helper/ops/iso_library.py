"""ISO libraries declared by users from Preferences, and the rights given for them.

add_iso_library     the folder (resolved) must exist, be a folder of the caller's
                    own, and be neither a system folder, inside one, nor above one.
remove_iso_library  forgets a library of the caller's, and removes the ACL entries
                    the helper added for it, unless another library still needs one
                    (a folder above two libraries keeps its search permission).
clear_iso_libraries forgets every declared library, at uninstall time, removing
                    every entry the helper added if asked to.
list_iso_libraries  the libraries the helper knows about; nothing is changed.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .. import acl, state
from ..config import HelperConfig
from ..errors import HelperError
from ..paths import client_path, declarable_folder, fd_path, open_nofollow
from ..polkit import Peer
from . import Runner, Task, expect_keys

ACTION = "org.kvmstudio.helper.iso-library"
UID_MIN = 1000
NOBODY = 65534


def _caller(peer: Peer) -> int:
    if peer.uid < UID_MIN or peer.uid == NOBODY:
        raise HelperError("not_allowed", f"uid {peer.uid} is not a regular user account")
    return peer.uid


def _needed(entry: state.AclEntry, roots: Iterable[Path]) -> bool:
    """A library still uses it: a folder on the way to it, or something inside it."""
    path = Path(entry.path)
    return any(root.is_relative_to(path) or path.is_relative_to(root) for root in roots)


def _for_library(entry: state.AclEntry, root: Path) -> bool:
    return _needed(entry, [root])


def revoke(runner: Runner, entry: state.AclEntry) -> bool:
    """Take back the bit the helper added, if the file is still the one it changed."""
    try:
        fds = open_nofollow(Path(entry.path))
    except OSError:
        return False  # gone, or replaced by a link: nothing of ours left there
    try:
        fd = fds[-1]
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) != (entry.dev, entry.ino):
            return False
        current = acl.user_entry(fd_path(fd), entry.uid)
        bit = acl.BITS[entry.bit]
        if current is None or not current & bit:
            return False
        left = current & ~bit
        if left == 0 and entry.created and entry.bare and acl.named_entries(fd_path(fd)) == 1:
            # Ours was the only entry: back to plain permission bits, mask included.
            argv = ["setfacl", "-b", "--", fd_path(fd)]
        elif left == 0 and entry.created:
            argv = ["setfacl", "-x", f"u:{entry.uid}", "--", fd_path(fd)]
        else:
            argv = ["setfacl", "-m", f"u:{entry.uid}:{acl.perm_text(left)}", "--", fd_path(fd)]
        runner(argv, (fd,))
        return True
    finally:
        for fd in fds:
            os.close(fd)


def prepare_add(params: Mapping[str, object], config: HelperConfig, peer: Peer) -> Task:
    expect_keys(params, {"path"})
    uid = _caller(peer)
    folder = declarable_folder(params["path"], uid)

    def run(_runner: Runner) -> dict[str, Any]:
        with state.editing(config.state) as current:
            # Checked again: the folder may have changed while the password was typed.
            try:
                again = declarable_folder(str(folder), uid)
            except HelperError:
                again = None
            if again != folder:
                raise HelperError("path_changed", f"{folder} changed during the request")
            if current.user_library(folder) is None:
                current.libraries.append(state.UserLibrary(str(folder), uid))
        return {"path": str(folder)}

    return run


def prepare_remove(params: Mapping[str, object], config: HelperConfig, peer: Peer) -> Task:
    expect_keys(params, {"path"})
    uid = _caller(peer)
    # Not resolved: the folder may be gone already. Its declared path is enough.
    folder = Path(os.path.normpath(client_path(params["path"])))
    known = state.load(config.state).user_library(folder)
    if known is None:
        if any(lib.path == folder for lib in config.iso_libraries):
            raise HelperError("admin_library", f"{folder} is declared in helper.toml")
        raise HelperError("not_declared", f"{folder} is not a declared ISO library")
    if known.owner != uid:
        raise HelperError("not_owner", f"{folder} was declared by another account")

    def run(runner: Runner) -> dict[str, Any]:
        removed: list[str] = []
        with state.editing(config.state) as current:
            current.libraries = [lib for lib in current.libraries if Path(lib.path) != folder]
            others = [lib.path for lib in state.libraries(config, current)]
            keep = []
            for entry in current.acl:
                if not _for_library(entry, folder) or _needed(entry, others):
                    keep.append(entry)
                elif revoke(runner, entry):
                    removed.append(f"{entry.path} u:{entry.uid}:{entry.bit}")
            current.acl = keep
        return {"path": str(folder), "removed": removed}

    return run


def prepare_clear(params: Mapping[str, object], config: HelperConfig, peer: Peer) -> Task:
    expect_keys(params, {"remove_acls"})
    remove_acls = params["remove_acls"]
    if not isinstance(remove_acls, bool):
        raise HelperError("invalid_params", "remove_acls must be true or false")

    def run(runner: Runner) -> dict[str, Any]:
        return clear(config, runner, remove_acls=remove_acls)

    return run


def clear(config: HelperConfig, runner: Runner, *, remove_acls: bool) -> dict[str, Any]:
    removed: list[str] = []
    with state.editing(config.state) as current:
        if remove_acls:
            for entry in current.acl:
                if revoke(runner, entry):
                    removed.append(f"{entry.path} u:{entry.uid}:{entry.bit}")
        current.libraries = []
        current.acl = []
    return {"removed": removed}


def prepare_list(params: Mapping[str, object], config: HelperConfig, peer: Peer) -> Task:
    expect_keys(params, set())

    def run(_runner: Runner) -> dict[str, Any]:
        current = state.load(config.state)
        mine = [lib for lib in current.libraries if lib.owner == peer.uid]
        return {
            "libraries": [
                *({"path": str(lib.path), "source": "admin"} for lib in config.iso_libraries),
                *({"path": lib.path, "source": "user"} for lib in mine),
            ],
            "acl_entries": sum(
                1 for e in current.acl if any(_for_library(e, Path(m.path)) for m in mine)
            ),
        }

    return run
