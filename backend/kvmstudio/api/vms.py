from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..context import Context
from ..libvirt_conn import DomainState

router = APIRouter(prefix="/vms", tags=["vms"])


class VmSummary(BaseModel):
    uuid: str
    name: str
    state: DomainState
    vcpus: int
    memory_mib: int
    persistent: bool


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
