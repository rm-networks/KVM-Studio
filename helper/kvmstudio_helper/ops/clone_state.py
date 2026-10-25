"""Give a cloned VM the firmware variables and TPM state of its source.

Both belong to accounts the user is not: libvirt makes the NVRAM file QEMU's,
and keeps the TPM state in its own folder, owned by swtpm's account. Cloning
copies them; nothing else is read or written.

The client only names the two VMs by UUID. Their files are taken from libvirt
(qemu:///system), and both VMs must be shut off, before the password and again
after it.

- NVRAM: the source's file, regular with a single link, owned by the caller or
  by QEMU, is copied to the clone's file, which must not exist yet and must lie
  in a folder of the caller's under <location>/KVM-Studio/VM/. Owner and mode
  are those of the source.
- TPM: <swtpm_dir>/<source uuid>/ to <swtpm_dir>/<target uuid>/, which must not
  exist; owners and modes are kept, links and special files are refused.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import HelperConfig
from ..errors import HelperError
from ..paths import open_nofollow, system_folder
from ..polkit import TOOL_ENV, Peer
from . import Runner, Task, expect_keys

ACTION = "org.kvmstudio.helper.clone-state"
URI = "qemu:///system"
UID_MIN = 1000
NOBODY = 65534
CHUNK = 1 << 20
VIRSH_TIMEOUT = 30
# Every VM of KVM Studio lives under <location>/KVM-Studio/VM/<folders>/<name>/.
LIBRARY = ("KVM-Studio", "VM")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclass(frozen=True, slots=True)
class Domain:
    uuid: str
    running: bool
    nvram: Path | None
    tpm: bool


def virsh(args: list[str]) -> str:
    """Read-only virsh query; replaced in tests."""
    try:
        # PATH is limited to the system folders (TOOL_ENV).
        result = subprocess.run(  # noqa: S603
            ["virsh", "-q", "-c", URI, *args],  # noqa: S607
            env=TOOL_ENV,
            capture_output=True,
            timeout=VIRSH_TIMEOUT,
            check=True,
        )
    except subprocess.CalledProcessError:
        raise HelperError("not_found", f"no virtual machine {args[-1]} in {URI}") from None
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HelperError("failed", f"virsh: {exc}") from None
    return result.stdout.decode(errors="replace")


def domain(uuid: str) -> Domain:
    # libvirt's own output; expat expands no external entity.
    root = ET.fromstring(virsh(["dumpxml", "--inactive", uuid]))  # noqa: S314
    if root.findtext("uuid") != uuid:
        raise HelperError("not_found", f"no virtual machine {uuid} in {URI}")
    running = virsh(["domstate", uuid]).strip() != "shut off"
    nvram_el = root.find("os/nvram")
    nvram = None
    if nvram_el is not None:
        source = nvram_el.find("source")
        text = source.get("file") if source is not None else nvram_el.text
        if text and text.strip():
            nvram = Path(text.strip())
            if not nvram.is_absolute():
                raise HelperError("path_not_allowed", f"{nvram} is not an absolute path")
    tpm = root.find("devices/tpm/backend[@type='emulator']") is not None
    return Domain(uuid, running, nvram, tpm)


def _uuid(value: object, name: str) -> str:
    if not isinstance(value, str) or not _UUID.match(value):
        raise HelperError("invalid_params", f"{name} must be a lowercase UUID")
    return value


def _close(fds: list[int]) -> None:
    for fd in fds:
        os.close(fd)


def _shut_off(source: str, target: str) -> tuple[Domain, Domain]:
    src, dst = domain(source), domain(target)
    if src.running:
        raise HelperError("running", "power the source virtual machine off first")
    if dst.running:
        raise HelperError("running", "the clone is running")
    return src, dst


def _open_link_free(path: Path) -> list[int]:
    """O_PATH descriptors down to path, which must hold no link at all."""
    try:
        if path.resolve(strict=True) != path:
            raise HelperError("path_not_allowed", f"{path} goes through a symbolic link")
        return open_nofollow(path)
    except (OSError, RuntimeError):
        raise HelperError("not_found", f"{path} does not exist") from None


def _open_vm_folder(path: Path, uid: int) -> int:
    """The clone's folder: under <location>/KVM-Studio/VM/, the caller's down from there."""
    parts = path.parts
    start = next((i for i in range(1, len(parts) - 2) if parts[i : i + 2] == LIBRARY), None)
    if start is None or system_folder(path):
        raise HelperError("path_not_allowed", f"{path} is not inside a KVM-Studio/VM folder")
    fds = _open_link_free(path)
    try:
        # fds[i] is the folder parts[i]; KVM-Studio and everything below are the caller's.
        for fd in fds[start:]:
            st = os.fstat(fd)
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != uid:
                raise HelperError("not_owner", f"{path} is not a folder of yours")
        folder = fds.pop()
    finally:
        _close(fds)
    return folder


def _copy_fd(src: int, dst: int) -> None:
    while chunk := os.read(src, CHUNK):
        view = memoryview(chunk)
        while view:
            view = view[os.write(dst, view) :]


def _open_nvram(path: Path, uid: int, qemu_uid: int | None) -> int:
    fds = _open_link_free(path.parent)
    try:
        try:
            src = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fds[-1])
        except FileNotFoundError:
            raise HelperError("not_found", f"{path} does not exist") from None
        except OSError:
            # A symbolic link (ELOOP) or a file the helper may not read.
            raise HelperError("path_not_allowed", f"{path} is not a plain file") from None
    finally:
        _close(fds)
    st = os.fstat(src)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        os.close(src)
        raise HelperError("path_not_allowed", f"{path} is not a plain file")
    if st.st_uid not in (uid, qemu_uid):
        os.close(src)
        raise HelperError("not_owner", f"{path} is not a firmware file of your VMs")
    return src


def copy_nvram(source: Path, target: Path, uid: int, qemu_uid: int | None) -> None:
    src = _open_nvram(source, uid, qemu_uid)
    try:
        st = os.fstat(src)
        dst_dir = _open_vm_folder(target.parent, uid)
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
            try:
                dst = os.open(target.name, flags, 0o600, dir_fd=dst_dir)
            except FileExistsError:
                raise HelperError("exists", f"{target} already exists") from None
            try:
                _copy_fd(src, dst)
                os.fchmod(dst, stat.S_IMODE(st.st_mode))
                os.fchown(dst, st.st_uid, st.st_gid)
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


def _check(src: Domain, dst: Domain, peer: Peer, qemu_uid: int | None) -> bool:
    """Whether there is an NVRAM to copy; refuses what would fail anyway."""
    if src.nvram is None:
        return False
    if dst.nvram is None or dst.nvram.parent == src.nvram.parent:
        raise HelperError("invalid_params", "the clone needs its own firmware file")
    os.close(_open_vm_folder(dst.nvram.parent, peer.uid))
    try:
        os.close(_open_nvram(src.nvram, peer.uid, qemu_uid))
    except HelperError as exc:
        if exc.code == "not_found":
            return False  # never started: libvirt makes it from its template
        raise
    return True


def prepare(params: Mapping[str, object], config: HelperConfig, peer: Peer) -> Task:
    expect_keys(params, {"source_uuid", "target_uuid"})
    if peer.uid < UID_MIN or peer.uid == NOBODY:
        raise HelperError("not_allowed", f"uid {peer.uid} is not a regular user account")
    source = _uuid(params["source_uuid"], "source_uuid")
    target = _uuid(params["target_uuid"], "target_uuid")
    if source == target:
        raise HelperError("invalid_params", "source and target must differ")
    # Checked now so that a refusal comes before the password.
    src, dst = _shut_off(source, target)
    _check(src, dst, peer, config.qemu_uid)

    def run(_runner: Runner) -> dict[str, Any]:
        # The VMs may have changed while the password was typed.
        src, dst = _shut_off(source, target)
        nvram = _check(src, dst, peer, config.qemu_uid)
        if nvram and src.nvram is not None and dst.nvram is not None:
            copy_nvram(src.nvram, dst.nvram, peer.uid, config.qemu_uid)
        try:
            tpm = src.tpm and dst.tpm and copy_tpm(config.swtpm_dir, source, target)
        except BaseException:
            if nvram and dst.nvram is not None:
                folder = _open_vm_folder(dst.nvram.parent, peer.uid)
                try:
                    os.unlink(dst.nvram.name, dir_fd=folder)
                finally:
                    os.close(folder)
            raise
        return {"nvram": nvram, "tpm": tpm}

    return run
