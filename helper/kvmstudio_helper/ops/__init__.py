"""The only things the helper can do. Each operation has its own polkit action.

prepare() checks the parameters, and the caller as the kernel reports it, before
anyone is asked for a password. It returns the task to run once authorized.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..config import HelperConfig
from ..errors import HelperError
from ..polkit import Peer

# Runs a listed tool: argument list, descriptors to pass. Simulated in tests.
Runner = Callable[[list[str], tuple[int, ...]], None]
Task = Callable[[Runner], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class Operation:
    # None for the one read-only operation, which changes nothing.
    action: str | None
    prepare: Callable[[Mapping[str, object], HelperConfig, Peer], Task]


def expect_keys(params: Mapping[str, object], keys: set[str]) -> None:
    extra = set(params) - keys
    if extra:
        raise HelperError("invalid_params", f"unexpected parameters: {', '.join(sorted(extra))}")
    missing = keys - set(params)
    if missing:
        raise HelperError("invalid_params", f"missing parameters: {', '.join(sorted(missing))}")


def registry() -> dict[str, Operation]:
    from . import iso_acl, iso_library, join_libvirt, remove_package

    return {
        "iso_acl": Operation(iso_acl.ACTION, iso_acl.prepare),
        "add_iso_library": Operation(iso_library.ACTION, iso_library.prepare_add),
        "remove_iso_library": Operation(iso_library.ACTION, iso_library.prepare_remove),
        "clear_iso_libraries": Operation(iso_library.ACTION, iso_library.prepare_clear),
        "list_iso_libraries": Operation(None, iso_library.prepare_list),
        "join_libvirt": Operation(join_libvirt.ACTION, join_libvirt.prepare),
        "remove_package": Operation(remove_package.ACTION, remove_package.prepare),
    }
