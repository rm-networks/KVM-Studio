"""Loopback clients of another account are refused, the token alone is not enough."""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Iterator, MutableMapping
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kvmstudio.auth.peer import LocalUserCheck, peer_uid
from kvmstudio.auth.token import LinkCodes

from .conftest import TOKEN
from .helpers import AUTH

HEADER = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid\n"


@pytest.fixture
def connection() -> Iterator[tuple[tuple[str, int], tuple[str, int]]]:
    """A real loopback TCP connection: (client address, server address)."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    client = socket.create_connection(server.getsockname())
    accepted, address = server.accept()
    yield address, server.getsockname()
    for s in (accepted, client, server):
        s.close()


def test_the_kernel_tells_the_owner_of_a_client(
    connection: tuple[tuple[str, int], tuple[str, int]],
) -> None:
    client, server = connection
    assert peer_uid(client, server) == os.getuid()
    # The server's own end is not the client's.
    assert peer_uid(server, (client[0], 1)) is None


def test_ipv4_and_ipv6_tables(tmp_path: Path) -> None:
    tcp = tmp_path / "tcp"
    tcp.write_text(
        HEADER
        + "   0: 0100007F:D431 0100007F:EAF0 01 00000000:00000000 00:00000000 00000000  1001 0 1\n"
    )
    tcp6 = tmp_path / "tcp6"
    tcp6.write_text(
        HEADER + "   0: 00000000000000000000000001000000:D432 "
        "00000000000000000000000001000000:EAF0 01 00000000:00000000 00:00000000 00000000"
        "  1002 0 2\n"
    )
    tables = (tcp, tcp6)
    assert peer_uid(("127.0.0.1", 0xD431), ("127.0.0.1", 60144), tables) == 1001
    assert peer_uid(("::1", 0xD432), ("::1", 60144), tables) == 1002
    assert peer_uid(("127.0.0.1", 0xD433), ("127.0.0.1", 60144), tables) is None


def call(middleware: LocalUserCheck, scope: dict[str, Any]) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b""}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(dict(message))

    asyncio.run(middleware(scope, receive, send))
    return sent


async def reached(_scope: Any, _receive: Any, send: Any) -> None:
    await send({"type": "reached"})


@pytest.mark.parametrize("kind", ["http", "websocket"])
def test_another_account_is_refused(
    connection: tuple[tuple[str, int], tuple[str, int]], kind: str
) -> None:
    client, server = connection
    scope = {"type": kind, "client": client, "server": server, "path": "/", "headers": []}
    mine = call(LocalUserCheck(reached), scope)
    assert mine == [{"type": "reached"}]
    other = call(LocalUserCheck(reached, uid=os.getuid() + 1), scope)
    assert {"type": "reached"} not in other
    if kind == "http":
        assert other[0]["status"] == 403
    else:
        assert other == [{"type": "websocket.close", "code": 1008}]


def test_an_unknown_account_falls_back_on_the_token(caplog: pytest.LogCaptureFixture) -> None:
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 2),
        "path": "/",
        "headers": [],
    }
    assert call(LocalUserCheck(reached, uid=os.getuid() + 1), scope) == [{"type": "reached"}]
    assert "unknown" in caplog.text


def test_link_codes_are_single_use_and_short_lived() -> None:
    now = [0.0]
    codes = LinkCodes(clock=lambda: now[0])
    first = codes.new(30)
    assert codes.redeem(first)
    assert not codes.redeem(first)
    late = codes.new(30)
    now[0] = 31
    assert not codes.redeem(late)
    assert not codes.redeem("made-up")


def test_a_link_code_is_traded_for_the_token(client: TestClient) -> None:
    assert client.post("/api/auth/link", json={}).status_code == 401
    code = client.post("/api/auth/link", headers=AUTH, json={"purpose": "open"}).json()["code"]
    assert TOKEN not in code
    assert client.post("/api/auth/redeem", json={"code": code}).json() == {"token": TOKEN}
    again = client.post("/api/auth/redeem", json={"code": code})
    assert again.status_code == 401
