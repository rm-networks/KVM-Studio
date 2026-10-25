from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..context import Context
from ..events import EventHub
from ..services import clone
from ..services.tasks import Task, TaskRegistry

router = APIRouter(tags=["clone"])


class CloneRequest(BaseModel):
    kind: Literal["full", "linked"]
    name: str
    folder: str = ""


class TaskInfo(BaseModel):
    id: str
    kind: str
    state: Literal["running", "done", "failed", "cancelled"]
    progress: float
    step: str
    result: dict[str, Any]
    error_code: str | None
    error_detail: str | None


class LinkedClones(BaseModel):
    names: list[str]


def _registry(request: Request) -> TaskRegistry:
    tasks: TaskRegistry = request.app.state.tasks
    return tasks


def task_info(task: Task) -> TaskInfo:
    return TaskInfo(
        id=task.id,
        kind=task.kind,
        state=task.state,
        progress=task.progress,
        step=task.step,
        result=task.result,
        error_code=task.error_code,
        error_detail=task.error_detail,
    )


@router.post("/vms/{uuid}/clone", status_code=202)
async def start_clone(ctx: Context, request: Request, uuid: str, body: CloneRequest) -> TaskInfo:
    """Checks the request, then copies in the background: follow /tasks/{id}."""
    plan = await run_in_threadpool(
        clone.prepare, ctx.conn, ctx.config, uuid, body.kind, body.name, body.folder
    )
    hub: EventHub = request.app.state.events

    def work(task: Task) -> dict[str, Any]:
        try:
            return clone.run(ctx.conn, plan, task)
        finally:
            hub.broadcast({"type": "library.changed"})

    return task_info(_registry(request).start("clone", work))


@router.get("/vms/{uuid}/linked-clones")
async def linked_clones(ctx: Context, uuid: str) -> LinkedClones:
    return LinkedClones(names=await run_in_threadpool(clone.linked_clones, ctx.conn, uuid))


@router.get("/tasks/{task_id}")
def task(request: Request, task_id: str) -> TaskInfo:
    return task_info(_registry(request).get(task_id))


@router.post("/tasks/{task_id}/cancel")
def cancel(request: Request, task_id: str) -> TaskInfo:
    task = _registry(request).get(task_id)
    task.cancel.set()
    return task_info(task)
