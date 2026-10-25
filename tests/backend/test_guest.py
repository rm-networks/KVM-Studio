"""Guest account of LAN sharing: login, lockout, and the rights checked on every route."""

from __future__ import annotations

import re
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIWebSocketRoute
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from kvmstudio.app import create_app
from kvmstudio.auth import guest
from kvmstudio.auth.guest import GuestSessions, LoginLimiter
from kvmstudio.auth.roles import Sharing, guest_forbidden
from kvmstudio.config import Config
from kvmstudio.libvirt_conn import LibvirtConnection

from .conftest import TOKEN

PASSWORD = "correct horse"
LAN = "https://192.168.1.20:60443"


@pytest.fixture
def sharing() -> Sharing:
    return Sharing(https_port=60443, sessions=GuestSessions(), limiter=LoginLimiter(5))


@pytest.fixture
def app_with_sharing(
    config: Config, conn: LibvirtConnection, frontend_dir: Path, sharing: Sharing
) -> FastAPI:
    return create_app(config, conn, TOKEN, mode="web", frontend_dir=frontend_dir, sharing=sharing)


@pytest.fixture
def lan(app_with_sharing: FastAPI) -> Iterator[TestClient]:
    guest.set_password(PASSWORD)
    with TestClient(app_with_sharing, base_url=LAN) as client:
        yield client


@pytest.fixture
def guest_client(lan: TestClient) -> TestClient:
    assert lan.post("/api/auth/login", json={"password": PASSWORD}).status_code == 204
    return lan


def test_password_is_stored_as_a_hash_readable_by_the_user_only() -> None:
    guest.set_password(PASSWORD)
    path = guest.hash_path()
    assert path.read_text().startswith("$argon2")
    assert PASSWORD not in path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert guest.check_password(PASSWORD)
    assert not guest.check_password("wrong")


def test_sessions_expire_after_inactivity() -> None:
    sessions = GuestSessions(idle=0.0)
    sid = sessions.open("10.0.0.2")
    assert not sessions.touch(sid)
    assert sessions.count() == 0


def test_lockout_after_too_many_failures(lan: TestClient) -> None:
    for _ in range(5):
        assert lan.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    r = lan.post("/api/auth/login", json={"password": PASSWORD})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "auth.locked"


def test_login_sets_a_secure_cookie(lan: TestClient) -> None:
    r = lan.post("/api/auth/login", json={"password": PASSWORD})
    cookie = r.headers["set-cookie"]
    for flag in ("HttpOnly", "Secure", "SameSite=strict"):
        assert flag.lower() in cookie.lower()
    assert lan.get("/api/auth/me").json() == {"role": "guest", "sharing": True}


def test_no_cookie_no_access(lan: TestClient) -> None:
    assert lan.get("/api/vms").status_code == 401


def test_login_only_on_the_lan_listener(app_with_sharing: FastAPI) -> None:
    guest.set_password(PASSWORD)
    with TestClient(app_with_sharing, base_url="http://127.0.0.1") as local:
        assert local.post("/api/auth/login", json={"password": PASSWORD}).status_code == 404


def test_guest_manages_vms(guest_client: TestClient) -> None:
    assert guest_client.get("/api/vms").status_code == 200
    assert guest_client.get("/api/networks").status_code == 200
    assert guest_client.get("/api/info").status_code == 200


def _forbidden_routes(app: FastAPI) -> list[tuple[str, str]]:
    found = []
    for route in app.routes:
        # HTTP routes, whatever class the FastAPI version gives them.
        methods = getattr(route, "methods", None)
        if methods:
            path = re.sub(r"\{[^}]+\}", "x", getattr(route, "path", ""))
            found += [(m, path) for m in sorted(methods) if guest_forbidden(m, path)]
    return found


def test_the_forbidden_list_covers_the_host(app_with_sharing: FastAPI) -> None:
    paths = {p for _m, p in _forbidden_routes(app_with_sharing)}
    for expected in (
        "/api/preferences",
        "/api/networks/x",
        "/api/networks/export",
        "/api/isos/access/fix",
        "/api/sharing",
        "/api/sharing/password",
        "/api/uninstall",
        "/api/restart",
        "/api/setup",
        "/api/vms/x/import",
    ):
        assert expected in paths


def test_every_forbidden_route_answers_403(
    guest_client: TestClient, app_with_sharing: FastAPI
) -> None:
    routes = _forbidden_routes(app_with_sharing)
    assert len(routes) > 20
    for method, path in routes:
        r = guest_client.request(method, path, json={})
        assert r.status_code == 403, (method, path, r.status_code)
        assert r.json()["error"]["code"] == "auth.guest_forbidden"


def test_guest_cards_only_on_kvmnet_networks(guest_client: TestClient) -> None:
    vm = guest_client.get("/api/vms").json()[0]["uuid"]
    r = guest_client.post(f"/api/vms/{vm}/nics", json={"network": "default", "model": "virtio"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "auth.guest_network"


def test_owner_token_only_from_this_computer(app_with_sharing: FastAPI) -> None:
    auth = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app_with_sharing, base_url=LAN, client=("192.168.1.30", 5000)) as remote:
        assert remote.get("/api/preferences", headers=auth).status_code == 401


def test_host_header_is_checked_on_the_loopback_listener(app_with_sharing: FastAPI) -> None:
    with TestClient(app_with_sharing, base_url="http://127.0.0.1") as local:
        assert local.get("/api/health", headers={"host": "evil.example"}).status_code == 400
    with TestClient(app_with_sharing, base_url=LAN) as remote:
        assert remote.get("/api/health", headers={"host": "kvm.lan:60443"}).status_code == 200


def test_owner_sets_the_guest_password_and_sees_the_state(app_with_sharing: FastAPI) -> None:
    auth = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app_with_sharing, base_url="http://127.0.0.1") as local:
        assert local.get("/api/sharing", headers=auth).json()["has_password"] is False
        r = local.put("/api/sharing/password", headers=auth, json={"password": "short"})
        assert r.status_code == 422
        r = local.put("/api/sharing/password", headers=auth, json={"password": PASSWORD})
        assert r.status_code == 204
        state = local.get("/api/sharing", headers=auth).json()
    assert (state["has_password"], state["active"], state["guests"]) == (True, True, 0)


def test_events_socket_with_the_guest_cookie(guest_client: TestClient) -> None:
    with guest_client.websocket_connect(
        "wss://192.168.1.20:60443/ws/events", subprotocols=["kvmstudio.events"]
    ) as socket:
        assert socket.accepted_subprotocol == "kvmstudio.events"


def test_events_socket_refused_without_a_cookie(lan: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        lan.websocket_connect(
            "wss://192.168.1.20:60443/ws/events", subprotocols=["kvmstudio.events"]
        ),
    ):
        pass
    assert exc.value.code == 4401


def test_websocket_routes_check_the_role(app_with_sharing: FastAPI) -> None:
    sockets = [r.path for r in app_with_sharing.routes if isinstance(r, APIWebSocketRoute)]
    assert sorted(sockets) == ["/api/vms/{uuid}/console", "/ws/events"]
