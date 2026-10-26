"""Serial console (F-63): a WebSocket bridged to the domain's console stream.

libvirt's virDomainOpenConsole gives a stream to the first serial console of
the VM. It is non-blocking and read from the libvirt event loop (already
running for the domain events); the bytes hop to the asyncio loop. Firewalls
and appliances often have no graphical display, only this.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Protocol

import libvirt
from fastapi import WebSocket
from lxml import etree
from starlette.concurrency import run_in_threadpool

from ..auth.roles import socket_role
from ..context import get_context
from ..errors import ApiException, classify
from ..libvirt_conn import LibvirtConnection

ACCEPTED_PROTOCOL = "binary"
CHUNK = 65536
# A full stream (guest not reading) is retried this long before giving up.
SEND_TIMEOUT = 5.0


class SerialChannel(Protocol):
    def start(self, on_data: Callable[[bytes], None], on_end: Callable[[], None]) -> None: ...
    def send(self, data: bytes) -> None: ...
    def close(self) -> None: ...


SerialOpener = Callable[[LibvirtConnection, str], SerialChannel]


def has_serial(xml: str) -> bool:
    root = etree.fromstring(xml.encode(), parser=etree.XMLParser(resolve_entities=False))
    return root.find("devices/console") is not None or root.find("devices/serial") is not None


class LibvirtSerial:
    def __init__(self, stream: libvirt.virStream) -> None:
        self._stream = stream
        self._closed = False

    def start(self, on_data: Callable[[bytes], None], on_end: Callable[[], None]) -> None:
        def readable(stream: libvirt.virStream, events: int, _opaque: object) -> None:
            if events & (libvirt.VIR_STREAM_EVENT_ERROR | libvirt.VIR_STREAM_EVENT_HANGUP):
                on_end()
                return
            try:
                while True:
                    data = stream.recv(CHUNK)
                    if isinstance(data, int):  # -2: nothing more for now
                        return
                    if not data:  # end of stream
                        on_end()
                        return
                    on_data(data)
            except libvirt.libvirtError:
                on_end()

        mask = (
            libvirt.VIR_STREAM_EVENT_READABLE
            | libvirt.VIR_STREAM_EVENT_ERROR
            | libvirt.VIR_STREAM_EVENT_HANGUP
        )
        self._stream.eventAddCallback(mask, readable, None)

    def send(self, data: bytes) -> None:
        deadline = time.monotonic() + SEND_TIMEOUT
        while data:
            sent = self._stream.send(data)
            if sent == -2:
                if time.monotonic() > deadline:
                    raise ApiException(504, "serial.stalled", "The serial console does not read")
                time.sleep(0.01)
                continue
            data = data[sent:]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(libvirt.libvirtError):
            self._stream.eventRemoveCallback()
        with contextlib.suppress(libvirt.libvirtError):
            self._stream.abort()


def open_libvirt_serial(conn: LibvirtConnection, uuid: str) -> SerialChannel:
    def op(c: libvirt.virConnect) -> SerialChannel:
        dom = c.lookupByUUIDString(uuid)
        if not has_serial(dom.XMLDesc(0)):
            raise ApiException(409, "serial.none", "The virtual machine has no serial console")
        stream = c.newStream(libvirt.VIR_STREAM_NONBLOCK)
        # Without FORCE: a console already open elsewhere (virsh console) is
        # reported, not taken away.
        dom.openConsole(None, stream, 0)
        return LibvirtSerial(stream)

    return conn.run(op)


async def serial_console(websocket: WebSocket, uuid: str) -> None:
    ctx = get_context(websocket)
    if socket_role(websocket) is None:
        await websocket.close(code=4401)
        return
    try:
        channel = await run_in_threadpool(ctx.open_serial, ctx.conn, uuid)
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

    loop = asyncio.get_running_loop()
    incoming: asyncio.Queue[bytes | None] = asyncio.Queue()

    def on_data(data: bytes | None) -> None:
        loop.call_soon_threadsafe(incoming.put_nowait, data)

    channel.start(on_data, lambda: on_data(None))

    async def to_vm() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            data = message.get("bytes") or message.get("text", "").encode()
            await run_in_threadpool(channel.send, data)

    async def to_browser() -> None:
        while (chunk := await incoming.get()) is not None:
            await websocket.send_bytes(chunk)

    tasks = [asyncio.create_task(to_vm()), asyncio.create_task(to_browser())]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    await run_in_threadpool(channel.close)
    if tasks[1] in done:
        # The VM side ended (guest powered off): tell the browser.
        with contextlib.suppress(Exception):
            await websocket.close(code=1000)
