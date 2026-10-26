"""Scanning a folder for virtual machines, then importing the ones picked (services.scan)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..context import Context
from ..events import EventHub
from ..services import scan

router = APIRouter(prefix="/scan", tags=["scan"])


class FoundVm(BaseModel):
    id: str
    name: str
    folder: str
    disks: list[str]
    definition: str | None
    known: str | None
    uefi: bool


class ScanChoice(BaseModel):
    id: str
    mode: scan.Mode = "keep"


class ScanRequest(BaseModel):
    path: str
    choices: list[ScanChoice]


class ScanPlan(BaseModel):
    moves: list[tuple[str, str]]


class ScanFailure(BaseModel):
    name: str
    error: str


class ScanResult(BaseModel):
    imported: list[str]
    failed: list[ScanFailure]


def _choices(body: ScanRequest) -> list[scan.Choice]:
    return [scan.Choice(c.id, c.mode) for c in body.choices]


@router.get("")
async def found(ctx: Context, path: Annotated[str, Query()]) -> list[FoundVm]:
    items = await run_in_threadpool(scan.scan, ctx.conn, path)
    return [
        FoundVm(
            id=i.id,
            name=i.name,
            folder=i.folder,
            disks=i.disks,
            definition=i.definition,
            known=i.known,
            uefi=i.uefi,
        )
        for i in items
    ]


@router.post("/plan")
async def plan(ctx: Context, body: ScanRequest) -> ScanPlan:
    moves = await run_in_threadpool(scan.plan, ctx.conn, ctx.config, body.path, _choices(body))
    return ScanPlan(moves=moves)


@router.post("/import")
async def import_vms(ctx: Context, request: Request, body: ScanRequest) -> ScanResult:
    outcome = await run_in_threadpool(
        scan.import_found, ctx.conn, ctx.config, body.path, _choices(body)
    )
    hub: EventHub = request.app.state.events
    hub.broadcast({"type": "library.changed"})
    return ScanResult(
        imported=outcome.imported,
        failed=[ScanFailure(name=n, error=e) for n, e in outcome.failed],
    )
