"""Let QEMU read an ISO image of a declared library.

Adds the ACL entries u:<qemu>:x on the library root and the folders below it,
and u:<qemu>:r on the image. Folders above the library root are left alone:
the backend tells the user how to fix those.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..config import HelperConfig
from ..errors import HelperError
from ..paths import client_path, confine, fd_path, opened_chain
from . import Runner, Task, expect_keys

ACTION = "org.kvmstudio.helper.iso-acl"


def prepare(params: Mapping[str, object], config: HelperConfig) -> Task:
    expect_keys(params, {"path"})
    target = confine(client_path(params["path"]), config.iso_libraries)
    if target.relative.suffix.lower() not in target.library.extensions:
        raise HelperError("path_not_allowed", f"{target.path} is not an ISO image")
    uid = config.qemu_uid
    if uid is None:
        raise HelperError("failed", "no QEMU account found, set qemu_user in helper.toml")

    def run(runner: Runner) -> dict[str, Any]:
        changed: list[str] = []
        with opened_chain(target) as fds:
            folders = [target.root, *(target.root / p for p in target.relative.parents[-2::-1])]
            perms = "x" * len(folders) + "r"
            for fd, path, perm in zip(fds, [*folders, target.path], perms, strict=True):
                runner(["setfacl", "-m", f"u:{uid}:{perm}", "--", fd_path(fd)], (fd,))
                changed.append(str(path))
        return {"changed": changed}

    return run
