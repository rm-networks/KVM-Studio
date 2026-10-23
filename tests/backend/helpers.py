"""Helpers shared by the backend tests."""

from __future__ import annotations

import shutil
import subprocess
import uuid as uuidlib
from pathlib import Path

import libvirt
import pytest

from kvmstudio.libvirt_conn import LibvirtConnection

from .conftest import TOKEN

AUTH = {"Authorization": f"Bearer {TOKEN}"}
needs_qemu_img = pytest.mark.skipif(shutil.which("qemu-img") is None, reason="needs qemu-img")


def domain_xml(name: str, disks: list[tuple[str, str]], nvram: str | None = None) -> str:
    """Test-driver domain; disks are (device, path) pairs."""
    devices = "".join(
        f"<disk type='file' device='{device}'><source file='{path}'/>"
        f"<target dev='vd{chr(97 + i)}'/></disk>"
        for i, (device, path) in enumerate(disks)
    )
    loader = (
        f"<loader readonly='yes' type='pflash'>/usr/share/edk2/ovmf/OVMF_CODE.fd</loader>"
        f"<nvram>{nvram}</nvram>"
        if nvram
        else ""
    )
    return (
        f"<domain type='test'><name>{name}</name><uuid>{uuidlib.uuid4()}</uuid>"
        f"<memory>65536</memory><os><type>hvm</type>{loader}</os>"
        f"<devices>{devices}</devices></domain>"
    )


def add_domain(
    conn: LibvirtConnection, created: list[libvirt.virDomain], xml: str
) -> libvirt.virDomain:
    dom = conn.run(lambda c: c.defineXML(xml))
    created.append(dom)
    return dom


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * 512)
    return path


def qcow2(path: Path, backing: Path | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["qemu-img", "create", "-q", "-f", "qcow2"]
    if backing:
        cmd += ["-b", str(backing), "-F", "qcow2"]
    subprocess.run([*cmd, str(path), "16M"], check=True)  # noqa: S603
    return path
