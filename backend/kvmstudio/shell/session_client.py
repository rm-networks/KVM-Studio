"""The tray icon's view of running VMs, through the backend API.

The tray runs in the main process, without libvirt: it asks the backend, with
the session token, which VMs run and what to do with them before quitting or
switching to window mode.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any
from urllib.parse import urlsplit

TIMEOUT = 15.0


class SessionClient:
    def __init__(self, url: str) -> None:
        parts = urlsplit(url)
        self._base = f"{parts.scheme}://{parts.netloc}/api"
        self._token = parts.fragment.removeprefix("token=")

    def _call(self, method: str, path: str, body: Any = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(  # noqa: S310 (our own 127.0.0.1 URL)
            self._base + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:  # noqa: S310
            raw = answer.read()
        return json.loads(raw) if raw else None

    def running(self) -> list[str]:
        return [vm["name"] for vm in self._call("GET", "/session/running")]

    def workspace(self) -> dict[str, Any]:
        config = self._call("GET", "/preferences")["config"]
        return dict(config.get("workspace", {}))

    def hide_reminder(self) -> None:
        config = self._call("GET", "/preferences")["config"]
        config.setdefault("workspace", {})["close_reminder"] = False
        self._call("PUT", "/preferences", config)

    def act(self, action: str) -> list[str]:
        """suspend, shutdown or poweroff every running VM; returns the names that failed."""
        result = self._call("POST", f"/session/running/{action}")
        return [f["name"] for f in result["failed"]]
