"""POSIX ACL entries of one user, read from the inode the helper opened.

The entries are read straight from the system.posix_acl_access attribute, so
the helper knows what was there before it changes anything.
"""

from __future__ import annotations

import os
import struct

ACL_XATTR = "system.posix_acl_access"
ACL_USER = 0x02
BITS = {"r": 4, "x": 1}


ACL_GROUP = 0x08


def _entries(path: str) -> list[tuple[int, int, int]] | None:
    try:
        raw = os.getxattr(path, ACL_XATTR)
    except OSError:
        return None
    if len(raw) < 4 or struct.unpack("<I", raw[:4])[0] != 2:
        return None
    return [struct.unpack("<HHI", raw[i : i + 8]) for i in range(4, len(raw) - 7, 8)]


def user_entry(path: str, uid: int) -> int | None:
    """The permission bits of u:<uid> on path (rwx = 4|2|1), None without one."""
    for tag, perm, ident in _entries(path) or []:
        if tag == ACL_USER and ident == uid:
            return int(perm) & 7
    return None


def named_entries(path: str) -> int:
    """How many u:<name> and g:<name> entries the file has; 0 without an ACL."""
    return sum(1 for tag, _p, _i in _entries(path) or [] if tag in (ACL_USER, ACL_GROUP))


def perm_text(bits: int) -> str:
    return "".join(c if bits & v else "-" for c, v in (("r", 4), ("w", 2), ("x", 1)))
