from __future__ import annotations

from pathlib import Path

import pytest

from kvmstudio.config import Config, ConfigError, config_dir, load_config


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "absent.toml")
    assert config == Config()
    assert config.interface.mode == "desktop"
    assert config.libvirt.uri == "qemu:///system"
    assert config.storage.vm_default_location is None


def test_example_file_is_valid() -> None:
    example = Path(__file__).resolve().parents[2] / "config.example.toml"
    assert load_config(example) == Config()


def test_values_and_home_expansion(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[interface]
mode = "web"

[storage]
vm_default_location = "~/vms"

[[iso_libraries]]
name = "Main"
path = "/srv/iso"
"""
    )
    config = load_config(path)
    assert config.interface.mode == "web"
    assert config.storage.vm_default_location == Path.home() / "vms"
    assert config.iso_libraries[0].path == Path("/srv/iso")
    assert config.iso_libraries[0].extensions == [".iso", ".img"]


@pytest.mark.parametrize(
    "content",
    [
        '[interface]\nmode = "both"\n',
        "[web]\nport = 80\n",
        "[unknown]\nkey = 1\n",
        "[web]\nport = \n",
    ],
)
def test_invalid_files_are_rejected(tmp_path: Path, content: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(content)
    with pytest.raises(ConfigError, match=str(path)):
        load_config(path)


def test_config_dir_follows_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_dir() == tmp_path / "kvm-studio"
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/path")
    assert config_dir() == Path.home() / ".config" / "kvm-studio"


def test_old_default_iso_folder_key_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[storage]\ndefault_iso_folder = "~/ISO"\n')
    assert load_config(path) == Config()
