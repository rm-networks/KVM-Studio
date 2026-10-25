from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..auth import guest
from ..config import Config, save_config
from ..context import Context
from ..errors import ApiException
from ..paths import library_root
from ..services import iso_libraries

router = APIRouter(prefix="/preferences", tags=["preferences"])


class Preferences(BaseModel):
    config: Config
    config_path: str | None
    library_root: str | None
    # Folders the helper can fix the rights of; None when it does not answer.
    iso_declared: list[str] | None


class NewIsoLibrary(BaseModel):
    name: str = Field(min_length=1)
    path: str
    recursive: bool = True


class IsoLibraryRef(BaseModel):
    path: str


class IsoLibraryChange(BaseModel):
    config: Config
    # False when the helper did not answer: browsing works, fixing rights does not.
    declared: bool
    removed_acls: list[str]


class SaveResult(BaseModel):
    restart_required: bool
    library_root: str | None


def _check(new: Config) -> None:
    if new.web.share_on_lan and not guest.has_password():
        raise ApiException(
            422, "prefs.share_needs_password", "Set the guest password before sharing on the LAN"
        )
    if new.web.share_on_lan and new.web.https_port == new.web.port:
        raise ApiException(422, "prefs.share_same_port", "HTTPS needs a port of its own")
    location = new.storage.vm_default_location
    if location is not None:
        if not location.is_absolute():
            raise ApiException(422, "prefs.location_relative", f"{location} is not absolute")
        if not location.is_dir():
            raise ApiException(422, "prefs.location_missing", f"{location} does not exist")
    for lib in new.iso_libraries:
        if not lib.path.is_absolute() or not lib.path.is_dir():
            raise ApiException(422, "prefs.iso_missing", f"{lib.path} is not a folder")


def _prepare_library(new: Config) -> None:
    """Create <location>/KVM-Studio/VM now, so a permission problem shows up here."""
    root = library_root(new)
    if root is None:
        return
    try:
        root.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise ApiException(
            409,
            "prefs.location_not_writable",
            f"Cannot create {root}: the folder must be writable by your account",
        ) from exc


@router.get("")
async def get(ctx: Context) -> Preferences:
    root = library_root(ctx.config)
    return Preferences(
        config=ctx.config,
        config_path=str(ctx.config_path) if ctx.config_path else None,
        library_root=str(root) if root else None,
        iso_declared=await run_in_threadpool(iso_libraries.declared_paths),
    )


def _change(ctx: Context, change: iso_libraries.Change) -> IsoLibraryChange:
    ctx.config = change.config
    return IsoLibraryChange(
        config=change.config, declared=change.declared, removed_acls=change.removed_acls
    )


@router.post("/iso-libraries")
async def add_iso_library(ctx: Context, body: NewIsoLibrary) -> IsoLibraryChange:
    """Declare a folder to the helper (administrator password), then keep it."""

    def run() -> IsoLibraryChange:
        change = iso_libraries.add(
            ctx.config, ctx.config_path, body.name, Path(body.path), body.recursive
        )
        return _change(ctx, change)

    return await run_in_threadpool(run)


@router.post("/iso-libraries/remove")
async def remove_iso_library(ctx: Context, body: IsoLibraryRef) -> IsoLibraryChange:
    """Forget a library; the helper takes back the rights it gave QEMU there."""

    def run() -> IsoLibraryChange:
        return _change(ctx, iso_libraries.remove(ctx.config, ctx.config_path, Path(body.path)))

    return await run_in_threadpool(run)


@router.put("")
async def save(ctx: Context, body: Config) -> SaveResult:
    def run() -> SaveResult:
        if not iso_libraries.same_folders(ctx.config, body):
            raise ApiException(
                409, "prefs.iso_through_helper", "ISO libraries are added and removed one by one"
            )
        _check(body)
        _prepare_library(body)
        old = ctx.config
        if ctx.config_path is not None:
            save_config(body, ctx.config_path)
        ctx.config = body
        # The window, the web server and the libvirt link are set up at start.
        restart = (
            old.interface.mode != body.interface.mode
            or old.web.port != body.web.port
            or old.web.share_on_lan != body.web.share_on_lan
            or old.web.https_port != body.web.https_port
            or old.libvirt.uri != body.libvirt.uri
        )
        root = library_root(body)
        return SaveResult(restart_required=restart, library_root=str(root) if root else None)

    return await run_in_threadpool(run)
