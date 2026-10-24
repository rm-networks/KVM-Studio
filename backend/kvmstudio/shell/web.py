"""Web mode: the frontend is opened in the user's browser."""

from __future__ import annotations

import os
import sys
import time
import webbrowser
from pathlib import Path

import uvicorn

from ..auth.token import new_token
from ..config import Config, default_config_path
from .backend_process import BackendError, BackendProcess


def run(config: Config, config_path: Path | None, *, open_browser: bool, reload: bool) -> int:
    if config.web.share_on_lan:
        print(
            "share_on_lan is not available yet (planned for V1). "
            "Set [web] share_on_lan = false in the configuration.",
            file=sys.stderr,
        )
        return 2

    port = config.web.port
    token = new_token()
    url = f"http://127.0.0.1:{port}/#token={token}"

    if reload:
        # Uvicorn re-imports the app in a child process: pass what it needs by env.
        os.environ["KVMSTUDIO_TOKEN"] = token
        if config_path is not None:
            os.environ["KVMSTUDIO_CONFIG"] = str(config_path)
        print(f"KVM Studio (development): {url}", flush=True)
        uvicorn.run(
            "kvmstudio.app:create_app_from_env",
            factory=True,
            host="127.0.0.1",
            port=port,
            reload=True,
            ws="websockets-sansio",
            reload_dirs=[str(Path(__file__).resolve().parents[1])],
        )
        return 0

    backend = BackendProcess(config_path or default_config_path(), "web", token, port)
    try:
        backend.start()
    except BackendError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"KVM Studio is listening on 127.0.0.1:{port}")
    print(f"Open this link (it contains the session token): {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        while backend.alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        backend.stop()
    return 0
