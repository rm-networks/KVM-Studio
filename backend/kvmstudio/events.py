"""Live updates: libvirt domain events pushed to every open /ws/events socket.

libvirt calls us from its event-loop thread; we hop to the asyncio loop, fetch
the new state of the domain and broadcast a small JSON message:

    {"type": "vm.changed", "vm": {...VmSummary...}}
    {"type": "vm.removed", "uuid": "..."}
    {"type": "connection", "state": "lost" | "restored"}
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import asdict
from typing import Any

import libvirt
from fastapi import WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from .auth.token import offered_subprotocols, token_in_subprotocols
from .context import get_context
from .libvirt_conn import LibvirtConnection

EVENTS_PROTOCOL = "kvmstudio.events"
RECONNECT_INTERVAL = 3.0
QUEUE_SIZE = 256

Message = dict[str, Any]


class EventHub:
    def __init__(self, conn: LibvirtConnection) -> None:
        self._conn = conn
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue[Message]] = set()
        self._connected = False
        self._was_connected = False
        self._watchdog: asyncio.Task[None] | None = None
        self._pending: set[asyncio.Task[None]] = set()
        self._registrations: list[tuple[libvirt.virConnect, int]] = []
        conn.add_connect_hook(self._register)

    # Runs in whichever thread opens the connection.
    def _register(self, conn: libvirt.virConnect) -> None:
        callback_id = conn.domainEventRegisterAny(
            None, libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE, self._on_lifecycle, None
        )
        self._registrations.append((conn, callback_id))
        with contextlib.suppress(libvirt.libvirtError):
            conn.registerCloseCallback(self._on_close, None)

    # Run in the libvirt event-loop thread.
    def _on_lifecycle(
        self, _conn: libvirt.virConnect, dom: libvirt.virDomain, event: int, _detail: int, _o: Any
    ) -> None:
        self._post(dom.UUIDString(), event)

    def _on_close(self, _conn: libvirt.virConnect, _reason: int, _opaque: Any) -> None:
        self._call_soon(self._lost)

    def _post(self, uuid: str, event: int) -> None:
        self._call_soon(self._spawn, uuid, event)

    def _call_soon(self, fn: Any, *args: Any) -> None:
        loop = self._loop
        if loop is not None:
            with contextlib.suppress(RuntimeError):  # loop already closed
                loop.call_soon_threadsafe(fn, *args)

    # Asyncio side.
    def _spawn(self, uuid: str, event: int) -> None:
        task = asyncio.ensure_future(self._domain_event(uuid, event))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _domain_event(self, uuid: str, event: int) -> None:
        if event == libvirt.VIR_DOMAIN_EVENT_UNDEFINED:
            self.broadcast({"type": "vm.removed", "uuid": uuid})
            return
        try:
            summary = await run_in_threadpool(self._conn.domain_summary, uuid)
        except libvirt.libvirtError as exc:
            if exc.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                # A transient domain that stopped no longer exists.
                self.broadcast({"type": "vm.removed", "uuid": uuid})
            return
        self.broadcast({"type": "vm.changed", "vm": asdict(summary)})

    def _lost(self) -> None:
        if self._connected:
            self._connected = False
            self.broadcast({"type": "connection", "state": "lost"})

    async def _keep_connected(self) -> None:
        """Reopen the connection after a drop so events flow again."""
        while True:
            if not self._connected:
                try:
                    await run_in_threadpool(self._conn.run, lambda c: c.getLibVersion())
                except libvirt.libvirtError:
                    pass
                else:
                    self._connected = True
                    if self._was_connected:
                        self.broadcast({"type": "connection", "state": "restored"})
                    self._was_connected = True
            await asyncio.sleep(RECONNECT_INTERVAL)

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._watchdog = asyncio.create_task(self._keep_connected())

    async def stop(self) -> None:
        if self._watchdog is not None:
            self._watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watchdog
        for task in list(self._pending):
            task.cancel()
        self._loop = None
        for conn, callback_id in self._registrations:
            with contextlib.suppress(libvirt.libvirtError):
                conn.domainEventDeregisterAny(callback_id)
        self._registrations.clear()

    def subscribe(self) -> asyncio.Queue[Message]:
        queue: asyncio.Queue[Message] = asyncio.Queue(QUEUE_SIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Message]) -> None:
        self._subscribers.discard(queue)

    def broadcast(self, message: Message) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # A stalled client: make it resync instead of growing memory.
                with contextlib.suppress(asyncio.QueueEmpty):
                    while True:
                        queue.get_nowait()
                queue.put_nowait({"type": "connection", "state": "restored"})


async def events_socket(websocket: WebSocket) -> None:
    ctx = get_context(websocket)
    protocols = websocket.scope.get("subprotocols", [])
    if not token_in_subprotocols(protocols, ctx.token) or EVENTS_PROTOCOL not in (
        offered_subprotocols(protocols)
    ):
        await websocket.close(code=4401)
        return
    hub: EventHub = websocket.app.state.events
    queue = hub.subscribe()
    await websocket.accept(subprotocol=EVENTS_PROTOCOL)

    async def drain_client() -> None:
        # Nothing is expected from the client; this notices when it leaves.
        with contextlib.suppress(WebSocketDisconnect):
            while True:
                await websocket.receive_text()

    reader = asyncio.create_task(drain_client())
    try:
        while not reader.done():
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({getter, reader}, return_when=asyncio.FIRST_COMPLETED)
            if getter not in done:
                getter.cancel()
                break
            await websocket.send_text(json.dumps(getter.result()))
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(queue)
        reader.cancel()
