from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..context import Context
from ..services import snapshots

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


@router.get("/{uuid}/snapshots")
async def list_snapshots(ctx: Context, uuid: str) -> list[Snapshot]:
    found = await run_in_threadpool(snapshots.list_snapshots, ctx.conn, uuid)
    return [Snapshot.model_validate(s, from_attributes=True) for s in found]


@router.post("/{uuid}/snapshots", status_code=201)
async def take(ctx: Context, uuid: str, body: SnapshotCreate) -> Snapshot:
    snap = await run_in_threadpool(snapshots.take, ctx.conn, uuid, body.name, body.description)
    return Snapshot.model_validate(snap, from_attributes=True)


@router.post("/{uuid}/snapshots/{name}/revert", status_code=204)
async def revert(ctx: Context, uuid: str, name: str) -> Response:
    await run_in_threadpool(snapshots.revert, ctx.conn, uuid, name)
    return Response(status_code=204)


@router.delete("/{uuid}/snapshots/{name}", status_code=204)
async def delete(ctx: Context, uuid: str, name: str) -> Response:
    await run_in_threadpool(snapshots.delete, ctx.conn, uuid, name)
    return Response(status_code=204)
