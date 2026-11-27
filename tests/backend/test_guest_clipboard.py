"""End to end, both ways: a running Linux guest <-> QEMU vdagent <-> KVM Studio relay.

Needs a VM of qemu:///system with the QEMU guest agent, spice-vdagent, xclip
and an open X11 session of the given user; the guest clipboard is driven
through the guest agent. Run it on demand:

KVMSTUDIO_GUEST_VM=name KVMSTUDIO_GUEST_USER=user pytest tests/backend/test_guest_clipboard.py
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import time
import uuid
from typing import Any

import libvirt
import libvirt_qemu
import pytest

from kvmstudio.app import create_app
from kvmstudio.config import Config, LibvirtSettings
from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.shell.server import BackgroundServer, bind_loopback

from .rfb_client import ACTION_NOTIFY, ACTION_PROVIDE, ACTION_REQUEST, RfbClient
from .test_qemu_console import open_console

VM = os.environ.get("KVMSTUDIO_GUEST_VM", "")
USER = os.environ.get("KVMSTUDIO_GUEST_USER", "")
pytestmark = pytest.mark.skipif(
    not (VM and USER), reason="set KVMSTUDIO_GUEST_VM and KVMSTUDIO_GUEST_USER"
)
URI = "qemu:///system"


def agent(dom: libvirt.virDomain, request: dict[str, Any]) -> dict[str, Any]:
    answer = libvirt_qemu.qemuAgentCommand(dom, json.dumps(request), 10, 0)
    assert answer is not None
    result: dict[str, Any] = json.loads(answer)["return"]
    return result


def guest_shell(dom: libvirt.virDomain, script: str) -> str:
    """Run a shell script as the session user, with that session's X display."""
    env = (
        f"export DISPLAY=:0 XAUTHORITY=$(tr '\\0' '\\n' < /proc/$(pgrep -u {USER} -x plasmashell "
        f"|| pgrep -u {USER} -x gnome-shell | head -1)/environ | sed -n 's/^XAUTHORITY=//p'); "
    )
    command = f"runuser -u {USER} -- bash -c {shlex.quote(env + script)}"
    request = {
        "execute": "guest-exec",
        "arguments": {"path": "/bin/bash", "arg": ["-c", command], "capture-output": True},
    }
    pid = agent(dom, request)["pid"]
    status = {"execute": "guest-exec-status", "arguments": {"pid": pid}}
    for _ in range(100):
        answer = agent(dom, status)
        if answer["exited"]:
            return base64.b64decode(answer.get("out-data", "")).decode()
        time.sleep(0.1)
    raise TimeoutError(script)


def test_text_goes_both_ways() -> None:
    conn = LibvirtConnection(URI)
    dom = libvirt.open(URI).lookupByName(VM)
    server = BackgroundServer(
        create_app(Config(libvirt=LibvirtSettings(uri=URI)), conn, "tok", mode="web"),
        bind_loopback(0),
    )
    server.start()
    stamp = uuid.uuid4().hex[:8]
    try:
        console = open_console(server.port, "tok", dom.UUIDString())

        # Guest -> host: copied in the guest, offered then sent to the console.
        copied = f"from the guest {stamp}, été"
        xclip = "setsid xclip -selection clipboard -i >/dev/null 2>&1"
        guest_shell(dom, f"printf %s {shlex.quote(copied)} | {xclip}")
        flags, _ = console.read_clipboard_message()
        assert flags & ACTION_NOTIFY
        console.request_text()
        flags, payload = console.read_clipboard_message()
        assert flags & ACTION_PROVIDE
        assert RfbClient.decode_text(payload) == copied

        # Host -> guest, NUL-terminated as noVNC sends it: the guest gets the text only.
        pasted = f"from the host {stamp}, Grüße"
        console.notify_text()
        flags, _ = console.read_clipboard_message()
        assert flags & ACTION_REQUEST
        console.provide_text(pasted)
        for _ in range(30):
            if guest_shell(dom, "xclip -o -selection clipboard") == pasted:
                break
            time.sleep(0.2)
        assert guest_shell(dom, "xclip -o -selection clipboard") == pasted
        console.close()
    finally:
        server.stop()
        conn.close()
