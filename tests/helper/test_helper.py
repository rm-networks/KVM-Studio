"""Helper: request parsing, path confinement, attacks, peer identity.

Tools are never really run: a fake runner records what would have been run and
checks that each /proc/self/fd/N designates the expected file at that moment.
"""

from __future__ import annotations

import json
import os
import socket
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kvmstudio_helper import server
from kvmstudio_helper.config import ConfigError, HelperConfig, IsoLibrary, parse
from kvmstudio_helper.polkit import Peer, start_time

PEER = Peer(pid=4242, uid=1000, gid=1000)
QEMU_UID = 107


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, argv: list[str], fds: tuple[int, ...]) -> None:
        (fd,) = fds
        assert argv[-1] == f"/proc/self/fd/{fd}"
        self.calls.append((argv, os.readlink(f"/proc/self/fd/{fd}")))


@pytest.fixture
def lib(tmp_path: Path) -> Path:
    root = tmp_path / "iso"
    (root / "linux").mkdir(parents=True)
    (root / "linux" / "fedora.iso").write_bytes(b"")
    (tmp_path / "secret.iso").write_bytes(b"")
    return root


@pytest.fixture
def config(lib: Path, tmp_path: Path) -> HelperConfig:
    return HelperConfig(tmp_path / "h.sock", QEMU_UID, (IsoLibrary(lib, (".iso", ".img")),))


def call(
    config: HelperConfig,
    request: object,
    *,
    allow: bool = True,
    runner: Recorder | None = None,
) -> dict[str, Any]:
    raw = request if isinstance(request, bytes) else json.dumps(request).encode()
    asked: list[tuple[str, Peer]] = []

    def authorizer(action: str, peer: Peer) -> bool:
        asked.append((action, peer))
        return allow

    answer = server.handle(raw, PEER, config, authorizer=authorizer, runner=runner or Recorder())
    answer["_asked"] = asked
    return answer


def iso_acl(path: str) -> dict[str, object]:
    return {"op": "iso_acl", "params": {"path": path}}


def test_iso_acl_grants_qemu_search_and_read(config: HelperConfig, lib: Path) -> None:
    runner = Recorder()
    answer = call(config, iso_acl(str(lib / "linux" / "fedora.iso")), runner=runner)
    assert answer["ok"] is True
    assert answer["_asked"] == [("org.kvmstudio.helper.iso-acl", PEER)]
    assert [(argv[:4], target) for argv, target in runner.calls] == [
        (["setfacl", "-m", "u:107:x", "--"], str(lib)),
        (["setfacl", "-m", "u:107:x", "--"], str(lib / "linux")),
        (["setfacl", "-m", "u:107:r", "--"], str(lib / "linux" / "fedora.iso")),
    ]
    assert answer["result"]["changed"][-1] == str(lib / "linux" / "fedora.iso")


def test_refused_authorization_runs_nothing(config: HelperConfig, lib: Path) -> None:
    runner = Recorder()
    answer = call(config, iso_acl(str(lib / "linux" / "fedora.iso")), allow=False, runner=runner)
    assert answer["error"] == "not_authorized"
    assert runner.calls == []


@pytest.mark.parametrize(
    ("relative", "error"),
    [
        ("linux/../../secret.iso", "path_not_allowed"),
        ("linux/../..", "path_not_allowed"),
        ("", "path_not_allowed"),  # the library root itself
        ("linux", "path_not_allowed"),  # a folder, not an image
        ("missing.iso", "not_found"),
    ],
)
def test_paths_outside_or_invalid(
    config: HelperConfig, lib: Path, relative: str, error: str
) -> None:
    path = str(lib / relative) if relative else str(lib)
    answer = call(config, iso_acl(path))
    assert answer["error"] == error
    assert answer["_asked"] == []


def test_symlink_to_outside_is_refused(config: HelperConfig, lib: Path, tmp_path: Path) -> None:
    (lib / "link.iso").symlink_to(tmp_path / "secret.iso")
    (lib / "dir").symlink_to(tmp_path)
    assert call(config, iso_acl(str(lib / "link.iso")))["error"] == "path_not_allowed"
    assert call(config, iso_acl(str(lib / "dir" / "secret.iso")))["error"] == "path_not_allowed"


def test_symlink_inside_the_library_acts_on_its_target(config: HelperConfig, lib: Path) -> None:
    (lib / "latest.iso").symlink_to(lib / "linux" / "fedora.iso")
    runner = Recorder()
    assert call(config, iso_acl(str(lib / "latest.iso")), runner=runner)["ok"] is True
    assert runner.calls[-1][1] == str(lib / "linux" / "fedora.iso")


def test_folder_swapped_for_a_symlink_after_the_check(
    config: HelperConfig, lib: Path, tmp_path: Path
) -> None:
    """The check passes, then the user replaces a folder before the change."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "fedora.iso").write_bytes(b"")

    def swap(action: str, peer: Peer) -> bool:
        (lib / "linux").rename(lib / "old")
        (lib / "linux").symlink_to(outside)
        return True

    runner = Recorder()
    raw = json.dumps(iso_acl(str(lib / "linux" / "fedora.iso"))).encode()
    answer = server.handle(raw, PEER, config, authorizer=swap, runner=runner)
    assert answer["error"] == "path_changed"
    assert runner.calls == []


@pytest.mark.parametrize(
    "path",
    ["linux/fedora.iso", "./fedora.iso", "~/fedora.iso", "fedora.iso"],
)
def test_relative_paths_are_refused(config: HelperConfig, path: str) -> None:
    assert call(config, iso_acl(path))["error"] == "invalid_params"


@pytest.mark.parametrize(
    "path",
    ["/srv/iso/a\x00b.iso", "/srv/iso/a\nb.iso", "/srv/iso/\x1b[31m.iso", "/" + "a" * 5000],
)
def test_control_characters_and_long_paths(config: HelperConfig, path: str) -> None:
    assert call(config, iso_acl(path))["error"] == "invalid_params"


def test_shell_characters_are_just_part_of_a_name(config: HelperConfig, lib: Path) -> None:
    name = "a b;$(touch x)`id`'\"|&*.iso"
    (lib / name).write_bytes(b"")
    runner = Recorder()
    assert call(config, iso_acl(str(lib / name)), runner=runner)["ok"] is True
    argv, target = runner.calls[-1]
    assert target == str(lib / name)
    assert not any(name in arg for arg in argv)


@pytest.mark.parametrize(
    ("request_", "error"),
    [
        ({"op": "exec", "params": {"cmd": "id"}}, "unknown_operation"),
        ({"op": "iso_acl", "params": {"path": "/x", "uid": 0}}, "invalid_params"),
        ({"op": "iso_acl", "params": {}}, "invalid_params"),
        ({"op": "iso_acl", "params": {"path": 42}}, "invalid_params"),
        ({"op": "iso_acl", "params": {"path": "/x"}, "uid": 0}, "bad_request"),
        ({"op": "iso_acl"}, "bad_request"),
        ({"op": ["iso_acl"], "params": {}}, "bad_request"),
        (["iso_acl"], "bad_request"),
        (b"not json", "bad_request"),
        (b"\xff\xfe", "bad_request"),
        (b'{"op": "iso_acl", "op": "x", "params": {}}', "bad_request"),
        (b'{"op": "iso_acl", "params": {"path": "/a", "path": "/b"}}', "bad_request"),
        (b"{" + b" " * server.MAX_REQUEST + b"}", "bad_request"),
    ],
)
def test_malformed_requests(config: HelperConfig, request_: object, error: str) -> None:
    answer = call(config, request_)
    assert answer["error"] == error
    assert answer["_asked"] == []


def test_missing_qemu_account(config: HelperConfig, lib: Path) -> None:
    no_qemu = HelperConfig(config.socket, None, config.iso_libraries)
    assert call(no_qemu, iso_acl(str(lib / "linux" / "fedora.iso")))["error"] == "failed"


def test_config_parsing() -> None:
    parsed = parse({"qemu_user": "root", "iso_libraries": [{"path": "/srv/iso"}]})
    assert parsed.qemu_uid == 0
    assert parsed.iso_libraries == (IsoLibrary(Path("/srv/iso"), (".iso", ".img")),)
    with pytest.raises(ConfigError):
        parse({"iso_libraries": [{"path": "relative"}]})
    with pytest.raises(ConfigError):
        parse({"unknown": 1})
    with pytest.raises(ConfigError):
        parse({"qemu_user": "no-such-account-here"})


def test_duplicate_libraries_count_once() -> None:
    parsed = parse(
        {
            "qemu_user": "root",
            "iso_libraries": [
                {"path": "/srv/iso"},
                {"path": "/srv/iso/", "extensions": [".iso", ".raw"]},
                {"path": "/data/iso"},
            ],
        }
    )
    assert parsed.iso_libraries == (
        IsoLibrary(Path("/srv/iso"), (".iso", ".img", ".raw")),
        IsoLibrary(Path("/data/iso"), (".iso", ".img")),
    )


def test_start_time_reads_proc() -> None:
    assert start_time(os.getpid()).isdigit()


@pytest.fixture
def running(config: HelperConfig, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Peer]]:
    seen: list[Peer] = []

    def authorizer(action: str, peer: Peer) -> bool:
        seen.append(peer)
        return False

    real = server.handle
    monkeypatch.setattr(
        server, "handle", lambda raw, peer, cfg: real(raw, peer, cfg, authorizer=authorizer)
    )
    srv = server.HelperServer(config)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield seen
    srv.shutdown()
    srv.server_close()


def test_socket_identifies_the_caller_by_kernel_credentials(
    running: list[Peer], config: HelperConfig, lib: Path
) -> None:
    assert config.socket.stat().st_mode & 0o777 == 0o666
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(config.socket))
        client.sendall(json.dumps(iso_acl(str(lib / "linux" / "fedora.iso"))).encode() + b"\n")
        answer = json.loads(client.makefile().readline())
    assert answer["error"] == "not_authorized"
    assert running == [Peer(os.getpid(), os.getuid(), os.getgid())]
