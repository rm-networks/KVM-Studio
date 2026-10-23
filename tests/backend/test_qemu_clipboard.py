"""UTF-8 clipboard through a real QEMU VNC server and its qemu-vdagent channel.

Needs qemu-system-x86_64 and /dev/kvm, so it only runs when asked:
KVMSTUDIO_QEMU_TESTS=1 pytest tests/backend/test_qemu_clipboard.py
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from .rfb_client import (
    ACTION_CAPS,
    ACTION_NOTIFY,
    ACTION_PROVIDE,
    ACTION_REQUEST,
    FORMAT_TEXT,
    RfbClient,
)

QEMU = shutil.which("qemu-system-x86_64")

pytestmark = pytest.mark.skipif(
    os.environ.get("KVMSTUDIO_QEMU_TESTS") != "1" or QEMU is None,
    reason="set KVMSTUDIO_QEMU_TESTS=1 (needs qemu-system-x86_64)",
)

SAMPLE = "Élève à l'école : ça coûte 12 €\nZürich, Øresund, naïve, ŒUVRE, 日本語"


@pytest.fixture
def vnc_socket(tmp_path: Path) -> Iterator[Path]:
    assert QEMU is not None
    path = tmp_path / "vnc.sock"
    accel = "kvm" if os.access("/dev/kvm", os.R_OK | os.W_OK) else "tcg"
    proc = subprocess.Popen(  # noqa: S603
        [
            QEMU,
            "-machine", f"q35,accel={accel}",
            "-m", "128",
            "-nodefaults",
            "-display", "none",
            "-vnc", f"unix:{path}",
            "-chardev", "qemu-vdagent,id=vdagent,clipboard=on",
            "-device", "virtio-serial-pci",
            "-device", "virtserialport,chardev=vdagent,name=com.redhat.spice.0",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )  # fmt: skip
    try:
        for _ in range(100):
            if path.exists():
                break
            if proc.poll() is not None:
                pytest.fail(f"qemu exited: {proc.stderr.read().decode() if proc.stderr else ''}")
            time.sleep(0.05)
        yield path
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def connect(path: Path) -> RfbClient:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(path))
    client = RfbClient(sock)
    flags, _ = client.read_clipboard_message()
    assert flags & ACTION_CAPS, "server did not announce extended clipboard"
    assert flags & FORMAT_TEXT
    # noVNC only uses the UTF-8 path when the server can notify; otherwise it
    # falls back to Latin-1 cut text.
    assert flags & ACTION_NOTIFY
    client.send_caps()
    return client


def test_utf8_text_crosses_the_qemu_clipboard(vnc_socket: Path) -> None:
    sender = connect(vnc_socket)
    receiver = connect(vnc_socket)
    try:
        # Same sequence as noVNC: announce, then provide when QEMU asks.
        sender.notify_text()

        flags, _ = receiver.read_clipboard_message()
        assert flags & ACTION_NOTIFY
        assert flags & FORMAT_TEXT
        receiver.request_text()

        flags, _ = sender.read_clipboard_message()
        assert flags & ACTION_REQUEST
        sender.provide_text(SAMPLE)

        flags, payload = receiver.read_clipboard_message()
        assert flags & ACTION_PROVIDE
        assert RfbClient.decode_text(payload) == SAMPLE
    finally:
        sender.close()
        receiver.close()
