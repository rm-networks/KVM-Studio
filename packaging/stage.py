"""Gather the files of the kvm-studio package under build/stage for nfpm.

Run from the repository root after building the frontend:

    python3 packaging/stage.py
    VERSION=0.4.0 nfpm package -f packaging/nfpm.yaml -p rpm -t dist/
"""

from __future__ import annotations

import compileall
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "build" / "stage"
# Files that name the product: @APP_NAME@ is replaced by its name.
TEMPLATES = [
    "desktop/kvm-studio.desktop",
    "desktop/kvm-studio-uninstall.desktop",
    "firewalld/kvm-studio.xml",
    "polkit/org.kvmstudio.helper.policy",
    "scripts/preremove.sh",
    "systemd/kvmstudio-helper.service",
    "systemd/kvmstudio-helper.socket",
]
# Not packaged by Fedora: shipped in /opt/kvm-studio/vendor.
VENDOR = ["pywebview==6.2.1", "proxy_tools==0.1.0"]


def app_name() -> str:
    init = (ROOT / "backend" / "kvmstudio" / "__init__.py").read_text()
    match = re.search(r'^APP_NAME = "(.+)"$', init, re.MULTILINE)
    if match is None:
        raise SystemExit("APP_NAME not found in backend/kvmstudio/__init__.py")
    return match.group(1)


def render_templates(name: str) -> None:
    for rel in TEMPLATES:
        target = STAGE / "files" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((ROOT / "packaging" / rel).read_text().replace("@APP_NAME@", name))
        shutil.copymode(ROOT / "packaging" / rel, target)


def main() -> int:
    dist = ROOT / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        print("Build the frontend first: cd frontend && npm ci && npm run build", file=sys.stderr)
        return 1
    shutil.rmtree(STAGE, ignore_errors=True)
    render_templates(app_name())
    lib = STAGE / "lib"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "backend" / "kvmstudio", lib / "kvmstudio", ignore=ignore)
    shutil.copytree(ROOT / "helper" / "kvmstudio_helper", lib / "kvmstudio_helper", ignore=ignore)
    shutil.copytree(dist, lib / "kvmstudio" / "static")
    vendor = STAGE / "vendor"
    pip = [sys.executable, "-m", "pip", "install", "--quiet", "--no-deps", "--no-compile"]
    subprocess.run([*pip, "--target", str(vendor), *VENDOR], check=True)  # noqa: S603
    shutil.rmtree(vendor / "bin", ignore_errors=True)
    # Bytecode owned by the package: nothing is written under /opt at run time.
    # Hash based, so it stays valid whatever mtime the package gives the files.
    for tree in (lib, vendor):
        ok = compileall.compile_dir(
            tree,
            quiet=1,
            invalidation_mode=compileall.py_compile.PycInvalidationMode.CHECKED_HASH,
        )
        if not ok:
            return 1
    print(f"Staged in {STAGE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
