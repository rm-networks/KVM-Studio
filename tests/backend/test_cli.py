from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kvmstudio.cli import main

PACKAGED_NM_CONF = (
    Path(__file__).resolve().parents[2] / "packaging" / "networkmanager" / "90-kvm-studio.conf"
)


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(body)
    return path


def test_check_passes_on_test_driver(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vm_dir = tmp_path / "vms"
    vm_dir.mkdir()
    path = write_config(
        tmp_path,
        f'[libvirt]\nuri = "test:///default"\n[storage]\nvm_default_location = "{vm_dir}"\n',
    )
    assert main(["--config", str(path), "--check"]) == 0
    out = capsys.readouterr().out
    assert "[ OK ] libvirt: test:///default" in out
    assert "1 defined, 1 running" in out
    assert f"[ OK ] VM folder: {vm_dir}" in out


def test_check_fails_when_libvirt_is_unreachable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_config(tmp_path, '[libvirt]\nuri = "test:///nonexistent/file.xml"\n')
    assert main(["--config", str(path), "--check"]) == 1
    assert "[FAIL] libvirt" in capsys.readouterr().out


def test_check_reports_missing_folders(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_config(
        tmp_path,
        '[libvirt]\nuri = "test:///default"\n'
        f'[storage]\nvm_default_location = "{tmp_path / "nope"}"\n'
        f'[[iso_libraries]]\nname = "Lib"\npath = "{tmp_path / "noiso"}"\n',
    )
    assert main(["--config", str(path), "--check"]) == 1
    out = capsys.readouterr().out
    assert "[FAIL] VM folder" in out
    assert '[WARN] ISO library "Lib"' in out


def test_invalid_config_exits_with_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_config(tmp_path, '[interface]\nmode = "both"\n')
    assert main(["--config", str(path), "--check"]) == 2
    assert "interface.mode" in capsys.readouterr().err


def test_share_on_lan_needs_the_guest_password(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_config(tmp_path, "[web]\nshare_on_lan = true\n")
    assert main(["--config", str(path), "--mode", "web"]) == 2
    assert "guest password" in capsys.readouterr().err


def test_reload_requires_web_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_config(tmp_path, "")
    assert main(["--config", str(path), "--mode", "desktop", "--reload"]) == 2
    assert "--reload" in capsys.readouterr().err


def test_networkmanager_rule_is_checked(tmp_path: Path) -> None:
    from kvmstudio.check import NM_CONF_NAME, _check_networkmanager

    conf_dir = tmp_path / "NetworkManager" / "conf.d"
    conf_dir.mkdir(parents=True)
    missing = _check_networkmanager(conf_dir)
    assert missing is not None
    assert missing.level == "warn"
    assert "sudo install -m 644" in missing.message
    assert "packaging/networkmanager/90-kvm-studio.conf" in missing.message

    # The former [keyfile] rule can be replaced by another file: outdated.
    (conf_dir / NM_CONF_NAME).write_text(
        "[keyfile]\nunmanaged-devices=interface-name:kvmnet*;interface-name:ks-*\n"
    )
    outdated = _check_networkmanager(conf_dir)
    assert outdated is not None
    assert outdated.level == "warn"
    # The 0.1.0 rule, without vnet*: outdated too.
    (conf_dir / NM_CONF_NAME).write_text(
        "[device-kvm-studio]\nmatch-device=interface-name:kvmnet*;interface-name:ks-*\nmanaged=0\n"
    )
    assert getattr(_check_networkmanager(conf_dir), "level", None) == "warn"
    shutil.copy(PACKAGED_NM_CONF, conf_dir / NM_CONF_NAME)
    found = _check_networkmanager(conf_dir)
    assert found is not None
    assert found.level == "ok"
    assert _check_networkmanager(tmp_path / "absent" / "conf.d") is None


def test_the_packaged_rule_hides_our_interfaces_only() -> None:
    text = PACKAGED_NM_CONF.read_text()
    match = next(line for line in text.splitlines() if line.startswith("match-device="))
    assert match == "match-device=interface-name:kvmnet*;interface-name:ks-*;interface-name:vnet*"
    assert "unmanaged-devices" not in text.split("[device-kvm-studio]")[1]
