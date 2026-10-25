"""Self-signed certificate of LAN sharing, made with openssl at the first start."""

from __future__ import annotations

import hashlib
import os
import socket
import ssl
import subprocess
from pathlib import Path

from .config import config_dir

DAYS = 3650


class TlsError(Exception):
    pass


OPENSSL_TIMEOUT = 60


def tls_dir() -> Path:
    return config_dir() / "tls"


def paths(folder: Path | None = None) -> tuple[Path, Path]:
    folder = folder or tls_dir()
    return folder / "cert.pem", folder / "key.pem"


def ensure_certificate(folder: Path | None = None) -> tuple[Path, Path]:
    """Certificate and key, generated once (EC P-256, 10 years), key readable by the user only."""
    cert, key = paths(folder)
    if cert.is_file() and key.is_file():
        return cert, key
    cert.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    host = socket.gethostname() or "kvm-studio"
    old = os.umask(0o077)
    try:
        _openssl(host, cert, key)
    finally:
        os.umask(old)
    return cert, key


def _openssl(host: str, cert: Path, key: Path) -> None:
    try:
        subprocess.run(  # noqa: S603
            [  # noqa: S607
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "ec",
                "-pkeyopt",
                "ec_paramgen_curve:prime256v1",
                "-nodes",
                "-days",
                str(DAYS),
                "-subj",
                f"/CN={host}",
                "-addext",
                f"subjectAltName=DNS:{host},DNS:localhost",
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ],
            capture_output=True,
            timeout=OPENSSL_TIMEOUT,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TlsError(str(exc)) from exc


def fingerprint(cert: Path) -> str:
    """SHA-256 fingerprint as browsers show it (AB:CD:...)."""
    der = ssl.PEM_cert_to_DER_cert(cert.read_text(encoding="ascii"))
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))
