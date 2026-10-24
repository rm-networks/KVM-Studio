"""join_libvirt: the account comes from the kernel, never from the request."""

from __future__ import annotations

import grp
import json
import pwd
from pathlib import Path
from typing import Any

import pytest

from kvmstudio_helper import server
from kvmstudio_helper.config import HelperConfig
from kvmstudio_helper.ops import join_libvirt
from kvmstudio_helper.polkit import Peer

ALICE = Peer(pid=4242, uid=1000, gid=1000)


def _user(name: str, uid: int, gid: int) -> pwd.struct_passwd:
    return pwd.struct_passwd((name, "x", uid, gid, "", f"/home/{name}", "/bin/bash"))


@pytest.fixture
def accounts(monkeypatch: pytest.MonkeyPatch) -> dict[int, pwd.struct_passwd]:
    users = {
        1000: _user("alice", 1000, 1000),
        1001: _user("bob", 1001, 1001),
        1002: _user("-rf", 1002, 1002),
        65534: _user("nobody", 65534, 65534),
    }
    members = ["bob"]

    def by_uid(uid: int) -> pwd.struct_passwd:
        return users[uid]

    def by_name(name: str) -> grp.struct_group:
        if name != "libvirt":
            raise KeyError(name)
        return grp.struct_group(("libvirt", "x", 975, members))

    monkeypatch.setattr(join_libvirt, "user_by_uid", by_uid)
    monkeypatch.setattr(join_libvirt, "group_by_name", by_name)
    return users


def call(
    request: object, peer: Peer = ALICE, *, allow: bool = True
) -> tuple[dict[str, Any], list[list[str]], list[str]]:
    ran: list[list[str]] = []
    asked: list[str] = []

    def authorizer(action: str, who: Peer) -> bool:
        assert who == peer
        asked.append(action)
        return allow

    raw = request if isinstance(request, bytes) else json.dumps(request).encode()
    config = HelperConfig(Path("/nonexistent.sock"), None, ())
    answer = server.handle(
        raw, peer, config, authorizer=authorizer, runner=lambda argv, fds: ran.append(argv)
    )
    return answer, ran, asked


JOIN = {"op": "join_libvirt", "params": {}}


def test_adds_the_calling_account(accounts: object) -> None:
    answer, ran, asked = call(JOIN)
    assert answer == {"ok": True, "result": {"user": "alice", "already": False}}
    assert ran == [["usermod", "-a", "-G", "libvirt", "--", "alice"]]
    assert asked == ["org.kvmstudio.helper.join-libvirt"]


def test_already_member_changes_nothing(accounts: object) -> None:
    answer, ran, _ = call(JOIN, Peer(1, 1001, 1001))
    assert answer["result"] == {"user": "bob", "already": True}
    assert ran == []


def test_refused_authorization_runs_nothing(accounts: object) -> None:
    answer, ran, _ = call(JOIN, allow=False)
    assert answer["error"] == "not_authorized"
    assert ran == []


@pytest.mark.parametrize("uid", [0, 1, 999, 65534, 4000])
def test_root_system_and_unknown_accounts_are_refused(accounts: object, uid: int) -> None:
    answer, ran, asked = call(JOIN, Peer(1, uid, uid))
    assert answer["error"] == "not_allowed"
    assert (ran, asked) == ([], [])


def test_account_name_that_looks_like_an_option(accounts: object) -> None:
    answer, ran, _ = call(JOIN, Peer(1, 1002, 1002))
    assert answer["error"] == "not_allowed"
    assert ran == []


@pytest.mark.parametrize(
    "params",
    [{"user": "root"}, {"uid": 0}, {"group": "wheel"}, {"user": "bob", "group": "libvirt"}],
)
def test_no_parameter_is_accepted(accounts: object, params: dict[str, object]) -> None:
    answer, ran, asked = call({"op": "join_libvirt", "params": params})
    assert answer["error"] == "invalid_params"
    assert (ran, asked) == ([], [])


@pytest.mark.parametrize(
    "raw",
    [
        b'{"op": "join_libvirt", "params": {}, "uid": 0}',
        b'{"op": "join_libvirt", "params": {}, "params": {"uid": 0}}',
        b'{"op": "join_libvirt", "params": null}',
        b'{"op": "join_libvirt ", "params": {}}',
        b'{"op": "JOIN_LIBVIRT", "params": {}}',
    ],
)
def test_malformed_requests(accounts: object, raw: bytes) -> None:
    answer, ran, asked = call(raw)
    assert answer["error"] in {"bad_request", "unknown_operation"}
    assert (ran, asked) == ([], [])


def test_missing_group(accounts: object, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_group(name: str) -> grp.struct_group:
        raise KeyError(name)

    monkeypatch.setattr(join_libvirt, "group_by_name", no_group)
    assert call(JOIN)[0]["error"] == "failed"


# remove_package: same shape, no parameters, fixed package name


@pytest.mark.parametrize(
    ("tools", "expected"),
    [
        ({"dnf"}, ["--", "dnf", "remove", "-y", "kvm-studio"]),
        (
            {"apt-get"},
            [
                "--setenv=DEBIAN_FRONTEND=noninteractive",
                "--",
                "apt-get",
                "remove",
                "-y",
                "kvm-studio",
            ],
        ),
    ],
)
def test_remove_package_runs_outside_the_helper(
    monkeypatch: pytest.MonkeyPatch, tools: set[str], expected: list[str]
) -> None:
    from kvmstudio_helper.ops import remove_package

    monkeypatch.setattr(remove_package, "which", lambda name: name if name in tools else None)
    answer, ran, asked = call({"op": "remove_package", "params": {}})
    assert answer == {"ok": True, "result": {"unit": "kvm-studio-removal"}}
    assert ran == [["systemd-run", "--unit=kvm-studio-removal", "--collect", "--quiet", *expected]]
    assert asked == ["org.kvmstudio.helper.remove-package"]


@pytest.mark.parametrize(
    "params", [{"package": "systemd"}, {"package": "kvm-studio"}, {"command": "rm -rf /"}]
)
def test_remove_package_takes_no_parameter(params: dict[str, object]) -> None:
    answer, ran, asked = call({"op": "remove_package", "params": params})
    assert answer["error"] == "invalid_params"
    assert (ran, asked) == ([], [])


def test_remove_package_refused_runs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from kvmstudio_helper.ops import remove_package

    monkeypatch.setattr(remove_package, "which", lambda name: name)
    answer, ran, _ = call({"op": "remove_package", "params": {}}, allow=False)
    assert answer["error"] == "not_authorized"
    assert ran == []
