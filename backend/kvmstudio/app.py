"""FastAPI application: JSON API under /api, built frontend everywhere else."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import libvirt
from fastapi import APIRouter, Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .api import system, vms
from .auth.token import require_token
from .config import Config, load_config
from .console.vnc import ConsoleOpener, open_vnc_socket, vnc_console
from .context import AppContext, Mode
from .errors import (
    ApiError,
    ApiException,
    api_exception_handler,
    libvirt_error_handler,
    validation_error_handler,
)
from .events import EventHub, events_socket
from .libvirt_conn import LibvirtConnection

# Only loopback names are accepted, which defeats DNS rebinding.
LOOPBACK_HOSTS = ["127.0.0.1", "localhost"]

_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ApiError},
    403: {"model": ApiError},
    404: {"model": ApiError},
    409: {"model": ApiError},
    500: {"model": ApiError},
    503: {"model": ApiError},
}


def find_frontend_dir() -> Path | None:
    """Locate the built frontend: explicit override, packaged copy, then source tree."""
    candidates = []
    if override := os.environ.get("KVMSTUDIO_FRONTEND_DIR"):
        candidates.append(Path(override))
    here = Path(__file__).resolve().parent
    candidates += [here / "static", here.parents[1] / "frontend" / "dist"]
    return next((c for c in candidates if (c / "index.html").is_file()), None)


def create_app(
    config: Config,
    conn: LibvirtConnection,
    token: str,
    mode: Mode,
    frontend_dir: Path | None = None,
    open_console: ConsoleOpener = open_vnc_socket,
) -> FastAPI:
    hub = EventHub(conn)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await hub.start()
        yield
        await hub.stop()

    app = FastAPI(
        title="KVM Studio", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan
    )
    app.state.events = hub
    app.state.context = AppContext(
        config=config, conn=conn, token=token, mode=mode, open_console=open_console
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOOPBACK_HOSTS)
    app.add_exception_handler(libvirt.libvirtError, libvirt_error_handler)
    app.add_exception_handler(ApiException, api_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    public = APIRouter(prefix="/api")
    public.add_api_route("/health", system.health, methods=["GET"], tags=["system"])

    private = APIRouter(
        prefix="/api", dependencies=[Depends(require_token)], responses=_ERROR_RESPONSES
    )
    private.add_api_route("/info", system.info, methods=["GET"], tags=["system"])
    private.include_router(vms.router)

    app.include_router(public)
    app.include_router(private)
    # WebSockets check the token themselves (see console.vnc).
    app.add_api_websocket_route("/api/vms/{uuid}/console", vnc_console)
    app.add_api_websocket_route("/ws/events", events_socket)

    if frontend_dir is not None:
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    else:

        @app.get("/", include_in_schema=False)
        def frontend_missing() -> PlainTextResponse:
            return PlainTextResponse(
                "The frontend is not built. Run `npm run build` in frontend/.", status_code=503
            )

    return app


def create_app_from_env() -> FastAPI:
    """Factory used by `kvm-studio --mode web --reload`, which re-imports the app."""
    config_path = os.environ.get("KVMSTUDIO_CONFIG")
    config = load_config(Path(config_path) if config_path else None)
    return create_app(
        config,
        LibvirtConnection(config.libvirt.uri),
        token=os.environ["KVMSTUDIO_TOKEN"],
        mode="web",
        frontend_dir=find_frontend_dir(),
    )
