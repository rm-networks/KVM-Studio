"""qemu-img, called with argument lists only (never through a shell).

The format of an image is always given with -f: it comes from the libvirt
definition, or from the file name, never from what the file contains. A raw
disk is written freely by its VM, which could put a qcow2 header there.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

TIMEOUT = 30
MAX_CHAIN = 64
# "-p" prints "    (12.50/100%)" and rewrites it with carriage returns.
_PERCENT = re.compile(rb"\((\d+(?:\.\d+)?)/100%\)")


class QemuImgError(Exception):
    pass


def _qemu_img() -> str:
    exe = shutil.which("qemu-img")
    if exe is None:
        raise QemuImgError("qemu-img is not installed")
    return exe


def format_from_name(path: Path | str) -> str:
    """The format a file name stands for: qcow2 for .qcow2, raw for anything else."""
    return "qcow2" if str(path).lower().endswith(".qcow2") else "raw"


def backing_files(
    path: Path, fmt: str, stop: Callable[[Path], bool] | None = None
) -> list[str] | None:
    """Absolute paths of the backing chain below path, or None if unreadable.

    Only a qcow2 image has one: a raw image is never opened as anything else.
    Each level is opened on its own, with the format its parent records (raw
    when none), so nothing is opened before its name is known; the walk stops
    after the first path for which stop() is true.
    """
    chain: list[str] = []
    current, current_fmt = path, fmt
    while current_fmt == "qcow2":
        info = image_info(current, "qcow2")
        if info is None:
            return None
        backing = info.get("full-backing-filename") or info.get("backing-filename")
        if not backing:
            break
        # Relative names are relative to the image that holds them.
        following = (current.parent / str(backing)).resolve()
        if str(following) in chain or len(chain) >= MAX_CHAIN:
            return None
        chain.append(str(following))
        if stop is not None and stop(following):
            break
        current = following
        current_fmt = str(info.get("backing-filename-format") or "raw")
    return chain


def _run(args: list[str], timeout: float = TIMEOUT) -> str:
    try:
        return subprocess.run(  # noqa: S603
            [_qemu_img(), *args], capture_output=True, text=True, timeout=timeout, check=True
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise QemuImgError(exc.stderr.strip() or str(exc)) from exc


def image_info(path: Path, fmt: str) -> dict[str, Any] | None:
    try:
        info = json.loads(_run(["info", "--output=json", "-U", "-f", fmt, str(path)]))
    except (QemuImgError, subprocess.SubprocessError, OSError, ValueError):
        return None
    return info if isinstance(info, dict) else None


def rebase_unsafe(overlay: Path, backing: Path, backing_format: str | None) -> None:
    """Point overlay at backing without touching data (the backing file only moved)."""
    args = ["rebase", "-u", "-f", "qcow2", "-b", str(backing)]
    if backing_format:
        args += ["-F", backing_format]
    _run([*args, str(overlay)])


def convert(src: Path, src_fmt: str, dest: Path, fmt: str) -> None:
    """Copy a disk image, keeping it sparse (no time limit: disks can be large)."""
    try:
        subprocess.run(  # noqa: S603
            [_qemu_img(), "convert", "-p", "-f", src_fmt, "-O", fmt, str(src), str(dest)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise QemuImgError(exc.stderr.strip() or str(exc)) from exc


def create(path: Path, fmt: str, size_gib: int, *, preallocate: bool) -> None:
    """New disk image; preallocation reserves the space now (falloc: fast, no zero fill)."""
    args = ["create", "-q", "-f", fmt]
    if preallocate:
        args += ["-o", "preallocation=falloc"]
    _run([*args, str(path), f"{size_gib}G"], timeout=600)


def convert_progress(
    src: Path, src_fmt: str, dest: Path, fmt: str, on_progress: Callable[[float], None]
) -> None:
    """convert(), telling on_progress how far it went (0 to 1).

    on_progress may raise to stop the copy: qemu-img is then ended and the
    exception goes on; the partial file is the caller's to remove.
    """
    args = [_qemu_img(), "convert", "-p", "-f", src_fmt, "-O", fmt, str(src), str(dest)]
    proc = subprocess.Popen(  # noqa: S603
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0
    )
    out = proc.stdout
    if out is None:  # never: stdout is a pipe
        raise QemuImgError("no output from qemu-img")
    buffer = b""
    try:
        while chunk := out.read(64):
            buffer += chunk
            *lines, buffer = re.split(rb"[\r\n]", buffer)
            for line in lines:
                if match := _PERCENT.search(line):
                    on_progress(float(match.group(1)) / 100)
        proc.wait()
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    if proc.returncode != 0:
        error = proc.stderr.read().decode(errors="replace").strip() if proc.stderr else ""
        raise QemuImgError(error or f"qemu-img convert ended with {proc.returncode}")


def create_overlay(dest: Path, backing: Path, backing_format: str) -> None:
    """A new qcow2 image whose unchanged blocks are read from backing (linked clone)."""
    _run(["create", "-q", "-f", "qcow2", "-b", str(backing), "-F", backing_format, str(dest)])


def has_gpt(path: Path, fmt: str) -> bool:
    """True when the disk starts with a GPT partition table (an UEFI system)."""
    with tempfile.TemporaryDirectory(prefix="kvmstudio-") as tmp:
        out = Path(tmp) / "head.raw"
        try:
            _run(["dd", "-f", fmt, "-O", "raw", "bs=512", "count=2", f"if={path}", f"of={out}"])
            head = out.read_bytes()
        except (QemuImgError, subprocess.SubprocessError, OSError):
            return False
    return head[512:520] == b"EFI PART"
