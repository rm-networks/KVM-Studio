"""The only things the helper can do. Each operation has its own polkit action.

prepare() checks the parameters before anyone is asked for a password and
returns the task to run once the caller is authorized.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..config import HelperConfig
from ..errors import HelperError

# Runs a listed tool: argument list, descriptors to pass. Simulated in tests.
Runner = Callable[[list[str], tuple[int, ...]], None]
Task = Callable[[Runner], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class Operation:
    action: str
    prepare: Callable[[Mapping[str, object], HelperConfig], Task]


def expect_keys(params: Mapping[str, object], keys: set[str]) -> None:
    extra = set(params) - keys
    if extra:
        raise HelperError("invalid_params", f"unexpected parameters: {', '.join(sorted(extra))}")
    missing = keys - set(params)
    if missing:
        raise HelperError("invalid_params", f"missing parameters: {', '.join(sorted(missing))}")


def registry() -> dict[str, Operation]:
    from . import iso_acl

    return {"iso_acl": Operation(iso_acl.ACTION, iso_acl.prepare)}
