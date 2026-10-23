"""Web mode: the frontend is opened in the user's browser."""

from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path

import uvicorn

from ..app import create_app, find_frontend_dir
from ..auth.token import new_token
from ..config import Config
from ..libvirt_conn import LibvirtConnection
from .server import BackgroundServer, PortInUseError, bind_loopback


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
            reload_dirs=[str(Path(__file__).resolve().parents[1])],
        )
        return 0

    try:
        sock = bind_loopback(port)
    except PortInUseError as exc:
        print(f"{exc}. Change [web] port in the configuration.", file=sys.stderr)
        return 1

    conn = LibvirtConnection(config.libvirt.uri)
    app = create_app(config, conn, token, mode="web", frontend_dir=find_frontend_dir())
    server = BackgroundServer(app, sock)
    server.start()
    print(f"KVM Studio is listening on 127.0.0.1:{port}")
    print(f"Open this link (it contains the session token): {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        conn.close()
    return 0
