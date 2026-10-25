from __future__ import annotations

import contextlib
import re
from typing import Annotated, Literal

import libvirt
from fastapi import APIRouter, Query, Request, Response
from pydantic import AfterValidator, BaseModel
from starlette.concurrency import run_in_threadpool

from ..context import Context
from ..errors import ApiException
from ..events import EventHub
from ..libvirt_conn import DomainState
from ..paths import is_strictly_within, library_root
from ..services import clone, deletion, library, vm_view
from ..services.library import Drift

router = APIRouter(prefix="/vms", tags=["vms"])

PowerAction = Literal["start", "shutdown", "reboot", "reset", "poweroff"]

# Names end up as folder names: no slash, no control characters, no leading dot.
_NAME_RE = re.compile(r"^(?![.\s])[^/\\\x00-\x1f\x7f]{1,64}(?<!\s)$")


def _check_name(name: str) -> str:
    if not _NAME_RE.match(name):
        raise ValueError("invalid virtual machine name")
    return name


VmName = Annotated[str, AfterValidator(_check_name)]


class VmSummary(BaseModel):
    uuid: str
    name: str
    state: DomainState
    vcpus: int
    memory_mib: int
    persistent: bool
    folder: str
    managed: bool
    drift: list[Drift]


class MoveRequest(BaseModel):
    folder: str


class ImportResult(BaseModel):
    copied: list[str]
    originals: list[str]


class VmUpdate(BaseModel):
    name: VmName


class KeptFile(BaseModel):
    path: str
    reason: deletion.KeepReason


class DeletionPlan(BaseModel):
    delete: list[str]
    keep: list[KeptFile]


class DeletionResult(BaseModel):
    deleted: list[str]
    failed: list[str]
    keep: list[KeptFile]


@router.get("")
def list_vms(ctx: Context) -> list[VmSummary]:
    return [VmSummary.model_validate(e.as_dict()) for e in vm_view.all_vms(ctx.conn, ctx.config)]


@router.post("/{uuid}/power/{action}", status_code=204)
def power(
    ctx: Context, uuid: str, action: PowerAction, force: Annotated[bool, Query()] = False
) -> Response:
    """force: start a VM even though linked clones depend on its disks."""
    if action == "start" and not force and (clones := clone.linked_clones(ctx.conn, uuid)):
        raise ApiException(
            409, "vm.has_linked_clones", "Linked clones depend on it: " + ", ".join(clones)
        )

    def op(c: libvirt.virConnect) -> None:
        dom = c.lookupByUUIDString(uuid)
        if bool(dom.isActive()) == (action == "start"):
            state = "running" if action == "start" else "not running"
            raise ApiException(409, "libvirt.invalid_state", f"The virtual machine is {state}")
        if action == "start":
            dom.create()
        elif action == "shutdown":
            dom.shutdownFlags(0)
        elif action == "reboot":
            dom.reboot(0)
        elif action == "reset":
            dom.reset(0)
        else:
            dom.destroy()

    ctx.conn.run(op)
    return Response(status_code=204)


@router.patch("/{uuid}", status_code=204)
def update(ctx: Context, uuid: str, body: VmUpdate) -> Response:
    # libvirt only renames shut-off domains and reports a clear error otherwise.
    ctx.conn.run(lambda c: c.lookupByUUIDString(uuid).rename(body.name, 0))
    return Response(status_code=204)


@router.get("/{uuid}/deletion-plan")
async def deletion_plan(ctx: Context, uuid: str) -> DeletionPlan:
    plan = await run_in_threadpool(deletion.plan_deletion, ctx.conn, uuid, ctx.config)
    return DeletionPlan(
        delete=plan.delete, keep=[KeptFile(path=k.path, reason=k.reason) for k in plan.keep]
    )


def _library_changed(request: Request) -> None:
    hub: EventHub = request.app.state.events
    hub.broadcast({"type": "library.changed"})


@router.delete("/{uuid}")
async def delete(
    ctx: Context, request: Request, uuid: str, files: Annotated[bool, Query()] = False
) -> DeletionResult:
    def run() -> tuple[deletion.DeletionPlan, deletion.DeletionReport]:
        place = library.placement_of(ctx.conn, ctx.config, uuid)
        result = deletion.delete_vm(ctx.conn, uuid, ctx.config, delete_files=files)
        root = library_root(ctx.config)
        # The VM's own folder goes too once it is empty (never a library folder).
        vm_dir = place.vm_dir
        if files and place.managed and vm_dir and root and is_strictly_within(vm_dir, root):
            with contextlib.suppress(OSError):
                vm_dir.rmdir()
        return result

    plan, report = await run_in_threadpool(run)
    _library_changed(request)
    return DeletionResult(
        deleted=report.deleted,
        failed=report.failed,
        keep=[KeptFile(path=k.path, reason=k.reason) for k in plan.keep],
    )


@router.post("/{uuid}/move", status_code=204)
async def move(ctx: Context, request: Request, uuid: str, body: MoveRequest) -> Response:
    await run_in_threadpool(library.move_vm, ctx.conn, ctx.config, uuid, body.folder)
    _library_changed(request)
    return Response(status_code=204)


@router.post("/{uuid}/import")
async def import_files(
    ctx: Context, request: Request, uuid: str, body: MoveRequest
) -> ImportResult:
    result = await run_in_threadpool(
        library.import_vm_files, ctx.conn, ctx.config, uuid, body.folder
    )
    _library_changed(request)
    return ImportResult(copied=result.copied, originals=result.originals)
