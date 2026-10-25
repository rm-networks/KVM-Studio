"""Give a cloned VM the firmware variables and TPM state of its source.

Both belong to accounts the user is not: libvirt makes the NVRAM file QEMU's,
and keeps the TPM state in its own folder, owned by swtpm's account. Cloning
copies them; nothing else is read or written.

- TPM: <swtpm_dir>/<source uuid>/ to <swtpm_dir>/<target uuid>/, which must not
  exist; owners and modes are kept, links and special files are refused.
- NVRAM: a regular file with a single link, owned by the caller or by QEMU, in
  a folder of the caller's, outside system folders, to a new file in another
  folder of the caller's; the copy belongs to the caller.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..config import HelperConfig
from ..errors import HelperError
from ..paths import client_path, open_nofollow, system_folder
from ..polkit import Peer
from . import Runner, Task, expect_keys

ACTION = "org.kvmstudio.helper.clone-state"
UID_MIN = 1000
NOBODY = 65534
CHUNK = 1 << 20
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _uuid(value: object, name: str) -> str:
    if not isinstance(value, str) or not _UUID.match(value):
        raise HelperError("invalid_params", f"{name} must be a lowercase UUID")
    return value


def _optional_path(value: object) -> Path | None:
    return None if value is None else client_path(value)


def _close(fds: list[int]) -> None:
    for fd in fds:
        os.close(fd)


def _open_folder(path: Path, uid: int) -> int:
    """The caller's own folder, reached without following any link."""
    if system_folder(path):
        raise HelperError("path_not_allowed", f"{path} is a system folder or inside one")
    try:
        fds = open_nofollow(path)
    except OSError:
        raise HelperError("not_found", f"{path} does not exist") from None
    folder = fds.pop()
    _close(fds)
    st = os.fstat(folder)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != uid:
        os.close(folder)
        raise HelperError("not_owner", f"{path} is not a folder of yours")
    return folder


def _copy_fd(src: int, dst: int) -> None:
    while chunk := os.read(src, CHUNK):
        view = memoryview(chunk)
        while view:
            view = view[os.write(dst, view) :]


def copy_nvram(source: Path, target: Path, uid: int, gid: int, qemu_uid: int | None) -> None:
    src_dir = _open_folder(source.parent, uid)
    try:
        try:
            src = os.open(source.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=src_dir)
        except OSError:
            raise HelperError("not_found", f"{source} does not exist") from None
    finally:
        os.close(src_dir)
    try:
        st = os.fstat(src)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise HelperError("path_not_allowed", f"{source} is not a plain file")
        if st.st_uid not in (uid, qemu_uid):
            raise HelperError("not_owner", f"{source} is not a firmware file of your VMs")
        dst_dir = _open_folder(target.parent, uid)
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
            try:
                dst = os.open(target.name, flags, 0o600, dir_fd=dst_dir)
            except FileExistsError:
                raise HelperError("exists", f"{target} already exists") from None
            try:
                _copy_fd(src, dst)
                os.fchown(dst, uid, gid)
            except BaseException:
                os.unlink(target.name, dir_fd=dst_dir)
                raise
            finally:
                os.close(dst)
        finally:
            os.close(dst_dir)
    finally:
        os.close(src)


def copy_tpm(swtpm_dir: Path, source: str, target: str) -> bool:
    """Copy the TPM state folder; False when the source VM has none yet."""
    try:
        root = open_nofollow(swtpm_dir)
    except OSError:
        return False
    base = root.pop()
    _close(root)
    try:
        try:
            src = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base)
        except OSError:
            return False
        try:
            try:
                os.mkdir(target, mode=0o700, dir_fd=base)
            except FileExistsError:
                raise HelperError("exists", f"TPM state for {target} already exists") from None
            dst = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base)
            try:
                _copy_tree(src, dst)
            except BaseException:
                os.close(dst)
                _remove_tree(base, target)
                raise
            os.close(dst)
        finally:
            os.close(src)
    finally:
        os.close(base)
    return True


def _copy_tree(src: int, dst: int) -> None:
    st = os.fstat(src)
    os.fchmod(dst, stat.S_IMODE(st.st_mode))
    os.fchown(dst, st.st_uid, st.st_gid)
    for name in os.listdir(src):
        info = os.stat(name, dir_fd=src, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=src)
            try:
                os.mkdir(name, mode=0o700, dir_fd=dst)
                copy = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dst)
                try:
                    _copy_tree(child, copy)
                finally:
                    os.close(copy)
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode):
            fin = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=src)
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                fout = os.open(name, flags, 0o600, dir_fd=dst)
                try:
                    _copy_fd(fin, fout)
                    os.fchmod(fout, stat.S_IMODE(info.st_mode))
                    os.fchown(fout, info.st_uid, info.st_gid)
                finally:
                    os.close(fout)
            finally:
                os.close(fin)
        else:
            raise HelperError("path_not_allowed", f"unexpected entry {name} in the TPM state")


def _remove_tree(base: int, name: str) -> None:
    folder = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base)
    try:
        for entry in os.listdir(folder):
            info = os.stat(entry, dir_fd=folder, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                _remove_tree(folder, entry)
            else:
                os.unlink(entry, dir_fd=folder)
    finally:
        os.close(folder)
    os.rmdir(name, dir_fd=base)


def prepare(params: Mapping[str, object], config: HelperConfig, peer: Peer) -> Task:
    expect_keys(params, {"source_uuid", "target_uuid", "nvram_source", "nvram_target"})
    if peer.uid < UID_MIN or peer.uid == NOBODY:
        raise HelperError("not_allowed", f"uid {peer.uid} is not a regular user account")
    source = _uuid(params["source_uuid"], "source_uuid")
    target = _uuid(params["target_uuid"], "target_uuid")
    if source == target:
        raise HelperError("invalid_params", "source and target must differ")
    nvram_source = _optional_path(params["nvram_source"])
    nvram_target = _optional_path(params["nvram_target"])
    if (nvram_source is None) != (nvram_target is None):
        raise HelperError("invalid_params", "give both NVRAM paths or none")
    if nvram_source is not None and nvram_target is not None:
        if nvram_source.parent == nvram_target.parent:
            raise HelperError("invalid_params", "the copy goes to the clone's own folder")
        # Checked now so that a refusal comes before the password.
        os.close(_open_folder(nvram_source.parent, peer.uid))
        os.close(_open_folder(nvram_target.parent, peer.uid))

    def run(_runner: Runner) -> dict[str, Any]:
        nvram = False
        if nvram_source is not None and nvram_target is not None:
            copy_nvram(nvram_source, nvram_target, peer.uid, peer.gid, config.qemu_uid)
            nvram = True
        try:
            tpm = copy_tpm(config.swtpm_dir, source, target)
        except BaseException:
            if nvram_target is not None and nvram:
                folder = _open_folder(nvram_target.parent, peer.uid)
                try:
                    os.unlink(nvram_target.name, dir_fd=folder)
                finally:
                    os.close(folder)
            raise
        return {"nvram": nvram, "tpm": tpm}

    return run
