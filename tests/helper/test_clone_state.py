"""clone_vm_state: NVRAM and TPM state of a clone, copied by the helper."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from kvmstudio_helper import server
from kvmstudio_helper.config import HelperConfig
from kvmstudio_helper.polkit import Peer

SOURCE = "0d6b2a52-8c1f-4a44-9a3d-0123456789ab"
TARGET = "5e1f0c9a-2b7d-4e6a-8f00-fedcba987654"


@pytest.fixture
def owner() -> int:
    return os.getuid() if os.getuid() >= 1000 else 4321


@pytest.fixture
def tree(tmp_path: Path, owner: int) -> Path:
    """A library with a source VM folder and an empty clone folder, and libvirt's TPM folder."""
    lib = tmp_path / "lib"
    (lib / "src").mkdir(parents=True)
    (lib / "clone").mkdir()
    (lib / "src" / "src_VARS.fd").write_bytes(b"firmware variables")
    tpm = tmp_path / "swtpm" / SOURCE / "tpm2"
    tpm.mkdir(parents=True)
    (tpm / "tpm2-00.permall").write_bytes(b"tpm state")
    (tpm / ".lock").write_bytes(b"")
    (tpm / "tpm2-00.permall").chmod(0o600)
    if os.getuid() == 0:
        for path in [lib, *lib.rglob("*")]:
            os.chown(path, owner, owner)
    return tmp_path


@pytest.fixture
def config(tree: Path) -> HelperConfig:
    return HelperConfig(tree / "h.sock", 107, (), tree / "state.json", swtpm_dir=tree / "swtpm")


def call(config: HelperConfig, params: dict[str, Any], uid: int, allow: bool = True) -> Any:
    asked: list[str] = []

    def authorizer(action: str, _peer: Peer) -> bool:
        asked.append(action)
        return allow

    raw = json.dumps({"op": "clone_vm_state", "params": params}).encode()
    answer = server.handle(raw, Peer(1, uid, uid), config, authorizer=authorizer)
    answer["_asked"] = asked
    return answer


def params(tree: Path, **changes: Any) -> dict[str, Any]:
    base = {
        "source_uuid": SOURCE,
        "target_uuid": TARGET,
        "nvram_source": str(tree / "lib" / "src" / "src_VARS.fd"),
        "nvram_target": str(tree / "lib" / "clone" / "clone_VARS.fd"),
    }
    return {**base, **changes}


def test_copies_nvram_and_tpm_state(config: HelperConfig, tree: Path, owner: int) -> None:
    answer = call(config, params(tree), owner)
    assert answer["ok"] is True, answer
    assert answer["_asked"] == ["org.kvmstudio.helper.clone-state"]
    assert answer["result"] == {"nvram": True, "tpm": True}
    copy = tree / "lib" / "clone" / "clone_VARS.fd"
    assert copy.read_bytes() == b"firmware variables"
    assert copy.stat().st_mode & 0o777 == 0o600
    assert copy.stat().st_uid == owner
    state = tree / "swtpm" / TARGET / "tpm2" / "tpm2-00.permall"
    assert state.read_bytes() == b"tpm state"
    assert state.stat().st_mode & 0o777 == 0o600


def test_without_nvram_or_tpm_yet(config: HelperConfig, tree: Path, owner: int) -> None:
    (tree / "swtpm" / SOURCE / "tpm2" / "tpm2-00.permall").unlink()
    (tree / "swtpm" / SOURCE / "tpm2" / ".lock").unlink()
    (tree / "swtpm" / SOURCE / "tpm2").rmdir()
    (tree / "swtpm" / SOURCE).rmdir()
    answer = call(config, params(tree, nvram_source=None, nvram_target=None), owner)
    assert answer["result"] == {"nvram": False, "tpm": False}
    assert not (tree / "swtpm" / TARGET).exists()


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"source_uuid": "../etc"}, "invalid_params"),
        ({"target_uuid": SOURCE}, "invalid_params"),
        ({"target_uuid": TARGET.upper()}, "invalid_params"),
        ({"nvram_source": None}, "invalid_params"),
        ({"nvram_source": "relative/x.fd"}, "invalid_params"),
        ({"nvram_source": "/etc/shadow"}, "path_not_allowed"),
        ({"nvram_target": "/etc/clone_VARS.fd"}, "path_not_allowed"),
        ({"nvram_target": "/no/such/folder/x.fd"}, "not_found"),
        ({"extra": 1}, "invalid_params"),
    ],
)
def test_refusals_before_the_password(
    config: HelperConfig, tree: Path, owner: int, changes: dict[str, Any], error: str
) -> None:
    answer = call(config, params(tree, **changes), owner)
    assert answer["error"] == error
    assert answer["_asked"] == []
    assert not (tree / "swtpm" / TARGET).exists()


def test_folders_of_someone_else(config: HelperConfig, tree: Path, owner: int) -> None:
    answer = call(config, params(tree), owner + 1)
    assert answer["error"] == "not_owner"
    assert call(config, params(tree), 0)["error"] == "not_allowed"


def test_links_and_hard_links_are_refused(config: HelperConfig, tree: Path, owner: int) -> None:
    secret = tree / "secret"
    secret.write_bytes(b"secret")
    (tree / "lib" / "src" / "link.fd").symlink_to(secret)
    linked = call(config, params(tree, nvram_source=str(tree / "lib" / "src" / "link.fd")), owner)
    assert linked["error"] == "not_found"
    os.link(secret, tree / "lib" / "src" / "hard.fd")
    hard = call(config, params(tree, nvram_source=str(tree / "lib" / "src" / "hard.fd")), owner)
    assert hard["error"] == "path_not_allowed"
    (tree / "lib" / "dir-link").symlink_to(tree / "lib" / "clone")
    target = call(config, params(tree, nvram_target=str(tree / "lib" / "dir-link" / "x.fd")), owner)
    assert target["error"] == "not_found"
    assert not (tree / "lib" / "clone" / "x.fd").exists()


def test_nothing_is_overwritten(config: HelperConfig, tree: Path, owner: int) -> None:
    (tree / "lib" / "clone" / "clone_VARS.fd").write_bytes(b"mine")
    assert call(config, params(tree), owner)["error"] == "exists"
    assert (tree / "lib" / "clone" / "clone_VARS.fd").read_bytes() == b"mine"
    (tree / "lib" / "clone" / "clone_VARS.fd").unlink()
    (tree / "swtpm" / TARGET).mkdir()
    assert call(config, params(tree), owner)["error"] == "exists"
    # The NVRAM copied before the refusal is taken back.
    assert not (tree / "lib" / "clone" / "clone_VARS.fd").exists()


def test_a_link_inside_the_tpm_state_stops_the_copy(
    config: HelperConfig, tree: Path, owner: int
) -> None:
    (tree / "swtpm" / SOURCE / "tpm2" / "escape").symlink_to("/etc/passwd")
    answer = call(config, params(tree), owner)
    assert answer["error"] == "path_not_allowed"
    assert not (tree / "swtpm" / TARGET).exists()
    assert not (tree / "lib" / "clone" / "clone_VARS.fd").exists()


def test_refused_authorization_copies_nothing(config: HelperConfig, tree: Path, owner: int) -> None:
    assert call(config, params(tree), owner, allow=False)["error"] == "not_authorized"
    assert not (tree / "swtpm" / TARGET).exists()
    assert not (tree / "lib" / "clone" / "clone_VARS.fd").exists()
