"""Backend for the interface tests: test:///default driver and a throwaway configuration."""

import os
import sys
import tempfile
from pathlib import Path

import uvicorn

port = int(sys.argv[1])
root = Path(tempfile.mkdtemp(prefix="kvmstudio-e2e-"))
(root / "iso").mkdir()
(root / "iso" / "alpine-virt-3.22.iso").write_bytes(b"\0" * 2048)
(root / "vms").mkdir()
config = root / "config.toml"
config.write_text(
    f'iso_libraries = [{{ name = "ISO", path = "{root / "iso"}" }}]\n'
    '[libvirt]\nuri = "test:///default"\n'
    f'[storage]\nvm_default_location = "{root / "vms"}"\n'
    '[ui]\nlanguage = "en"\n',
    encoding="utf-8",
)
os.environ["KVMSTUDIO_CONFIG"] = str(config)
os.environ["KVMSTUDIO_TOKEN"] = "e2e"
uvicorn.run("kvmstudio.app:create_app_from_env", factory=True, host="127.0.0.1", port=port)
