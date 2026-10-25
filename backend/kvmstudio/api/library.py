from __future__ import annotations

from typing import Annotated

import libvirt
from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..context import Context
from ..events import EventHub
from ..paths import library_root
from ..services import folder_order, library
from .vms import KeptFile

router = APIRouter(prefix="/library", tags=["library"])


class LibraryInfo(BaseModel):
    root: str | None
    folders: list[str]
    # Display order chosen by drag and drop: parent folder -> names.
    order: dict[str, list[str]] = {}


class FolderCreate(BaseModel):
    path: str


class FolderRename(BaseModel):
    path: str
    name: str


class FolderRef(BaseModel):
    path: str


class FolderMove(BaseModel):
    path: str
    parent: str
    # Name of the folder to come before in the new parent (None: last).
    before: str | None = None


class FolderMovePlan(BaseModel):
    folder: str
    target: str
    vms: list[str]
    running: list[str]
    blockers: list[str]


class FolderOrder(BaseModel):
    parent: str
    names: list[str] = Field(max_length=1000)


class VmDeletion(BaseModel):
    uuid: str
    name: str
    delete: list[str]
    keep: list[KeptFile]


class FolderDeletionPlan(BaseModel):
    folder: str
    vms: list[VmDeletion]
    extra_files: list[str]
    keep: list[KeptFile]
    running: list[str]


class FolderDeletionResult(BaseModel):
    failed: list[str]


def _changed(request: Request) -> None:
    hub: EventHub = request.app.state.events
    hub.broadcast({"type": "library.changed"})


@router.get("")
async def info(ctx: Context) -> LibraryInfo:
    def run() -> LibraryInfo:
        xmls = ctx.conn.run(
            lambda c: [d.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE) for d in c.listAllDomains()]
        )
        places = library.placements(xmls, ctx.config)
        root = library_root(ctx.config)
        return LibraryInfo(
            root=str(root) if root else None,
            folders=library.list_folders(ctx.config, places),
            order=folder_order.load(),
        )

    return await run_in_threadpool(run)


@router.post("/folders", status_code=201)
async def create(ctx: Context, request: Request, body: FolderCreate) -> FolderRef:
    path = await run_in_threadpool(library.create_folder, ctx.config, body.path)
    _changed(request)
    return FolderRef(path=path)


@router.get("/folders/move-plan")
async def move_plan(
    ctx: Context, path: Annotated[str, Query()], parent: Annotated[str, Query()]
) -> FolderMovePlan:
    plan = await run_in_threadpool(library.plan_folder_move, ctx.conn, ctx.config, path, parent)
    return FolderMovePlan.model_validate(plan, from_attributes=True)


@router.post("/folders/move")
async def move(ctx: Context, request: Request, body: FolderMove) -> FolderRef:
    path = await run_in_threadpool(
        library.move_folder, ctx.conn, ctx.config, body.path, body.parent, body.before
    )
    _changed(request)
    return FolderRef(path=path)


@router.put("/order", status_code=204)
async def set_order(ctx: Context, request: Request, body: FolderOrder) -> Response:
    parent = library.check_folder(body.parent)
    names = [n for n in body.names if library.check_folder(n) == n and "/" not in n]
    await run_in_threadpool(folder_order.set_order, parent, names)
    _changed(request)
    return Response(status_code=204)


@router.post("/folders/rename")
async def rename(ctx: Context, request: Request, body: FolderRename) -> FolderRef:
    path = await run_in_threadpool(
        library.rename_folder, ctx.conn, ctx.config, body.path, body.name
    )
    _changed(request)
    return FolderRef(path=path)


@router.get("/folders/deletion-plan")
async def deletion_plan(ctx: Context, path: Annotated[str, Query()]) -> FolderDeletionPlan:
    plan = await run_in_threadpool(library.plan_folder_deletion, ctx.conn, ctx.config, path)
    return FolderDeletionPlan(
        folder=plan.folder,
        vms=[
            VmDeletion(
                uuid=v.uuid,
                name=v.name,
                delete=v.delete,
                keep=[KeptFile(path=k.path, reason=k.reason) for k in v.keep],
            )
            for v in plan.vms
        ],
        extra_files=plan.extra_files,
        keep=[KeptFile(path=k.path, reason=k.reason) for k in plan.keep],
        running=plan.running,
    )


@router.delete("/folders")
async def delete(
    ctx: Context, request: Request, path: Annotated[str, Query()]
) -> FolderDeletionResult:
    failed = await run_in_threadpool(library.delete_folder, ctx.conn, ctx.config, path)
    _changed(request)
    return FolderDeletionResult(failed=failed)
