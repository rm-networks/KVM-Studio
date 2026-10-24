from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response
from lxml import etree
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import helper_client
from ..context import Context
from ..errors import ApiException
from ..isolib import access, scan
from ..paths import confine, in_iso_library
from ..services import hardware

router = APIRouter(tags=["isos"])


class IsoLibraryStatus(BaseModel):
    name: str
    path: str
    available: bool


class IsoFile(BaseModel):
    library: str
    path: str
    relative: str
    size: int
    mtime: float


class IsoListing(BaseModel):
    libraries: list[IsoLibraryStatus]
    isos: list[IsoFile]


class AccessProblem(BaseModel):
    kind: access.Problem
    path: str


class AccessReport(BaseModel):
    path: str
    identity: str | None
    readable: bool
    problems: list[AccessProblem]
    commands: list[str]


class AccessFix(BaseModel):
    path: str


class CdromDevice(BaseModel):
    target: str
    bus: str
    path: str | None


class MediaChange(BaseModel):
    path: str | None


@router.get("/isos")
async def list_isos(ctx: Context) -> IsoListing:
    statuses, files = await run_in_threadpool(scan.scan, ctx.config)
    return IsoListing(
        libraries=[
            IsoLibraryStatus(name=s.name, path=s.path, available=s.available) for s in statuses
        ],
        isos=[
            IsoFile(library=f.library, path=f.path, relative=f.relative, size=f.size, mtime=f.mtime)
            for f in files
        ],
    )


def _qemu_identity(ctx: Context) -> access.Identity | None:
    # A session connection runs QEMU as the user: no other identity to test.
    if ctx.config.libvirt.uri.rstrip("/").endswith("/session"):
        return None
    return access.qemu_identity(ctx.conn.run(lambda c: c.getCapabilities()))


def _report(ctx: Context, path: str) -> AccessReport:
    target = confine(path, ctx.config)
    report = access.check(str(target), _qemu_identity(ctx))
    return AccessReport(
        path=report.path,
        identity=report.identity,
        readable=report.readable,
        problems=[AccessProblem(kind=k, path=p) for k, p in report.problems],
        commands=report.commands,
    )


@router.get("/isos/access")
async def check_access(ctx: Context, path: Annotated[str, Query()]) -> AccessReport:
    return await run_in_threadpool(_report, ctx, path)


@router.post("/isos/access/fix")
async def fix_access(ctx: Context, body: AccessFix) -> AccessReport:
    """Ask the helper to add the ACLs QEMU needs inside the ISO library."""

    def run() -> AccessReport:
        if not in_iso_library(body.path, ctx.config):
            raise ApiException(403, "path.not_allowed", f"{body.path} is not in an ISO library")
        helper_client.call("iso_acl", {"path": str(confine(body.path, ctx.config))})
        return _report(ctx, body.path)

    return await run_in_threadpool(run)


def _cdroms(xml: str) -> list[tuple[etree._Element, CdromDevice]]:
    root = etree.fromstring(xml.encode(), parser=etree.XMLParser(resolve_entities=False))
    found = []
    for disk in root.iterfind("devices/disk[@device='cdrom']"):
        target = disk.find("target")
        source = disk.find("source")
        found.append(
            (
                disk,
                CdromDevice(
                    target=target.get("dev", "") if target is not None else "",
                    bus=target.get("bus", "") if target is not None else "",
                    path=source.get("file") if source is not None else None,
                ),
            )
        )
    return found


@router.get("/vms/{uuid}/cdroms")
async def list_cdroms(ctx: Context, uuid: str) -> list[CdromDevice]:
    xml = await run_in_threadpool(ctx.conn.run, lambda c: c.lookupByUUIDString(uuid).XMLDesc(0))
    return [device for _el, device in _cdroms(xml)]


@router.put("/vms/{uuid}/cdroms/{target}", status_code=204)
async def change_media(ctx: Context, uuid: str, target: str, body: MediaChange) -> Response:
    """Insert, change or eject the ISO of a CD/DVD drive, live and in the config."""

    def run() -> None:
        # ISO images come from the declared libraries only (rule 5).
        path = str(confine(body.path, ctx.config)) if body.path else None
        if path is not None and not in_iso_library(path, ctx.config):
            raise ApiException(403, "path.not_allowed", f"{path} is not in an ISO library")

        hardware.set_media(ctx.conn, uuid, target, path)

    await run_in_threadpool(run)
    return Response(status_code=204)
