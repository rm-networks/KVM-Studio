"""User configuration, read from $XDG_CONFIG_HOME/kvm-studio/config.toml."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Annotated, Literal

import tomli_w
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, field_validator

ExpandedPath = Annotated[Path, AfterValidator(lambda p: p.expanduser())]


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class InterfaceSettings(_Section):
    mode: Literal["desktop", "web"] = "desktop"


class WebSettings(_Section):
    # HTTP on 127.0.0.1; HTTPS is for LAN sharing (V1).
    port: int = Field(default=60080, ge=1024, le=65535)
    https_port: int = Field(default=60443, ge=1024, le=65535)
    share_on_lan: bool = False
    tls: Literal["auto"] = "auto"
    guest_enabled: bool = True
    login_max_attempts: int = Field(default=5, ge=1, le=100)


class LibvirtSettings(_Section):
    uri: str = Field(default="qemu:///system", min_length=1)


class StorageSettings(_Section):
    # No generic default: the first-run assistant asks for it.
    vm_default_location: ExpandedPath | None = None


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


class WorkspaceSettings(_Section):
    # VMs are run by libvirt and QEMU: closing KVM Studio leaves them running
    # unless asked otherwise.
    on_close: Literal["keep", "ask", "suspend", "shutdown"] = "keep"
    # Reminder that VMs keep running when KVM Studio closes or changes mode.
    close_reminder: bool = True


class UiSettings(_Section):
    theme: Literal["system", "light", "dark"] = "system"
    # English unless French is chosen; the desktop language is not looked at.
    language: Literal["en", "fr"] = "en"
    # Bar of the open VM tabs above the console.
    vm_tabs: bool = True

    @field_validator("language", mode="before")
    @classmethod
    def _former_system(cls, value: object) -> object:
        # "system" (versions before 1.0.0) followed the desktop: now English.
        return "en" if value == "system" else value


class Config(_Section):
    interface: InterfaceSettings = Field(default_factory=InterfaceSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    libvirt: LibvirtSettings = Field(default_factory=LibvirtSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    iso_libraries: list[IsoLibrary] = Field(default_factory=list)
    defaults: DefaultsSettings = Field(default_factory=DefaultsSettings)
    workspace: WorkspaceSettings = Field(default_factory=WorkspaceSettings)
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


OLD_DEFAULT_PORT = 8765


def load_config(path: Path | None = None) -> Config:
    """Load the configuration file, or return defaults when it does not exist."""
    path = path or default_config_path()
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    # Dropped keys: ISO images come from [[iso_libraries]] only.
    storage = data.get("storage")
    if isinstance(storage, dict):
        storage.pop("default_iso_folder", None)
    # Former default port, written by versions that saved every value.
    web = data.get("web")
    if isinstance(web, dict) and web.get("port") == OLD_DEFAULT_PORT:
        web.pop("port")
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        lines = [f"{path}: invalid configuration"]
        for err in exc.errors():
            where = ".".join(str(part) for part in err["loc"])
            lines.append(f"  {where}: {err['msg']}")
        raise ConfigError("\n".join(lines)) from exc


HEADER = """\
# KVM Studio configuration, written by the Preferences screen.
# Every key is optional; see config.example.toml for the full list.
"""


def save_config(config: Config, path: Path | None = None) -> Path:
    """Write the configuration atomically, readable by the user only.

    Only values that differ from the defaults are written, so a default
    changed in a later version applies to everyone who never touched it.
    """
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    dumped = config.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    data = {key: value for key, value in dumped.items() if value not in ({}, [])}
    tmp = path.with_suffix(".toml.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(HEADER + "\n" + tomli_w.dumps(data))
    os.replace(tmp, path)
    return path
