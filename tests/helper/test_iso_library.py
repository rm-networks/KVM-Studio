"""ISO libraries declared through the helper, and the ACL entries it keeps track of.

setfacl is never run: a fake keeps the u:<qemu> entry of each inode, so that the
helper reads back what it "wrote", and what was there before it came.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kvmstudio_helper import __main__ as helper_main
from kvmstudio_helper import acl, server, state
from kvmstudio_helper.config import HelperConfig, IsoLibrary
from kvmstudio_helper.polkit import Peer

QEMU = 107
ADD, REMOVE, CLEAR, LIST = (
    "add_iso_library",
    "remove_iso_library",
    "clear_iso_libraries",
    "list_iso_libraries",
)


class FakeAcl:
    """u:<uid> entries by inode, changed by the fake setfacl."""

    def __init__(self) -> None:
        self.entries: dict[tuple[int, int, int], int] = {}
        self.calls: list[tuple[list[str], str]] = []

    @staticmethod
    def _key(path: str | Path, uid: int) -> tuple[int, int, int]:
        st = os.stat(path)
        return (st.st_dev, st.st_ino, uid)

    def set(self, path: Path, uid: int, bits: int) -> None:
        self.entries[self._key(path, uid)] = bits

    def get(self, path: Path, uid: int = QEMU) -> int | None:
        return self.entries.get(self._key(path, uid))

    def user_entry(self, path: str, uid: int) -> int | None:
        return self.entries.get(self._key(path, uid))

    def named_entries(self, path: str) -> int:
        st = os.stat(path)
        return sum(1 for dev, ino, _uid in self.entries if (dev, ino) == (st.st_dev, st.st_ino))

    def __call__(self, argv: list[str], fds: tuple[int, ...]) -> None:
        (fd,) = fds
        target = f"/proc/self/fd/{fd}"
        assert argv[0] == "setfacl"
        assert argv[-2:] == ["--", target]
        self.calls.append((argv[1:3], os.readlink(target)))
        if argv[1] == "-b":
            st = os.stat(target)
            for key in [k for k in self.entries if k[:2] == (st.st_dev, st.st_ino)]:
                del self.entries[key]
        elif argv[1] == "-x":
            uid = int(argv[2].split(":")[1])
            del self.entries[self._key(target, uid)]
        else:
            _u, uid_text, perms = argv[2].split(":")
            bits = sum(v for c, v in zip(perms, (4, 2, 1), strict=True) if c != "-")
            self.entries[self._key(target, int(uid_text))] = bits


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeAcl:
    f = FakeAcl()
    monkeypatch.setattr(acl, "user_entry", f.user_entry)
    monkeypatch.setattr(acl, "named_entries", f.named_entries)
    return f


@pytest.fixture
def owner() -> int:
    # The CI runs as root: the test tree is then given to a regular account.
    return os.getuid() if os.getuid() >= 1000 else 4321


@pytest.fixture
def home(tmp_path: Path, owner: int) -> Iterator[Path]:
    """A home folder QEMU cannot cross, with two ISO folders and an image in each."""
    home = tmp_path / "home"
    for name in ("iso", "more"):
        (home / name / "linux").mkdir(parents=True)
        (home / name / "linux" / f"{name}.iso").write_bytes(b"")
    home.chmod(0o700)
    if os.getuid() == 0:
        for path in [home, *home.rglob("*")]:
            os.chown(path, owner, owner)
    yield home
    home.chmod(0o755)


@pytest.fixture
def config(tmp_path: Path) -> HelperConfig:
    admin = tmp_path / "admin"
    (admin / "x.iso").parent.mkdir()
    (admin / "x.iso").write_bytes(b"")
    return HelperConfig(
        tmp_path / "h.sock", QEMU, (IsoLibrary(admin, (".iso",)),), tmp_path / "state.json"
    )


def call(
    config: HelperConfig,
    op: str,
    params: dict[str, Any],
    uid: int,
    *,
    allow: bool = True,
    runner: FakeAcl | None = None,
) -> dict[str, Any]:
    asked: list[str] = []

    def authorizer(action: str, _peer: Peer) -> bool:
        asked.append(action)
        return allow

    raw = json.dumps({"op": op, "params": params}).encode()
    calls: list[Any] = []
    answer = server.handle(
        raw,
        Peer(4242, uid, uid),
        config,
        authorizer=authorizer,
        runner=runner or (lambda argv, fds: calls.append(argv)),
    )
    answer["_asked"] = asked
    return answer


def declared(config: HelperConfig) -> list[tuple[str, int]]:
    return [(lib.path, lib.owner) for lib in state.load(config.state).libraries]


def test_declaring_a_library_of_ones_own(config: HelperConfig, home: Path, owner: int) -> None:
    (home / "link").symlink_to(home / "iso")
    answer = call(config, ADD, {"path": str(home / "link")}, owner)
    assert answer["ok"] is True
    assert answer["_asked"] == ["org.kvmstudio.helper.iso-library"]
    # Stored resolved, links followed.
    assert answer["result"] == {"path": str(home / "iso")}
    assert declared(config) == [(str(home / "iso"), owner)]
    # Twice is once.
    assert call(config, ADD, {"path": str(home / "iso")}, owner)["ok"] is True
    assert declared(config) == [(str(home / "iso"), owner)]
    # Read with helper.toml, which keeps its own.
    paths = [lib.path for lib in state.libraries(config)]
    assert paths == [config.iso_libraries[0].path, home / "iso"]


@pytest.mark.parametrize(
    ("path", "error"),
    [
        ("/", "system_folder"),
        ("/etc", "system_folder"),
        ("/usr/share", "system_folder"),
        ("/var/lib", "system_folder"),
        ("/boot", "system_folder"),
        ("/proc/self", "system_folder"),
        ("/dev", "system_folder"),
        ("/run", "system_folder"),
        ("/bin", "system_folder"),
        ("/lib", "system_folder"),
        ("/tmp", "not_owner"),  # noqa: S108
        ("/no/such/folder", "not_found"),
        ("relative/iso", "invalid_params"),
        ("~/iso", "invalid_params"),
        ("/srv/a\nb", "invalid_params"),
        ("/srv/\x00", "invalid_params"),
    ],
)
def test_folders_that_cannot_be_declared(
    config: HelperConfig, owner: int, path: str, error: str
) -> None:
    answer = call(config, ADD, {"path": path}, owner)
    assert answer["error"] == error
    assert answer["_asked"] == []
    assert declared(config) == []


def test_links_into_system_folders_files_and_others(
    config: HelperConfig, home: Path, owner: int, tmp_path: Path
) -> None:
    (home / "etc").symlink_to("/etc")
    (home / "root-link").symlink_to("/")
    assert call(config, ADD, {"path": str(home / "etc")}, owner)["error"] == "system_folder"
    assert call(config, ADD, {"path": str(home / "root-link")}, owner)["error"] == "system_folder"
    image = home / "iso" / "linux" / "iso.iso"
    assert call(config, ADD, {"path": str(image)}, owner)["error"] == "not_a_folder"
    # Someone else's folder, even through a link of one's own.
    assert call(config, ADD, {"path": str(home / "iso")}, owner + 1)["error"] == "not_owner"
    assert declared(config) == []


@pytest.mark.parametrize("uid", [0, 999, 65534])
def test_root_and_system_accounts_declare_nothing(
    config: HelperConfig, home: Path, uid: int
) -> None:
    assert call(config, ADD, {"path": str(home / "iso")}, uid)["error"] == "not_allowed"


@pytest.mark.parametrize(
    "params",
    [{}, {"path": "/x", "owner": 0}, {"path": 42}, {"path": ["/x"]}],
)
def test_malformed_parameters(config: HelperConfig, owner: int, params: dict[str, Any]) -> None:
    for op in (ADD, REMOVE):
        answer = call(config, op, params, owner)
        assert answer["error"] == "invalid_params"
        assert answer["_asked"] == []


def test_refused_authorization_changes_nothing(
    config: HelperConfig, home: Path, owner: int
) -> None:
    answer = call(config, ADD, {"path": str(home / "iso")}, owner, allow=False)
    assert answer["error"] == "not_authorized"
    assert not config.state.exists()


def test_folder_swapped_while_the_password_is_typed(
    config: HelperConfig, home: Path, owner: int, tmp_path: Path
) -> None:
    raw = json.dumps({"op": ADD, "params": {"path": str(home / "iso")}}).encode()

    def swap(_action: str, _peer: Peer) -> bool:
        (home / "iso").rename(home / "old")
        (home / "iso").symlink_to("/etc")
        return True

    answer = server.handle(raw, Peer(1, owner, owner), config, authorizer=swap)
    assert answer["error"] == "path_changed"
    assert declared(config) == []


def fix(config: HelperConfig, image: Path, owner: int, fake: FakeAcl) -> dict[str, Any]:
    answer = call(config, "iso_acl", {"path": str(image)}, owner, runner=fake)
    assert answer["ok"] is True, answer
    return answer


def test_fix_crosses_the_owners_folders_and_records_each_bit(
    config: HelperConfig, home: Path, owner: int, fake: FakeAcl
) -> None:
    call(config, ADD, {"path": str(home / "iso")}, owner)
    image = home / "iso" / "linux" / "iso.iso"
    changed = fix(config, image, owner, fake)["result"]["changed"]
    assert changed[-3:] == [str(home / "iso"), str(home / "iso" / "linux"), str(image)]
    # The home folder (0700) is crossed; folders of other accounts are never touched.
    assert str(home) in changed
    for path in changed:
        assert os.stat(path).st_uid == owner
    assert fake.get(home) == 1
    assert fake.get(image) == 4
    recorded = {(e.path, e.bit, e.created) for e in state.load(config.state).acl}
    assert (str(image), "r", True) in recorded
    assert (str(home), "x", True) in recorded


def test_rights_that_were_there_before_are_never_recorded(
    config: HelperConfig, home: Path, owner: int, fake: FakeAcl
) -> None:
    call(config, ADD, {"path": str(home / "iso")}, owner)
    image = home / "iso" / "linux" / "iso.iso"
    fake.set(image, QEMU, 4)  # u:qemu:r, set by hand earlier
    fake.set(home / "iso", QEMU, 4)  # u:qemu:r on a folder: x is still missing
    fix(config, image, owner, fake)
    entries = {e.path: e for e in state.load(config.state).acl}
    assert str(image) not in entries
    assert entries[str(home / "iso")].created is False
    assert fake.get(home / "iso") == 5

    answer = call(config, REMOVE, {"path": str(home / "iso")}, owner, runner=fake)
    assert answer["ok"] is True
    # Back to what it was, entry included; the image keeps its own.
    assert fake.get(home / "iso") == 4
    assert fake.get(image) == 4
    assert fake.get(home) is None
    assert fake.get(home / "iso" / "linux") is None
    # Folders above the home folder stay: the helper.toml library needs them too.
    assert [e for e in state.load(config.state).acl if Path(e.path).is_relative_to(home)] == []
    assert declared(config) == []


def test_a_file_without_acl_gets_no_acl_back(
    config: HelperConfig, home: Path, owner: int, fake: FakeAcl
) -> None:
    call(config, ADD, {"path": str(home / "iso")}, owner)
    image = home / "iso" / "linux" / "iso.iso"
    fake.set(home / "iso" / "linux", 1001, 5)  # someone else's entry on the folder
    fix(config, image, owner, fake)
    fake.calls.clear()
    call(config, REMOVE, {"path": str(home / "iso")}, owner, runner=fake)
    flags = {target: argv[0] for argv, target in fake.calls}
    # No ACL before: none after, mask included. The folder keeps the other entry.
    assert flags[str(image)] == "-b"
    assert flags[str(home / "iso" / "linux")] == "-x"
    assert fake.get(home / "iso" / "linux", 1001) == 5


def test_a_shared_parent_keeps_search_while_a_library_needs_it(
    config: HelperConfig, home: Path, owner: int, fake: FakeAcl
) -> None:
    for name in ("iso", "more"):
        call(config, ADD, {"path": str(home / name)}, owner)
        fix(config, home / name / "linux" / f"{name}.iso", owner, fake)
    assert [e.path for e in state.load(config.state).acl].count(str(home)) == 1

    removed = call(config, REMOVE, {"path": str(home / "iso")}, owner, runner=fake)["result"]
    assert f"{home} u:{QEMU}:x" not in removed["removed"]
    assert fake.get(home) == 1
    assert fake.get(home / "iso") is None
    assert fake.get(home / "more" / "linux" / "more.iso") == 4

    call(config, REMOVE, {"path": str(home / "more")}, owner, runner=fake)
    assert fake.get(home) is None
    assert [p for p in home.rglob("*") if fake.get(p) is not None] == []


def test_a_file_replaced_since_is_left_alone(
    config: HelperConfig, home: Path, owner: int, fake: FakeAcl
) -> None:
    call(config, ADD, {"path": str(home / "iso")}, owner)
    image = home / "iso" / "linux" / "iso.iso"
    fix(config, image, owner, fake)
    # The old file stays elsewhere, so its inode cannot be given to the new one.
    image.rename(home / "iso" / "old.iso")
    image.write_bytes(b"other")
    fake.set(image, QEMU, 4)  # someone's own entry on the new file
    fake.calls.clear()
    call(config, REMOVE, {"path": str(home / "iso")}, owner, runner=fake)
    assert all(target != str(image) for _argv, target in fake.calls)
    assert fake.get(image) == 4


def test_a_library_swapped_for_a_link_gives_nothing(
    config: HelperConfig, home: Path, owner: int, fake: FakeAcl, tmp_path: Path
) -> None:
    """Declared, then replaced by a link to a folder of someone else's."""
    call(config, ADD, {"path": str(home / "iso")}, owner)
    (home / "iso").rename(home / "was-iso")
    (home / "iso").symlink_to(config.iso_libraries[0].path.parent / "elsewhere")
    elsewhere = config.iso_libraries[0].path.parent / "elsewhere"
    (elsewhere / "linux").mkdir(parents=True)
    (elsewhere / "linux" / "iso.iso").write_bytes(b"")
    answer = call(config, "iso_acl", {"path": str(home / "iso" / "linux" / "iso.iso")}, owner)
    assert answer["error"] == "path_not_allowed"
    assert fake.calls == []


def test_removing_what_is_not_ones_own(
    config: HelperConfig, home: Path, owner: int, fake: FakeAcl
) -> None:
    admin = str(config.iso_libraries[0].path)
    assert call(config, REMOVE, {"path": admin}, owner)["error"] == "admin_library"
    assert call(config, REMOVE, {"path": str(home / "iso")}, owner)["error"] == "not_declared"
    call(config, ADD, {"path": str(home / "iso")}, owner)
    assert call(config, REMOVE, {"path": str(home / "iso")}, owner + 1)["error"] == "not_owner"
    assert call(config, REMOVE, {"path": str(home / "iso")}, 0)["error"] == "not_allowed"
    assert declared(config) == [(str(home / "iso"), owner)]


def test_a_folder_gone_can_still_be_removed(
    config: HelperConfig, home: Path, owner: int, fake: FakeAcl
) -> None:
    call(config, ADD, {"path": str(home / "iso")}, owner)
    fix(config, home / "iso" / "linux" / "iso.iso", owner, fake)
    (home / "iso" / "linux" / "iso.iso").unlink()
    (home / "iso" / "linux").rmdir()
    (home / "iso").rmdir()
    assert call(config, REMOVE, {"path": str(home / "iso")}, owner, runner=fake)["ok"] is True
    assert declared(config) == []
    assert fake.get(home) is None


@pytest.mark.parametrize("remove_acls", [True, False])
def test_clearing_at_uninstall(
    config: HelperConfig, home: Path, owner: int, fake: FakeAcl, remove_acls: bool
) -> None:
    call(config, ADD, {"path": str(home / "iso")}, owner)
    fix(config, home / "iso" / "linux" / "iso.iso", owner, fake)
    before = dict(fake.entries)
    answer = call(config, CLEAR, {"remove_acls": remove_acls}, owner, runner=fake)
    assert answer["ok"] is True
    assert answer["_asked"] == ["org.kvmstudio.helper.iso-library"]
    assert fake.entries == ({} if remove_acls else before)
    assert state.load(config.state) == state.State()


@pytest.mark.parametrize("params", [{}, {"remove_acls": "yes"}, {"remove_acls": 1, "x": 2}])
def test_clear_takes_a_boolean_only(
    config: HelperConfig, owner: int, params: dict[str, Any]
) -> None:
    assert call(config, CLEAR, params, owner)["error"] == "invalid_params"


def test_listing_needs_no_password_and_shows_ones_own(
    config: HelperConfig, home: Path, owner: int, fake: FakeAcl
) -> None:
    call(config, ADD, {"path": str(home / "iso")}, owner)
    fix(config, home / "iso" / "linux" / "iso.iso", owner, fake)
    answer = call(config, LIST, {}, owner)
    assert answer["_asked"] == []
    assert answer["result"]["libraries"] == [
        {"path": str(config.iso_libraries[0].path), "source": "admin"},
        {"path": str(home / "iso"), "source": "user"},
    ]
    assert answer["result"]["acl_entries"] >= 4
    other = call(config, LIST, {}, owner + 1)["result"]
    assert other["libraries"] == [{"path": str(config.iso_libraries[0].path), "source": "admin"}]
    assert call(config, LIST, {"path": "/"}, owner)["error"] == "invalid_params"


def test_clear_state_from_the_package_scripts(
    config: HelperConfig,
    home: Path,
    owner: int,
    fake: FakeAcl,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call(config, ADD, {"path": str(home / "iso")}, owner)
    fix(config, home / "iso" / "linux" / "iso.iso", owner, fake)
    toml = tmp_path / "helper.toml"
    toml.write_text(f'qemu_user = "root"\nstate = "{config.state}"\n')
    monkeypatch.setattr(helper_main, "run_tool", fake)
    assert helper_main.main(["--config", str(toml), "--clear-state"]) == 0
    assert fake.entries == {}
    assert not config.state.exists()


def test_state_file_is_private(config: HelperConfig, home: Path, owner: int) -> None:
    call(config, ADD, {"path": str(home / "iso")}, owner)
    assert config.state.stat().st_mode & 0o777 == 0o600
