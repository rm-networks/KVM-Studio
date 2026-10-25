"""Let QEMU read an ISO image of a declared library.

Adds u:<qemu>:x on the library root and the folders below it, and u:<qemu>:r on
the image. For a library a user declared, the folders above it that belong to
that user (their home folder, say) get u:<qemu>:x too when QEMU cannot cross
them yet. Folders of other accounts are never changed.

Each bit added is written to the state, so that removing the library later
takes away exactly what was added here, and nothing that was there before.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .. import acl, state
from ..config import HelperConfig
from ..errors import HelperError
from ..paths import Confined, client_path, confine, fd_path, open_nofollow, opened_chain
from ..polkit import Peer
from . import Runner, Task, expect_keys

ACTION = "org.kvmstudio.helper.iso-acl"


def grant(
    runner: Runner, current: state.State, fd: int, path: Path, uid: int, bit: state.Bit
) -> bool:
    """Add one bit to u:<uid> on the opened file and record it; False if already there."""
    before = acl.user_entry(fd_path(fd), uid)
    if before is not None and before & acl.BITS[bit]:
        return False
    after = (before or 0) | acl.BITS[bit]
    bare = acl.named_entries(fd_path(fd)) == 0
    runner(["setfacl", "-m", f"u:{uid}:{acl.perm_text(after)}", "--", fd_path(fd)], (fd,))
    st = os.fstat(fd)
    entry = state.AclEntry(str(path), st.st_dev, st.st_ino, uid, bit, before is None, bare)
    current.record(entry)
    return True


def _grant_above(runner: Runner, current: state.State, target: Confined, uid: int) -> list[str]:
    """Search permission on the owner's folders right above a user's library."""
    owner = target.library.owner
    if owner is None:
        return []
    changed = []
    try:
        fds = open_nofollow(target.root)
    except OSError:
        raise HelperError("path_changed", f"{target.root} changed during the request") from None
    try:
        folders = [Path("/"), *target.root.parents[-2::-1]]
        for fd, folder in reversed(list(zip(fds[:-1], folders, strict=True))):
            st = os.fstat(fd)
            if st.st_uid != owner:
                break
            others_cross = acl.user_entry(fd_path(fd), uid) is None and st.st_mode & 0o001
            if not others_cross and grant(runner, current, fd, folder, uid, "x"):
                changed.append(str(folder))
    finally:
        for fd in fds:
            os.close(fd)
    return changed[::-1]


def prepare(params: Mapping[str, object], config: HelperConfig, peer: Peer) -> Task:
    expect_keys(params, {"path"})
    target = confine(client_path(params["path"]), state.libraries(config))
    if target.relative.suffix.lower() not in target.library.extensions:
        raise HelperError("path_not_allowed", f"{target.path} is not an ISO image")
    uid = config.qemu_uid
    if uid is None:
        raise HelperError("failed", "no QEMU account found, set qemu_user in helper.toml")

    def run(runner: Runner) -> dict[str, Any]:
        changed: list[str] = []
        with state.editing(config.state) as current:
            changed += _grant_above(runner, current, target, uid)
            with opened_chain(target) as fds:
                folders = [
                    target.root,
                    *(target.root / p for p in target.relative.parents[-2::-1]),
                ]
                search: state.Bit = "x"
                read: state.Bit = "r"
                bits = [search] * len(folders) + [read]
                for fd, path, bit in zip(fds, [*folders, target.path], bits, strict=True):
                    if grant(runner, current, fd, path, uid, bit):
                        changed.append(str(path))
        return {"changed": changed}

    return run
