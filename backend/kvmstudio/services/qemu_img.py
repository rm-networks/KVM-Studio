"""qemu-img, called with argument lists only (never through a shell)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

QCOW2_MAGIC = b"QFI\xfb"
TIMEOUT = 30
# "-p" prints "    (12.50/100%)" and rewrites it with carriage returns.
_PERCENT = re.compile(rb"\((\d+(?:\.\d+)?)/100%\)")


class QemuImgError(Exception):
    pass


def _qemu_img() -> str:
    exe = shutil.which("qemu-img")
    if exe is None:
        raise QemuImgError("qemu-img is not installed")
    return exe


def is_qcow2(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(4) == QCOW2_MAGIC
    except OSError:
        return False


def backing_files(path: Path) -> list[str] | None:
    """Absolute paths of the backing chain below path, or None if unreadable."""
    try:
        out = subprocess.run(  # noqa: S603
            [_qemu_img(), "info", "--output=json", "--backing-chain", "-U", str(path)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=True,
        ).stdout
        images = json.loads(out)
    except (subprocess.SubprocessError, OSError, ValueError, QemuImgError):
        return None
    chain = []
    for image in images if isinstance(images, list) else [images]:
        backing = image.get("full-backing-filename") or image.get("backing-filename")
        if backing:
            # Relative names are relative to the image that holds them.
            base = Path(image.get("filename", str(path))).parent
            chain.append(str((base / backing).resolve()))
    return chain


def _run(args: list[str], timeout: float = TIMEOUT) -> str:
    try:
        return subprocess.run(  # noqa: S603
            [_qemu_img(), *args], capture_output=True, text=True, timeout=timeout, check=True
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise QemuImgError(exc.stderr.strip() or str(exc)) from exc


def image_info(path: Path) -> dict[str, Any] | None:
    try:
        info = json.loads(_run(["info", "--output=json", "-U", str(path)]))
    except (QemuImgError, subprocess.SubprocessError, OSError, ValueError):
        return None
    return info if isinstance(info, dict) else None


def rebase_unsafe(overlay: Path, backing: Path, backing_format: str | None) -> None:
    """Point overlay at backing without touching data (the backing file only moved)."""
    args = ["rebase", "-u", "-b", str(backing)]
    if backing_format:
        args += ["-F", backing_format]
    _run([*args, str(overlay)])


def convert(src: Path, dest: Path, fmt: str) -> None:
    """Copy a disk image, keeping it sparse (no time limit: disks can be large)."""
    try:
        subprocess.run(  # noqa: S603
            [_qemu_img(), "convert", "-p", "-O", fmt, str(src), str(dest)],
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


def convert_progress(src: Path, dest: Path, fmt: str, on_progress: Callable[[float], None]) -> None:
    """convert(), telling on_progress how far it went (0 to 1).

    on_progress may raise to stop the copy: qemu-img is then ended and the
    exception goes on; the partial file is the caller's to remove.
    """
    args = [_qemu_img(), "convert", "-p", "-O", fmt, str(src), str(dest)]
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
