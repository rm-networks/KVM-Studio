"""qemu-img, called with argument lists only (never through a shell)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

QCOW2_MAGIC = b"QFI\xfb"
TIMEOUT = 30


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
