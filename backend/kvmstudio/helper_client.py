"""Client of kvmstudio-helper, the only component running as root.

The helper identifies this process by its kernel credentials and asks polkit,
which shows the authentication dialog on the desktop: a call can take as long
as the user needs to type a password.
"""

from __future__ import annotations

import json
import os
import socket
from typing import Any

from .errors import ApiException

DEFAULT_SOCKET = "/run/kvmstudio-helper.sock"
# A little more than the helper gives polkit (300 s).
TIMEOUT = 330

_STATUS = {"not_authorized": 403, "path_not_allowed": 403, "not_found": 404, "failed": 500}


def socket_path() -> str:
    return os.environ.get("KVMSTUDIO_HELPER_SOCKET", DEFAULT_SOCKET)


def call(op: str, params: dict[str, Any]) -> dict[str, Any]:
    path = socket_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(TIMEOUT)
            sock.connect(path)
            sock.sendall(json.dumps({"op": op, "params": params}).encode() + b"\n")
            line = sock.makefile("rb").readline()
    except (FileNotFoundError, ConnectionRefusedError):
        raise ApiException(503, "helper.unavailable", f"no helper listening on {path}") from None
    except OSError as exc:
        raise ApiException(503, "helper.unavailable", str(exc)) from None
    try:
        answer = json.loads(line)
    except ValueError:
        raise ApiException(502, "helper.bad_answer", "the helper sent an invalid answer") from None
    if not answer.get("ok"):
        error = str(answer.get("error", "failed"))
        raise ApiException(_STATUS.get(error, 400), f"helper.{error}", str(answer.get("message")))
    result: dict[str, Any] = answer.get("result", {})
    return result
