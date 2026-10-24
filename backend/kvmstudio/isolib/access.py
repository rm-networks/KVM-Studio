"""Can QEMU read this file? Checked the way the kernel would for QEMU's user.

QEMU (qemu:///system) runs as an unprivileged user, 107:107 on Fedora, read from
libvirt's capabilities. It needs search permission on every parent folder and
read permission on the file, through mode bits or POSIX ACLs. With SELinux,
libvirt relabels images itself, which only works where the filesystem stores
labels (not on FAT, exFAT, NTFS through FUSE...).
"""

from __future__ import annotations

import errno
import grp
import os
import pwd
import re
import shlex
import stat
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from lxml import etree

Problem = Literal["no_search", "no_read", "no_labels", "missing"]

ACL_XATTR = "system.posix_acl_access"
ACL_USER_OBJ, ACL_USER, ACL_GROUP_OBJ, ACL_GROUP, ACL_MASK, ACL_OTHER = 1, 2, 4, 8, 16, 32
R, X = 4, 1


@dataclass(frozen=True, slots=True)
class Identity:
    uid: int
    gid: int
    groups: frozenset[int]
    name: str | None


@dataclass(slots=True)
class AccessReport:
    path: str
    identity: str | None
    readable: bool
    problems: list[tuple[Problem, str]] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)


def qemu_identity(capabilities_xml: str) -> Identity | None:
    """uid/gid from the DAC base label in libvirt's capabilities ("+107:+107")."""
    root = etree.fromstring(
        capabilities_xml.encode(), parser=etree.XMLParser(resolve_entities=False)
    )
    for model in root.iterfind("host/secmodel"):
        if model.findtext("model") != "dac":
            continue
        label = model.findtext("baselabel[@type='kvm']") or model.findtext("baselabel") or ""
        match = re.fullmatch(r"\+?(\d+):\+?(\d+)", label.strip())
        if match:
            uid, gid = int(match.group(1)), int(match.group(2))
            return identity_for(uid, gid)
    return None


def identity_for(uid: int, gid: int) -> Identity:
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        name = None
    groups = {gid}
    if name:
        groups.update(g.gr_gid for g in grp.getgrall() if name in g.gr_mem)
    return Identity(uid, gid, frozenset(groups), name)


def _acl_entries(path: Path) -> list[tuple[int, int, int]] | None:
    try:
        raw = os.getxattr(path, ACL_XATTR)
    except OSError:
        return None
    if len(raw) < 4 or struct.unpack("<I", raw[:4])[0] != 2:
        return None
    return [struct.unpack("<HHI", raw[i : i + 8]) for i in range(4, len(raw) - 7, 8)]


def allowed(path: Path, who: Identity, want: int) -> bool:
    """POSIX permission check (with ACLs) for an arbitrary identity."""
    st = path.stat()
    if who.uid == 0:
        return True
    acl = _acl_entries(path)
    if acl is None:
        if st.st_uid == who.uid:
            bits = (st.st_mode >> 6) & 7
        elif st.st_gid in who.groups:
            bits = (st.st_mode >> 3) & 7
        else:
            bits = st.st_mode & 7
        return bits & want == want
    mask = next((perm for tag, perm, _id in acl if tag == ACL_MASK), 7)
    if st.st_uid == who.uid:
        return next(p for t, p, _ in acl if t == ACL_USER_OBJ) & want == want
    for tag, perm, ident in acl:
        if tag == ACL_USER and ident == who.uid:
            return perm & mask & want == want
    group_perms = [
        perm
        for tag, perm, ident in acl
        if (tag == ACL_GROUP_OBJ and st.st_gid in who.groups)
        or (tag == ACL_GROUP and ident in who.groups)
    ]
    if group_perms:
        return any(perm & mask & want == want for perm in group_perms)
    return next(p for t, p, _ in acl if t == ACL_OTHER) & want == want


def selinux_enforcing() -> bool:
    try:
        return Path("/sys/fs/selinux/enforce").read_text().strip() == "1"
    except OSError:
        return False


def has_labels(path: Path) -> bool:
    try:
        os.getxattr(path, "security.selinux")
    except OSError as exc:
        return exc.errno not in (errno.ENOTSUP, errno.EOPNOTSUPP)
    return True


def check(path: str, who: Identity | None, *, selinux: bool | None = None) -> AccessReport:
    target = Path(path)
    label = None if who is None else (who.name or f"{who.uid}:{who.gid}")
    report = AccessReport(path=path, identity=label, readable=True)
    if not target.exists():
        report.readable = False
        report.problems.append(("missing", path))
        return report
    user = (who.name or str(who.uid)) if who else None
    if who is not None and who.uid != os.getuid():
        for parent in reversed(target.resolve().parents):
            if not allowed(parent, who, X):
                report.readable = False
                report.problems.append(("no_search", str(parent)))
                report.commands.append(f"setfacl -m u:{user}:x {shlex.quote(str(parent))}")
        if stat.S_ISREG(target.stat().st_mode) and not allowed(target, who, R):
            report.readable = False
            report.problems.append(("no_read", path))
            report.commands.append(f"setfacl -m u:{user}:r {shlex.quote(path)}")
    if (selinux if selinux is not None else selinux_enforcing()) and not has_labels(target):
        report.readable = False
        report.problems.append(("no_labels", path))
    return report
