"""Browse buttons of a web browser: folders and disk images (services.browse)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..context import Context
from ..services import browse

router = APIRouter(prefix="/files", tags=["files"])


class FileEntry(BaseModel):
    name: str
    path: str
    folder: bool
    size: int


class Place(BaseModel):
    kind: str
    path: str


class FileListing(BaseModel):
    path: str
    parent: str | None
    entries: list[FileEntry]
    places: list[Place]
    truncated: bool


@router.get("")
async def list_files(
    ctx: Context,
    request: Request,
    path: Annotated[str | None, Query()] = None,
    kind: Annotated[browse.Kind, Query()] = "disk",
) -> FileListing:
    confined = getattr(request.state, "role", "owner") == "guest"
    found = await run_in_threadpool(browse.listing, ctx.config, path, kind, confined=confined)
    return FileListing(
        path=found.path,
        parent=found.parent,
        entries=[
            FileEntry(name=e.name, path=e.path, folder=e.folder, size=e.size) for e in found.entries
        ],
        places=[Place(kind=k, path=p) for k, p in found.places],
        truncated=found.truncated,
    )
