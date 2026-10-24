from __future__ import annotations

from pathlib import Path

import pytest

from kvmstudio.__main__ import main


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


def test_share_on_lan_is_refused_for_now(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_config(tmp_path, "[web]\nshare_on_lan = true\n")
    assert main(["--config", str(path), "--mode", "web"]) == 2
    assert "share_on_lan" in capsys.readouterr().err


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

    (conf_dir / NM_CONF_NAME).write_text(
        "[keyfile]\nunmanaged-devices=interface-name:kvmnet*;interface-name:ks-*\n"
    )
    found = _check_networkmanager(conf_dir)
    assert found is not None
    assert found.level == "ok"
    assert _check_networkmanager(tmp_path / "absent" / "conf.d") is None
