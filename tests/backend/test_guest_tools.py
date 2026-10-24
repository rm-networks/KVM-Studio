from __future__ import annotations

import uuid as uuidlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import libvirt
import pytest
from fastapi.testclient import TestClient

from kvmstudio.config import Config
from kvmstudio.guesttools import install
from kvmstudio.guesttools.keymaps import ALTGR, KEY, SHIFT, UnsupportedCharacter, strokes
from kvmstudio.services.library import metadata_values

from .helpers import AUTH, touch


def test_azerty_and_qwerty_tables() -> None:
    assert strokes("a", "fr") == [(KEY["Q"],)]
    assert strokes("a", "us") == [(KEY["A"],)]
    assert strokes("M", "fr") == [(SHIFT, KEY["SEMICOLON"])]
    assert strokes("1", "fr") == [(SHIFT, KEY["1"])]
    assert strokes("1", "us") == [(KEY["1"],)]
    assert strokes("./", "fr") == [(SHIFT, KEY["COMMA"]), (SHIFT, KEY["DOT"])]
    assert strokes("\\|", "fr") == [(ALTGR, KEY["8"]), (ALTGR, KEY["6"])]
    assert strokes("\\|", "us") == [(KEY["BACKSLASH"],), (SHIFT, KEY["BACKSLASH"])]


@pytest.mark.parametrize("layout", ["fr", "us"])
@pytest.mark.parametrize("command", [install.LINUX_COMMAND, install.WINDOWS_COMMAND])
def test_install_commands_can_be_typed(command: str, layout: str) -> None:
    assert len(strokes(command, layout)) == len(command)  # type: ignore[arg-type]


def test_unknown_characters_are_refused() -> None:
    with pytest.raises(UnsupportedCharacter, match="€"):
        strokes("5 €", "us")


def test_type_text_sends_one_stroke_per_character() -> None:
    sent: list[list[int]] = []
    install.type_text(sent.append, "ls -l\n", "fr", lambda _s: None)
    assert sent == [
        [KEY["L"]],
        [KEY["S"]],
        [KEY["SPACE"]],
        [KEY["6"]],
        [KEY["L"]],
        [KEY["ENTER"]],
    ]


def test_family_guesses() -> None:
    ours = (
        "<domain><metadata><kvmstudio:vm xmlns:kvmstudio="
        "'https://github.com/rm-networks/kvm-studio/ns/1.0'><kvmstudio:profile>windows11"
        "</kvmstudio:profile></kvmstudio:vm></metadata></domain>"
    )
    assert install.guess_family(ours) == "windows"
    virt_manager = (
        "<domain><metadata><libosinfo:libosinfo xmlns:libosinfo="
        "'http://libosinfo.org/xmlns/libvirt/domain/1.0'><libosinfo:os "
        "id='http://debian.org/debian/13'/></libosinfo:libosinfo></metadata></domain>"
    )
    assert install.guess_family(virt_manager) == "linux"
    assert install.guess_family("<domain/>") is None


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kvmstudio.guesttools.install.time.sleep", lambda _s: None)


@pytest.fixture
def cd_vm(conn: Any) -> Iterator[libvirt.virDomain]:
    xml = (
        f"<domain type='test'><name>gt-{uuidlib.uuid4().hex[:6]}</name><memory>65536</memory>"
        "<os><type>hvm</type></os><devices>"
        "<disk type='file' device='cdrom'><target dev='sda' bus='sata'/><readonly/></disk>"
        "</devices></domain>"
    )
    dom = conn.run(lambda c: c.defineXML(xml))
    dom.create()
    yield dom
    dom.destroy()
    dom.undefine()


def test_linux_install_types_and_remembers_the_layout(
    lib_client: TestClient, conn: Any, no_sleep: None
) -> None:
    uuid = conn.run(lambda c: c.lookupByName("test").UUIDString())
    body = {"family": "linux", "layout": "fr"}
    result = lib_client.post(f"/api/vms/{uuid}/guest-tools", headers=AUTH, json=body).json()
    assert result == {"typed": True, "drive": None}
    xml = conn.run(lambda c: c.lookupByUUIDString(uuid).XMLDesc(0))
    assert metadata_values(xml)["keyboard"] == "fr"
    info = lib_client.get(f"/api/vms/{uuid}/guest-tools", headers=AUTH).json()
    assert (info["family"], info["layout"], info["agent"]) == ("linux", "fr", False)


def test_windows_needs_the_virtio_iso(
    lib_client: TestClient, cd_vm: libvirt.virDomain, no_sleep: None
) -> None:
    body = {"family": "windows", "layout": "fr"}
    response = lib_client.post(
        f"/api/vms/{cd_vm.UUIDString()}/guest-tools", headers=AUTH, json=body
    )
    assert response.json()["error"]["code"] == "guest.no_virtio_iso"


def test_windows_inserts_virtio_win(
    lib_client: TestClient,
    lib_config: Config,
    cd_vm: libvirt.virDomain,
    tmp_path: Path,
    no_sleep: None,
) -> None:
    iso = touch(tmp_path / "iso" / "drivers" / "virtio-win.iso")
    lib_config.defaults.virtio_win_iso = iso
    body = {"family": "windows", "layout": "us"}
    url = f"/api/vms/{cd_vm.UUIDString()}/guest-tools"
    result = lib_client.post(url, headers=AUTH, json=body)
    assert result.json() == {"typed": True, "drive": "sda"}
    assert str(iso) in cd_vm.XMLDesc(0)


def test_install_refusals(lib_client: TestClient, conn: Any, no_sleep: None) -> None:
    xml = (
        "<domain type='test'><name>gt-off</name><memory>65536</memory>"
        "<os><type>hvm</type></os></domain>"
    )
    dom = conn.run(lambda c: c.defineXML(xml))
    try:
        uuid = dom.UUIDString()
        off = lib_client.post(
            f"/api/vms/{uuid}/guest-tools", headers=AUTH, json={"family": "linux", "layout": "fr"}
        )
        assert off.json()["error"]["code"] == "vm.not_running"
        bsd = lib_client.post(
            f"/api/vms/{uuid}/guest-tools", headers=AUTH, json={"family": "bsd", "layout": "fr"}
        )
        assert bsd.json()["error"]["code"] == "guest.unsupported"
    finally:
        dom.undefine()


def test_agent_status_without_agent(lib_client: TestClient, conn: Any) -> None:
    uuid = conn.run(lambda c: c.lookupByName("test").UUIDString())
    assert lib_client.get(f"/api/vms/{uuid}/agent", headers=AUTH).json() == {"responding": False}
