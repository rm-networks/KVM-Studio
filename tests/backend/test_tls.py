"""Certificate of LAN sharing: two years, the computer's addresses, renewed when needed."""

from __future__ import annotations

import shutil
import socket
import ssl
import subprocess
import threading
from pathlib import Path

import pytest

from kvmstudio import tls

pytestmark = pytest.mark.skipif(not shutil.which("openssl"), reason="no openssl")


def test_two_years_with_the_addresses(tmp_path: Path) -> None:
    cert, _key = tls.ensure_certificate(["10.0.0.39"], tmp_path)
    found = tls.describe(cert)
    assert found is not None
    start, end, names = found
    assert 729 * 86400 <= end - start <= 731 * 86400
    assert "IP Address:10.0.0.39" in names
    assert "DNS:localhost" in names
    assert not tls.needs_renewal(cert, ["10.0.0.39"])


def test_renewed_when_the_addresses_change(tmp_path: Path) -> None:
    cert, _key = tls.ensure_certificate(["10.0.0.39"], tmp_path)
    before = tls.fingerprint(cert)
    assert tls.needs_renewal(cert, ["10.0.0.40"])
    tls.ensure_certificate(["10.0.0.40"], tmp_path)
    assert tls.fingerprint(cert) != before
    renewed = tls.fingerprint(cert)
    tls.ensure_certificate(["10.0.0.40"], tmp_path)
    assert tls.fingerprint(cert) == renewed  # kept while nothing changes


def test_renewed_before_it_expires(tmp_path: Path) -> None:
    cert, _key = tls.ensure_certificate([], tmp_path)
    found = tls.describe(cert)
    assert found is not None
    assert tls.needs_renewal(cert, [], now=found[1] - 10 * 86400)


def test_a_ten_year_certificate_of_an_older_version_is_replaced(tmp_path: Path) -> None:
    cert, key = tls.paths(tmp_path)
    host = socket.gethostname()
    subprocess.run(  # noqa: S603
        [
            *("openssl", "req", "-x509", "-newkey", "ec", "-nodes", "-days", "3650"),
            *("-pkeyopt", "ec_paramgen_curve:prime256v1", "-subj", f"/CN={host}"),
            *("-addext", f"subjectAltName=DNS:{host},DNS:localhost"),
            *("-keyout", str(key), "-out", str(cert)),
        ],
        capture_output=True,
        check=True,
    )
    old = tls.fingerprint(cert)
    assert tls.needs_renewal(cert, [])
    tls.ensure_certificate([], tmp_path)
    assert tls.fingerprint(cert) != old
    assert not tls.needs_renewal(cert, [])


def handshake(server: ssl.SSLContext, client: ssl.SSLContext) -> str | None:
    """Cipher agreed between the two contexts, or None when refused."""
    left, right = socket.socketpair()

    def serve() -> None:
        try:
            with server.wrap_socket(left, server_side=True) as s:
                s.recv(1)
        except (ssl.SSLError, OSError):
            pass

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        with client.wrap_socket(right, server_hostname="localhost") as s:
            agreed = s.cipher()
            s.send(b"x")
            return agreed[0] if agreed else None
    except (ssl.SSLError, OSError):
        return None
    finally:
        left.close()
        thread.join(5)


def test_tls_context_refuses_old_versions_and_cbc(tmp_path: Path) -> None:
    cert, key = tls.ensure_certificate([], tmp_path)
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert, key)
    tls.harden(server)
    assert server.minimum_version == ssl.TLSVersion.TLSv1_2
    for cipher in server.get_ciphers():
        if cipher["protocol"] == "TLSv1.2":
            assert cipher["name"].startswith("ECDHE-")
            assert cipher["aead"]

    def client(**options: object) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        for name, value in options.items():
            setattr(ctx, name, value)
        return ctx

    tls12 = client(maximum_version=ssl.TLSVersion.TLSv1_2)
    assert handshake(server, tls12) is not None
    cbc = client(maximum_version=ssl.TLSVersion.TLSv1_2)
    cbc.set_ciphers("ECDHE-ECDSA-AES128-SHA:ECDHE-ECDSA-AES256-SHA:@SECLEVEL=0")
    assert handshake(server, cbc) is None
