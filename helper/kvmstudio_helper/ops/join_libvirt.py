"""Add the calling user to the libvirt group.

No parameters: the account is the one the kernel reports for the peer
process, the group is fixed here. Root and system accounts are refused.
"""

from __future__ import annotations

import grp
import pwd
import re
from collections.abc import Callable, Mapping
from typing import Any

from ..config import HelperConfig
from ..errors import HelperError
from ..polkit import Peer
from . import Runner, Task, expect_keys

ACTION = "org.kvmstudio.helper.join-libvirt"
GROUP = "libvirt"
UID_MIN = 1000
NOBODY = 65534
_NAME = re.compile(r"[a-z_][a-z0-9_.-]*\$?")

# Replaced in tests.
user_by_uid: Callable[[int], pwd.struct_passwd] = pwd.getpwuid
group_by_name: Callable[[str], grp.struct_group] = grp.getgrnam


def prepare(params: Mapping[str, object], config: HelperConfig, peer: Peer) -> Task:
    expect_keys(params, set())
    if peer.uid < UID_MIN or peer.uid == NOBODY:
        raise HelperError("not_allowed", f"uid {peer.uid} is not a regular user account")
    try:
        user = user_by_uid(peer.uid)
    except KeyError:
        raise HelperError("not_allowed", f"uid {peer.uid} has no account") from None
    if not _NAME.fullmatch(user.pw_name):
        raise HelperError("not_allowed", f"unexpected account name for uid {peer.uid}")
    try:
        group = group_by_name(GROUP)
    except KeyError:
        raise HelperError("failed", f"no {GROUP} group: is libvirt installed?") from None

    def run(runner: Runner) -> dict[str, Any]:
        if user.pw_name in group.gr_mem or user.pw_gid == group.gr_gid:
            return {"user": user.pw_name, "already": True}
        runner(["usermod", "-a", "-G", GROUP, "--", user.pw_name], ())
        return {"user": user.pw_name, "already": False}

    return run
