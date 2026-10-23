"""User configuration, read from $XDG_CONFIG_HOME/kvm-studio/config.toml."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

ExpandedPath = Annotated[Path, AfterValidator(lambda p: p.expanduser())]


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class InterfaceSettings(_Section):
    mode: Literal["desktop", "web"] = "desktop"


class WebSettings(_Section):
    port: int = Field(default=8765, ge=1024, le=65535)
    share_on_lan: bool = False
    tls: Literal["auto"] = "auto"
    guest_enabled: bool = True
    login_max_attempts: int = Field(default=5, ge=1, le=100)


class LibvirtSettings(_Section):
    uri: str = Field(default="qemu:///system", min_length=1)


class StorageSettings(_Section):
    # No generic default: the first-run assistant asks for it.
    vm_default_location: ExpandedPath | None = None
    default_iso_folder: ExpandedPath | None = Path("~/ISO")


class IsoLibrary(_Section):
    name: str = Field(min_length=1)
    path: ExpandedPath
    recursive: bool = True
    extensions: list[str] = Field(default_factory=lambda: [".iso", ".img"])


class DefaultsSettings(_Section):
    firmware: Literal["uefi", "bios"] = "uefi"
    disk_bus: Literal["virtio", "scsi", "sata", "nvme", "ide"] = "virtio"
    nic_model: Literal["virtio", "e1000e", "rtl8139", "vmxnet3"] = "virtio"
    virtio_win_iso: ExpandedPath | None = None


class UiSettings(_Section):
    theme: Literal["system", "light", "dark"] = "system"
    language: Literal["fr", "en"] = "fr"


class Config(_Section):
    interface: InterfaceSettings = Field(default_factory=InterfaceSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    libvirt: LibvirtSettings = Field(default_factory=LibvirtSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    iso_libraries: list[IsoLibrary] = Field(default_factory=list)
    defaults: DefaultsSettings = Field(default_factory=DefaultsSettings)
    ui: UiSettings = Field(default_factory=UiSettings)


class ConfigError(Exception):
    pass


def config_dir() -> Path:
    # The XDG spec says relative values must be ignored.
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(xdg) if os.path.isabs(xdg) else Path.home() / ".config"
    return base / "kvm-studio"


def default_config_path() -> Path:
    return config_dir() / "config.toml"


def load_config(path: Path | None = None) -> Config:
    """Load the configuration file, or return defaults when it does not exist."""
    path = path or default_config_path()
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        lines = [f"{path}: invalid configuration"]
        for err in exc.errors():
            where = ".".join(str(part) for part in err["loc"])
            lines.append(f"  {where}: {err['msg']}")
        raise ConfigError("\n".join(lines)) from exc
