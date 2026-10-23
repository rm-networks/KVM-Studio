from __future__ import annotations

import re
from typing import Annotated, Literal

import libvirt
from fastapi import APIRouter, Query, Response
from pydantic import AfterValidator, BaseModel
from starlette.concurrency import run_in_threadpool

from ..context import Context
from ..errors import ApiException
from ..libvirt_conn import DomainState
from ..services import deletion

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
    return [
        VmSummary(
            uuid=d.uuid,
            name=d.name,
            state=d.state,
            vcpus=d.vcpus,
            memory_mib=d.memory_mib,
            persistent=d.persistent,
        )
        for d in ctx.conn.list_domains()
    ]


@router.post("/{uuid}/power/{action}", status_code=204)
def power(ctx: Context, uuid: str, action: PowerAction) -> Response:
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


@router.delete("/{uuid}")
async def delete(
    ctx: Context, uuid: str, files: Annotated[bool, Query()] = False
) -> DeletionResult:
    plan, report = await run_in_threadpool(
        lambda: deletion.delete_vm(ctx.conn, uuid, ctx.config, delete_files=files)
    )
    return DeletionResult(
        deleted=report.deleted,
        failed=report.failed,
        keep=[KeptFile(path=k.path, reason=k.reason) for k in plan.keep],
    )
