"""Long operations (copying disks) run in a thread the client follows and can cancel."""

from __future__ import annotations

import threading
import uuid as uuidlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from ..errors import ApiException

State = Literal["running", "done", "failed", "cancelled"]
# Finished tasks are kept a while for the client to read their outcome.
KEEP_FINISHED = 20


class Cancelled(Exception):
    """Raised inside a task when the user cancelled it."""


@dataclass(slots=True)
class Task:
    id: str
    kind: str
    state: State = "running"
    progress: float = 0.0
    step: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_detail: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)

    def report(self, progress: float, step: str | None = None) -> None:
        """Called by the work itself; stops it when the user cancelled."""
        if self.cancel.is_set():
            raise Cancelled
        self.progress = max(0.0, min(1.0, progress))
        if step is not None:
            self.step = step


Work = Callable[[Task], dict[str, Any]]


class TaskRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, work: Work) -> Task:
        task = Task(id=str(uuidlib.uuid4()), kind=kind)
        with self._lock:
            finished = [t for t in self._tasks.values() if t.state != "running"]
            for old in finished[:-KEEP_FINISHED]:
                del self._tasks[old.id]
            self._tasks[task.id] = task

        def run() -> None:
            try:
                task.result = work(task)
                task.progress = 1.0
                task.state = "done"
            except Cancelled:
                task.state = "cancelled"
            except ApiException as exc:
                task.error_code, task.error_detail = exc.code, exc.detail
                task.state = "failed"
            except Exception as exc:  # reported to the client as is
                task.error_code, task.error_detail = "task.failed", str(exc)
                task.state = "failed"

        threading.Thread(target=run, name=f"task-{kind}", daemon=True).start()
        return task

    def get(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise ApiException(404, "task.not_found", f"no task {task_id}")
        return task
