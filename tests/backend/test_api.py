from __future__ import annotations

from pathlib import Path

import libvirt
import pytest
from fastapi.testclient import TestClient

from kvmstudio.app import create_app
from kvmstudio.config import Config
from kvmstudio.errors import classify
from kvmstudio.frontend import find_frontend_dir
from kvmstudio.libvirt_conn import LibvirtConnection


def test_health_needs_no_token(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/api/vms", "/api/info"])
@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "test-token"}],
)
def test_api_rejects_missing_or_wrong_token(
    client: TestClient, path: str, headers: dict[str, str]
) -> None:
    response = client.get(path, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.invalid_token"


def test_non_ascii_token_is_rejected_cleanly(client: TestClient) -> None:
    response = client.get("/api/vms", headers=[(b"authorization", "Bearer é".encode())])
    assert response.status_code == 401


def test_list_vms(client: TestClient, auth: dict[str, str]) -> None:
    response = client.get("/api/vms", headers=auth)
    assert response.status_code == 200
    (vm,) = response.json()
    assert vm["name"] == "test"
    assert vm["state"] == "running"
    assert set(vm) == {
        "uuid",
        "name",
        "state",
        "vcpus",
        "memory_mib",
        "persistent",
        "folder",
        "managed",
        "drift",
        "files",
        "notes",
    }
    assert vm["folder"] == ""
    assert vm["managed"] is False


def test_info(client: TestClient, auth: dict[str, str]) -> None:
    data = client.get("/api/info", headers=auth).json()
    assert data["mode"] == "web"
    assert data["libvirt"]["driver"] == "TEST"
    assert data["ui"] == {"theme": "system", "language": "en"}


def test_foreign_host_header_is_refused(client: TestClient, auth: dict[str, str]) -> None:
    response = client.get("/api/vms", headers={**auth, "Host": "evil.example:8765"})
    assert response.status_code == 400


def test_libvirt_failure_is_reported_as_json(
    config: Config, frontend_dir: Path, auth: dict[str, str]
) -> None:
    broken = LibvirtConnection("test:///nonexistent/kvm-studio.xml")
    app = create_app(config, broken, "test-token", mode="web", frontend_dir=frontend_dir)
    response = TestClient(app, base_url="http://127.0.0.1").get("/api/vms", headers=auth)
    assert response.status_code >= 500
    error = response.json()["error"]
    assert error["code"].startswith("libvirt.")
    assert error["detail"]


def test_classify_known_and_unknown_errors() -> None:
    class FakeError(libvirt.libvirtError):
        def __init__(self, code: int | None) -> None:
            Exception.__init__(self, "boom")
            self.code = code

        def get_error_code(self) -> int | None:
            return self.code

    assert classify(FakeError(libvirt.VIR_ERR_NO_CONNECT)) == (503, "libvirt.unreachable")
    assert classify(FakeError(libvirt.VIR_ERR_ACCESS_DENIED)) == (403, "libvirt.denied")
    assert classify(FakeError(libvirt.VIR_ERR_OPERATION_TIMEOUT)) == (409, "libvirt.busy")
    assert classify(FakeError(None)) == (500, "libvirt.error")


def test_frontend_is_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "KVM Studio" in response.text


def test_missing_frontend_gives_a_hint(config: Config, conn: LibvirtConnection) -> None:
    app = create_app(config, conn, "t", mode="web", frontend_dir=None)
    response = TestClient(app, base_url="http://127.0.0.1").get("/")
    assert response.status_code == 503
    assert "npm run build" in response.text


def test_frontend_dir_override(monkeypatch: pytest.MonkeyPatch, frontend_dir: Path) -> None:
    monkeypatch.setenv("KVMSTUDIO_FRONTEND_DIR", str(frontend_dir))
    assert find_frontend_dir() == frontend_dir
