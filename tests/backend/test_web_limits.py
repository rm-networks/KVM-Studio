"""Limits of the web server: login attempts, request sizes, origins, headers."""

from __future__ import annotations

import asyncio
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from kvmstudio.api import auth as auth_api
from kvmstudio.app import create_app
from kvmstudio.auth import guest
from kvmstudio.auth.guest import MAX_CHECKS, GuestSessions, LoginLimiter
from kvmstudio.auth.roles import Sharing
from kvmstudio.config import Config
from kvmstudio.libvirt_conn import LibvirtConnection
from kvmstudio.limits import SocketLimit

from .conftest import TOKEN

PASSWORD = "correct horse"
LAN = "https://192.168.1.20:60443"


@pytest.fixture
def lan_app(config: Config, conn: LibvirtConnection, frontend_dir: Path) -> FastAPI:
    guest.set_password(PASSWORD)
    sharing = Sharing(https_port=60443, sessions=GuestSessions(), limiter=LoginLimiter(5))
    return create_app(config, conn, TOKEN, mode="web", frontend_dir=frontend_dir, sharing=sharing)


@pytest.fixture
def client_app(config: Config, conn: LibvirtConnection, frontend_dir: Path) -> FastAPI:
    return create_app(config, conn, TOKEN, mode="web", frontend_dir=frontend_dir)


def lan_client(app: FastAPI, address: str = "192.168.1.30") -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=(address, 50000))
    return httpx.AsyncClient(transport=transport, base_url=LAN)


def test_attempts_are_counted_before_the_check() -> None:
    limiter = LoginLimiter(5)
    results: list[int] = []
    threads = [
        threading.Thread(target=lambda: results.append(limiter.reserve("a"))) for _ in range(200)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(0) == 5


def test_old_addresses_are_forgotten() -> None:
    now = [0.0]
    limiter = LoginLimiter(5, lockout=60, max_addresses=100, clock=lambda: now[0])
    for i in range(500):
        limiter.reserve(f"10.0.{i // 250}.{i % 250}")
    assert limiter.tracked() <= 100
    now[0] = 61
    limiter.reserve("10.9.9.9")
    assert limiter.tracked() == 1


def test_simultaneous_logins_check_five_passwords_at_most(
    lan_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    checked = 0
    running = 0
    most = 0
    lock = threading.Lock()

    def slow_check(_password: str, _path: Any = None) -> bool:
        nonlocal checked, running, most
        with lock:
            checked += 1
            running += 1
            most = max(most, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return False

    monkeypatch.setattr(auth_api, "check_password", slow_check)

    async def burst() -> Counter[int]:
        async with lan_client(lan_app) as client:
            answers = await asyncio.gather(
                *(client.post("/api/auth/login", json={"password": "nope"}) for _ in range(200))
            )
        return Counter(a.status_code for a in answers)

    statuses = asyncio.run(burst())
    assert checked <= 5
    assert most <= MAX_CHECKS
    assert statuses[401] == checked
    assert statuses[429] == 200 - checked


MIB = 1024 * 1024


def test_a_huge_login_is_refused_before_it_is_read(lan_app: FastAPI) -> None:
    sent = 0

    async def body() -> Any:
        nonlocal sent
        for _ in range(400):
            sent += 1
            yield b"x" * MIB

    async def post() -> tuple[int, int]:
        async with lan_client(lan_app) as client:
            streamed = await client.post("/api/auth/login", content=body())
            announced = await client.post(
                "/api/auth/login",
                content=b"{}",
                headers={"Content-Length": str(400 * MIB)},
            )
        return streamed.status_code, announced.status_code

    assert asyncio.run(post()) == (413, 413)
    assert sent <= 2  # refused at the first chunk past 64 KiB, not after 400 MiB


def test_the_owner_may_send_more(client_app: FastAPI) -> None:
    async def post(size: int) -> int:
        transport = httpx.ASGITransport(app=client_app, client=("127.0.0.1", 1))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as c:
            answer = await c.post(
                "/api/networks/import",
                content=b" " * size,
                headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            )
        return answer.status_code

    assert asyncio.run(post(MIB)) == 422  # read, then found not to be JSON
    assert asyncio.run(post(9 * MIB)) == 413
    with_bad_token = httpx.ASGITransport(app=client_app, client=("127.0.0.1", 1))

    async def anonymous() -> int:
        async with httpx.AsyncClient(transport=with_bad_token, base_url="http://127.0.0.1") as c:
            return (await c.post("/api/networks/import", content=b" " * MIB)).status_code

    assert asyncio.run(anonymous()) == 413


def test_websockets_per_session_are_capped() -> None:
    release = asyncio.Event()

    async def app(_scope: Any, _receive: Any, _send: Any) -> None:
        await release.wait()

    limit = SocketLimit(app, limit=3)
    closed: list[Any] = []

    async def connect() -> None:
        async def receive() -> dict[str, Any]:
            return {"type": "websocket.connect"}

        async def send(message: Any) -> None:
            closed.append(message)

        scope = {
            "type": "websocket",
            "headers": [(b"cookie", b"kvmstudio_session=abc")],
            "client": ("192.168.1.30", 1),
        }
        await limit(scope, receive, send)

    async def run() -> None:
        tasks = [asyncio.create_task(connect()) for _ in range(5)]
        await asyncio.sleep(0.05)
        assert sum(limit.open.values()) == 3
        assert closed == [{"type": "websocket.close", "code": 1008}] * 2
        release.set()
        await asyncio.gather(*tasks)
        assert not limit.open

    asyncio.run(run())


def test_security_headers_and_no_public_schema(lan_app: FastAPI, client_app: FastAPI) -> None:
    async def get(app: FastAPI, base: str, path: str) -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=("192.168.1.30", 1))
        async with httpx.AsyncClient(transport=transport, base_url=base) as c:
            return await c.get(path)

    lan = asyncio.run(get(lan_app, LAN, "/"))
    assert "frame-ancestors 'none'" in lan.headers["content-security-policy"]
    assert "script-src 'self'" in lan.headers["content-security-policy"]
    assert lan.headers["x-content-type-options"] == "nosniff"
    assert lan.headers["referrer-policy"] == "no-referrer"
    assert lan.headers["strict-transport-security"].startswith("max-age=")
    local = asyncio.run(get(client_app, "http://127.0.0.1", "/"))
    assert "content-security-policy" in local.headers
    assert "strict-transport-security" not in local.headers
    assert asyncio.run(get(lan_app, LAN, "/openapi.json")).status_code in (404, 405)
