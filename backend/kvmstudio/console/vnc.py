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
from lxml import etree
from starlette.concurrency import run_in_threadpool

from ..auth.roles import socket_role
from ..context import get_context
from ..errors import ApiException, classify
from ..libvirt_conn import LibvirtConnection

ACCEPTED_PROTOCOL = "binary"

ConsoleOpener = Callable[[LibvirtConnection, str], socket.socket]


def graphics_types(xml: str) -> list[str]:
    """Types of the <graphics> devices, in order ("vnc", "spice"...)."""
    root = etree.fromstring(xml.encode(), parser=etree.XMLParser(resolve_entities=False))
    return [g.get("type", "") for g in root.iterfind("devices/graphics")]


def open_vnc_socket(conn: LibvirtConnection, uuid: str) -> socket.socket:
    def op(c: libvirt.virConnect) -> int:
        dom = c.lookupByUUIDString(uuid)
        # VMs made in virt-manager often have SPICE first: pick the VNC display.
        types = graphics_types(dom.XMLDesc(0))
        if "vnc" not in types:
            raise ApiException(409, "console.no_vnc", "The virtual machine has no VNC display")
        return dom.openGraphicsFD(types.index("vnc"), libvirt.VIR_DOMAIN_OPEN_GRAPHICS_SKIPAUTH)

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
    if socket_role(websocket) is None:
        await websocket.close(code=4401)
        return
    try:
        sock = await run_in_threadpool(ctx.open_console, ctx.conn, uuid)
    except libvirt.libvirtError as exc:
        status, code = classify(exc)
        await websocket.accept(subprotocol=ACCEPTED_PROTOCOL)
        await websocket.close(code=4000 + status, reason=code)
        return
    except ApiException as exc:
        await websocket.accept(subprotocol=ACCEPTED_PROTOCOL)
        await websocket.close(code=4000 + exc.status, reason=exc.code)
        return
    await websocket.accept(subprotocol=ACCEPTED_PROTOCOL)
    _viewers(websocket, uuid, +1)
    try:
        await _pump(websocket, sock)
    finally:
        sock.close()
        _viewers(websocket, uuid, -1)


def _viewers(websocket: WebSocket, uuid: str, change: int) -> None:
    """People on the console of a VM (F-104), told to every open interface."""
    viewers: dict[str, int] = websocket.app.state.viewers
    count = max(0, viewers.get(uuid, 0) + change)
    if count:
        viewers[uuid] = count
    else:
        viewers.pop(uuid, None)
    websocket.app.state.events.broadcast({"type": "console.viewers", "uuid": uuid, "count": count})
