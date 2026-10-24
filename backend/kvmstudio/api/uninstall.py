from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import helper_client
from ..context import Context
from ..errors import ApiException
from ..services import uninstall
from .library import VmDeletion
from .vms import KeptFile

router = APIRouter(prefix="/uninstall", tags=["uninstall"])


class NetworkRemoval(BaseModel):
    name: str
    bridge: str
    used_by_kept: list[str]
    used_by_deleted: list[str]


class UninstallPlan(BaseModel):
    plan_id: str
    library_root: str | None
    vms: list[VmDeletion]
    running: list[str]
    kept_vms: list[str]
    extra_files: list[str]
    keep: list[KeptFile]
    networks: list[NetworkRemoval]
    settings: list[str]
    # False when running from the sources: no package to remove.
    packaged: bool


class UninstallRequest(BaseModel):
    plan_id: str
    delete_vms: bool
    delete_networks: bool
    delete_settings: bool


class UninstallReport(BaseModel):
    deleted_vms: list[str]
    failed_files: list[str]
    deleted_networks: list[str]
    kept_networks: list[str]
    deleted_settings: bool


class PackageState(BaseModel):
    packaged: bool
    present: bool


def _model(p: uninstall.UninstallPlan) -> UninstallPlan:
    return UninstallPlan(
        plan_id=p.plan_id,
        library_root=p.library_root,
        vms=[
            VmDeletion(
                uuid=v.uuid,
                name=v.name,
                delete=v.delete,
                keep=[KeptFile(path=k.path, reason=k.reason) for k in v.keep],
            )
            for v in p.vms
        ],
        running=p.running,
        kept_vms=p.kept_vms,
        extra_files=p.extra_files,
        keep=[KeptFile(path=k.path, reason=k.reason) for k in p.keep],
        networks=[
            NetworkRemoval(
                name=n.name,
                bridge=n.bridge,
                used_by_kept=n.used_by_kept,
                used_by_deleted=n.used_by_deleted,
            )
            for n in p.networks
        ],
        settings=p.settings,
        packaged=uninstall.installed_from_package(),
    )


@router.get("/plan")
async def get_plan(ctx: Context) -> UninstallPlan:
    return _model(await run_in_threadpool(uninstall.plan, ctx.conn, ctx.config))


@router.post("")
async def run(ctx: Context, body: UninstallRequest) -> UninstallReport:
    """Delete what the user chose, provided the plan is still the one shown."""
    choices = uninstall.Choices(body.delete_vms, body.delete_networks, body.delete_settings)
    report = await run_in_threadpool(uninstall.execute, ctx.conn, ctx.config, choices, body.plan_id)
    return UninstallReport(
        deleted_vms=report.deleted_vms,
        failed_files=report.failed_files,
        deleted_networks=report.deleted_networks,
        kept_networks=report.kept_networks,
        deleted_settings=report.deleted_settings,
    )


@router.post("/package", status_code=202)
async def remove_package() -> PackageState:
    """Ask the helper to remove the package (administrator password asked by polkit)."""
    if not uninstall.installed_from_package():
        raise ApiException(409, "uninstall.not_packaged", "Not installed from the package")
    await run_in_threadpool(helper_client.call, "remove_package", {})
    return PackageState(packaged=True, present=uninstall.package_present())


@router.get("/package")
def package_state() -> PackageState:
    return PackageState(
        packaged=uninstall.installed_from_package(), present=uninstall.package_present()
    )
