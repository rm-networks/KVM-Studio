"""Web mode: the frontend is opened in the user's browser."""

from __future__ import annotations

import os
import sys
import time
import webbrowser
from pathlib import Path

import uvicorn

from ..auth.token import new_token
from ..config import Config, default_config_path, load_config, save_config
from ..frontend import find_frontend_dir
from ..i18n import t
from .backend_process import BackendError, BackendProcess
from .restart import exec_restart
from .tray import run_tray


def run(config: Config, config_path: Path | None, *, open_browser: bool, reload: bool) -> int:
    if config.web.share_on_lan:
        print(
            t("cli.share_unavailable"),
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
        print(t("cli.web_dev", url=url), flush=True)
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

    path = config_path or default_config_path()
    backend = BackendProcess(path, "web", token, port)
    try:
        backend.start()
    except BackendError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(t("cli.web_listening", port=port))
    print(t("cli.web_link", url=url), flush=True)
    if open_browser:
        # The default browser (xdg-open on Linux desktops), as if a link was clicked.
        webbrowser.open(url)

    frontend = find_frontend_dir()
    icon = frontend / "logo.png" if frontend else None
    outcome = run_tray(url, icon, config.ui.language, backend.alive)
    if outcome is None:
        # No notification area (GNOME without AppIndicator, no display): just wait.
        try:
            while backend.alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            outcome = "quit"
        else:
            outcome = "backend_exited"

    if outcome == "desktop":
        switch_to_desktop(path)
        backend.stop()
        exec_restart()
    restart = outcome == "backend_exited" and backend.wants_restart()
    backend.stop()
    if restart:
        exec_restart()
    return 0


def switch_to_desktop(config_path: Path) -> None:
    """Save interface mode = desktop, as Preferences would."""
    config = load_config(config_path)
    config.interface.mode = "desktop"
    save_config(config, config_path)
