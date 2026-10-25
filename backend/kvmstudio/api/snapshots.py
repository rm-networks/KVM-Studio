from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..context import Context
from ..events import EventHub
from ..services import snapshots
from ..services.tasks import Task, TaskRegistry
from .clone import TaskInfo, task_info

router = APIRouter(prefix="/vms", tags=["snapshots"])


class Snapshot(BaseModel):
    name: str
    description: str
    created: int
    state: str
    parent: str | None
    current: bool


class SnapshotCreate(BaseModel):
    name: str
    description: str = ""
    # Ignored for a powered-off VM; a running one is only snapshotted with it.
    memory: bool = True


class SnapshotLimits(BaseModel):
    running: bool
    raw_disks: list[str]
    raw_nvram: bool
    tpm: bool


@router.get("/{uuid}/snapshots")
async def list_snapshots(ctx: Context, uuid: str) -> list[Snapshot]:
    found = await run_in_threadpool(snapshots.list_snapshots, ctx.conn, uuid)
    return [Snapshot.model_validate(s, from_attributes=True) for s in found]


@router.get("/{uuid}/snapshots/limits")
async def limits(ctx: Context, uuid: str) -> SnapshotLimits:
    found = await run_in_threadpool(snapshots.limits, ctx.conn, uuid)
    return SnapshotLimits.model_validate(found, from_attributes=True)


@router.post("/{uuid}/snapshots", status_code=202)
async def take(ctx: Context, request: Request, uuid: str, body: SnapshotCreate) -> TaskInfo:
    """Checks the request, then snapshots in the background: follow /tasks/{id}."""
    name = await run_in_threadpool(
        snapshots.check_new, ctx.conn, uuid, body.name, body.description, body.memory
    )
    hub: EventHub = request.app.state.events
    registry: TaskRegistry = request.app.state.tasks

    def work(task: Task) -> dict[str, Any]:
        # Known while it runs: the interface tells which VM is busy.
        task.result = {"vm": uuid}
        try:
            return {**snapshots.take(ctx.conn, uuid, name, body.description, task), "vm": uuid}
        finally:
            hub.broadcast({"type": "snapshots.changed", "uuid": uuid})

    return task_info(registry.start("snapshot", work))


@router.post("/{uuid}/snapshots/{name}/revert", status_code=204)
async def revert(ctx: Context, uuid: str, name: str) -> Response:
    await run_in_threadpool(snapshots.revert, ctx.conn, uuid, name)
    return Response(status_code=204)


@router.delete("/{uuid}/snapshots/{name}", status_code=204)
async def delete(ctx: Context, uuid: str, name: str) -> Response:
    await run_in_threadpool(snapshots.delete, ctx.conn, uuid, name)
    return Response(status_code=204)
