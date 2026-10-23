"""qemu-img, called with argument lists only (never through a shell)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

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
