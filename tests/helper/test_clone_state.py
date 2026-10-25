"""clone_vm_state: NVRAM and TPM state of a clone, found through libvirt, copied by the helper."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from kvmstudio_helper import server
from kvmstudio_helper.config import HelperConfig
from kvmstudio_helper.errors import HelperError
from kvmstudio_helper.ops import clone_state
from kvmstudio_helper.polkit import Peer

SOURCE = "0d6b2a52-8c1f-4a44-9a3d-0123456789ab"
TARGET = "5e1f0c9a-2b7d-4e6a-8f00-fedcba987654"


@pytest.fixture
def owner() -> int:
    return os.getuid() if os.getuid() >= 1000 else 4321


@pytest.fixture
def tree(tmp_path: Path, owner: int) -> Path:
    """<location>/KVM-Studio/VM with a source VM and an empty clone folder; libvirt's TPM folder."""
    base = tmp_path.resolve()
    lib = base / "KVM-Studio" / "VM"
    (lib / "src").mkdir(parents=True)
    (lib / "clone").mkdir()
    (lib / "src" / "src_VARS.fd").write_bytes(b"firmware variables")
    (lib / "src" / "src_VARS.fd").chmod(0o640)
    tpm = base / "swtpm" / SOURCE / "tpm2"
    tpm.mkdir(parents=True)
    (tpm / "tpm2-00.permall").write_bytes(b"tpm state")
    (tpm / ".lock").write_bytes(b"")
    (tpm / "tpm2-00.permall").chmod(0o600)
    if os.getuid() == 0:
        for path in [base / "KVM-Studio", *(base / "KVM-Studio").rglob("*")]:
            os.chown(path, owner, owner)
    return base


@pytest.fixture
def config(tree: Path) -> HelperConfig:
    return HelperConfig(tree / "h.sock", 107, (), tree / "state.json", swtpm_dir=tree / "swtpm")


def domain_xml(uuid: str, nvram: str | None, tpm: bool = True) -> str:
    os_el = f"<os><type>hvm</type><nvram>{nvram}</nvram></os>" if nvram else "<os/>"
    tpm_el = "<tpm model='tpm-crb'><backend type='emulator' version='2.0'/></tpm>" if tpm else ""
    devices = f"<devices>{tpm_el}</devices>"
    return f"<domain type='kvm'><name>x</name><uuid>{uuid}</uuid>{os_el}{devices}</domain>"


class Libvirt:
    """What virsh answers, per domain UUID."""

    def __init__(self, tree: Path) -> None:
        lib = tree / "KVM-Studio" / "VM"
        off = {"tpm": True, "state": "shut off"}
        self.domains: dict[str, dict[str, Any]] = {
            SOURCE: {**off, "nvram": str(lib / "src" / "src_VARS.fd")},
            TARGET: {**off, "nvram": str(lib / "clone" / "clone_VARS.fd")},
        }
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        found = self.domains.get(args[-1])
        if found is None:
            raise HelperError("not_found", f"no virtual machine {args[-1]}")
        if args[0] == "domstate":
            return str(found["state"]) + "\n"
        return domain_xml(args[-1], found["nvram"], found["tpm"])


@pytest.fixture
def libvirt(tree: Path, monkeypatch: pytest.MonkeyPatch) -> Libvirt:
    fake = Libvirt(tree)
    monkeypatch.setattr(clone_state, "virsh", fake)
    return fake


def call(
    config: HelperConfig,
    params: dict[str, Any],
    uid: int,
    allow: bool = True,
    on_password: Any = None,
) -> Any:
    asked: list[str] = []

    def authorizer(action: str, _peer: Peer) -> bool:
        asked.append(action)
        if on_password is not None:
            on_password()
        return allow

    raw = json.dumps({"op": "clone_vm_state", "params": params}).encode()
    answer = server.handle(raw, Peer(1, uid, uid), config, authorizer=authorizer)
    answer["_asked"] = asked
    return answer


PARAMS = {"source_uuid": SOURCE, "target_uuid": TARGET}


def nothing_copied(tree: Path) -> bool:
    clone = tree / "KVM-Studio" / "VM" / "clone"
    return not (tree / "swtpm" / TARGET).exists() and not (clone / "clone_VARS.fd").exists()


def test_copies_nvram_and_tpm_state(
    config: HelperConfig, tree: Path, owner: int, libvirt: Libvirt
) -> None:
    answer = call(config, PARAMS, owner)
    assert answer["ok"] is True, answer
    assert answer["_asked"] == ["org.kvmstudio.helper.clone-state"]
    assert answer["result"] == {"nvram": True, "tpm": True}
    source = tree / "KVM-Studio" / "VM" / "src" / "src_VARS.fd"
    copy = tree / "KVM-Studio" / "VM" / "clone" / "clone_VARS.fd"
    assert copy.read_bytes() == b"firmware variables"
    # Owner and mode of the original (QEMU's on a real system).
    assert (copy.stat().st_uid, copy.stat().st_gid) == (source.stat().st_uid, source.stat().st_gid)
    assert copy.stat().st_mode & 0o777 == 0o640
    state = tree / "swtpm" / TARGET / "tpm2" / "tpm2-00.permall"
    assert state.read_bytes() == b"tpm state"
    assert state.stat().st_mode & 0o777 == 0o600
    # libvirt is only read, through the system connection.
    assert all(args[0] in ("dumpxml", "domstate") for args in libvirt.calls)


def test_without_nvram_or_tpm_yet(
    config: HelperConfig, tree: Path, owner: int, libvirt: Libvirt
) -> None:
    (tree / "KVM-Studio" / "VM" / "src" / "src_VARS.fd").unlink()  # never started
    libvirt.domains[SOURCE]["tpm"] = False
    answer = call(config, PARAMS, owner)
    assert answer["result"] == {"nvram": False, "tpm": False}
    assert nothing_copied(tree)


@pytest.mark.parametrize(
    ("params", "error"),
    [
        ({**PARAMS, "source_uuid": "../etc"}, "invalid_params"),
        ({**PARAMS, "target_uuid": SOURCE}, "invalid_params"),
        ({**PARAMS, "target_uuid": TARGET.upper()}, "invalid_params"),
        ({"source_uuid": SOURCE}, "invalid_params"),
        # No path is accepted from the client, not even alongside the UUIDs.
        ({**PARAMS, "nvram_source": "/etc/shadow"}, "invalid_params"),
        ({**PARAMS, "nvram_target": "/etc/x.fd"}, "invalid_params"),
        ({**PARAMS, "extra": 1}, "invalid_params"),
        ({**PARAMS, "source_uuid": "11111111-2222-3333-4444-555555555555"}, "not_found"),
        ({**PARAMS, "target_uuid": "11111111-2222-3333-4444-555555555555"}, "not_found"),
    ],
)
def test_refusals_before_the_password(
    config: HelperConfig,
    tree: Path,
    owner: int,
    libvirt: Libvirt,
    params: dict[str, Any],
    error: str,
) -> None:
    answer = call(config, params, owner)
    assert answer["error"] == error
    assert answer["_asked"] == []
    assert nothing_copied(tree)


@pytest.mark.parametrize("which", [SOURCE, TARGET])
@pytest.mark.parametrize("state", ["running", "paused"])
def test_a_vm_that_is_not_shut_off(
    config: HelperConfig, tree: Path, owner: int, libvirt: Libvirt, which: str, state: str
) -> None:
    libvirt.domains[which]["state"] = state
    answer = call(config, PARAMS, owner)
    assert answer["error"] == "running"
    assert answer["_asked"] == []
    assert nothing_copied(tree)


def test_started_while_the_password_was_typed(
    config: HelperConfig, tree: Path, owner: int, libvirt: Libvirt
) -> None:
    def start() -> None:
        libvirt.domains[SOURCE]["state"] = "running"

    answer = call(config, PARAMS, owner, on_password=start)
    assert answer["error"] == "running"
    assert nothing_copied(tree)


@pytest.mark.parametrize(
    ("target", "error"),
    [
        ("/etc/clone_VARS.fd", "path_not_allowed"),
        ("/var/lib/libvirt/qemu/nvram/clone_VARS.fd", "path_not_allowed"),
        ("{tree}/elsewhere/clone_VARS.fd", "path_not_allowed"),
        ("{tree}/KVM-Studio/clone_VARS.fd", "path_not_allowed"),
        # The VM folder itself, not a file right in KVM-Studio/VM.
        ("{tree}/KVM-Studio/VM/clone_VARS.fd", "path_not_allowed"),
        ("{tree}/KVM-Studio/VM/../../elsewhere/x/clone_VARS.fd", "path_not_allowed"),
        ("{tree}/KVM-Studio/VM/missing/clone_VARS.fd", "not_found"),
        ("{tree}/KVM-Studio/VM/src/clone_VARS.fd", "invalid_params"),
        ("relative/clone_VARS.fd", "path_not_allowed"),
    ],
)
def test_the_copy_stays_in_the_callers_vm_folder(
    config: HelperConfig, tree: Path, owner: int, libvirt: Libvirt, target: str, error: str
) -> None:
    (tree / "elsewhere" / "x").mkdir(parents=True)
    libvirt.domains[TARGET]["nvram"] = target.format(tree=tree)
    answer = call(config, PARAMS, owner)
    assert answer["error"] == error
    assert answer["_asked"] == []
    assert not list((tree / "elsewhere").rglob("*.fd"))


def test_symbolic_links_are_refused(
    config: HelperConfig, tree: Path, owner: int, libvirt: Libvirt
) -> None:
    lib = tree / "KVM-Studio" / "VM"
    (lib / "dir-link").symlink_to(lib / "clone")
    libvirt.domains[TARGET]["nvram"] = str(lib / "dir-link" / "clone_VARS.fd")
    assert call(config, PARAMS, owner)["error"] == "path_not_allowed"
    assert not (lib / "clone" / "clone_VARS.fd").exists()

    libvirt.domains[TARGET]["nvram"] = str(lib / "clone" / "clone_VARS.fd")
    secret = tree / "secret"
    secret.write_bytes(b"secret")
    (lib / "src" / "link.fd").symlink_to(secret)
    libvirt.domains[SOURCE]["nvram"] = str(lib / "src" / "link.fd")
    assert call(config, PARAMS, owner)["error"] == "path_not_allowed"

    os.link(secret, lib / "src" / "hard.fd")
    libvirt.domains[SOURCE]["nvram"] = str(lib / "src" / "hard.fd")
    assert call(config, PARAMS, owner)["error"] == "path_not_allowed"
    assert nothing_copied(tree)


def test_a_source_file_of_someone_else(
    config: HelperConfig, tree: Path, owner: int, libvirt: Libvirt
) -> None:
    libvirt.domains[SOURCE]["nvram"] = "/etc/passwd"
    assert call(config, PARAMS, owner)["error"] == "not_owner"
    assert nothing_copied(tree)


def test_folders_of_someone_else(
    config: HelperConfig, tree: Path, owner: int, libvirt: Libvirt
) -> None:
    assert call(config, PARAMS, owner + 1)["error"] == "not_owner"
    assert call(config, PARAMS, 0)["error"] == "not_allowed"
    assert call(config, PARAMS, 65534)["error"] == "not_allowed"
    assert nothing_copied(tree)


def test_nothing_is_overwritten(
    config: HelperConfig, tree: Path, owner: int, libvirt: Libvirt
) -> None:
    copy = tree / "KVM-Studio" / "VM" / "clone" / "clone_VARS.fd"
    copy.write_bytes(b"mine")
    assert call(config, PARAMS, owner)["error"] == "exists"
    assert copy.read_bytes() == b"mine"
    copy.unlink()
    (tree / "swtpm" / TARGET).mkdir()
    assert call(config, PARAMS, owner)["error"] == "exists"
    # The NVRAM copied before the refusal is taken back.
    assert not copy.exists()


def test_a_link_inside_the_tpm_state_stops_the_copy(
    config: HelperConfig, tree: Path, owner: int, libvirt: Libvirt
) -> None:
    (tree / "swtpm" / SOURCE / "tpm2" / "escape").symlink_to("/etc/passwd")
    answer = call(config, PARAMS, owner)
    assert answer["error"] == "path_not_allowed"
    assert nothing_copied(tree)


def test_refused_authorization_copies_nothing(
    config: HelperConfig, tree: Path, owner: int, libvirt: Libvirt
) -> None:
    assert call(config, PARAMS, owner, allow=False)["error"] == "not_authorized"
    assert nothing_copied(tree)


def test_virsh_is_called_without_a_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    def run(argv: list[str], **kwargs: Any) -> Any:
        seen.append((argv, kwargs))
        raise FileNotFoundError("virsh")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(HelperError) as exc:
        clone_state.virsh(["domstate", SOURCE])
    assert exc.value.code == "failed"
    argv, kwargs = seen[0]
    assert argv == ["virsh", "-q", "-c", "qemu:///system", "domstate", SOURCE]
    assert "shell" not in kwargs
