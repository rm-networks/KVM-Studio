"""Graphical console: a WebSocket bridged to the domain's VNC server.

libvirt hands us a socket already connected to QEMU (virDomainOpenGraphicsFD),
so the VNC server never listens on a TCP port.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import Callable

import libvirt
from fastapi import WebSocket
from starlette.concurrency import run_in_threadpool

from ..auth.token import token_in_subprotocols
from ..context import get_context
from ..errors import classify
from ..libvirt_conn import LibvirtConnection

ACCEPTED_PROTOCOL = "binary"

ConsoleOpener = Callable[[LibvirtConnection, str], socket.socket]


def open_vnc_socket(conn: LibvirtConnection, uuid: str) -> socket.socket:
    def op(c: libvirt.virConnect) -> int:
        dom = c.lookupByUUIDString(uuid)
        return dom.openGraphicsFD(0, libvirt.VIR_DOMAIN_OPEN_GRAPHICS_SKIPAUTH)

    return socket.socket(fileno=conn.run(op))


async def _pump(websocket: WebSocket, sock: socket.socket) -> None:
    sock.setblocking(False)
    reader, writer = await asyncio.open_connection(sock=sock)

    async def to_vm() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            data = message.get("bytes") or message.get("text", "").encode()
            writer.write(data)
            await writer.drain()

    async def to_browser() -> None:
        while chunk := await reader.read(65536):
            await websocket.send_bytes(chunk)

    tasks = [asyncio.create_task(to_vm()), asyncio.create_task(to_browser())]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    if tasks[1] in done:
        # The VM side ended (guest powered off): tell the browser.
        with contextlib.suppress(Exception):
            await websocket.close(code=1000)


async def vnc_console(websocket: WebSocket, uuid: str) -> None:
    ctx = get_context(websocket)
    if not token_in_subprotocols(websocket.scope.get("subprotocols", []), ctx.token):
        await websocket.close(code=4401)
        return
    try:
        sock = await run_in_threadpool(ctx.open_console, ctx.conn, uuid)
    except libvirt.libvirtError as exc:
        status, code = classify(exc)
        await websocket.accept(subprotocol=ACCEPTED_PROTOCOL)
        await websocket.close(code=4000 + status, reason=code)
        return
    await websocket.accept(subprotocol=ACCEPTED_PROTOCOL)
    try:
        await _pump(websocket, sock)
    finally:
        sock.close()
