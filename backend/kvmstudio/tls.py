"""Self-signed certificate of LAN sharing, made with openssl.

Valid two years and naming the computer's addresses, so that a guest's
browser can match it. It is made again when it is about to expire, when it
names other addresses than the computer has now, or when it was made for
longer than two years (by an older version): a guest then checks the new
fingerprint once.
"""

from __future__ import annotations

import hashlib
import os
import socket
import ssl
import subprocess
import time
from pathlib import Path

from .config import config_dir

DAYS = 730
RENEW_BEFORE_S = 30 * 86400
# Cipher suites of TLS 1.2 (1.3 has only AEAD ones): forward secrecy and AEAD.
CIPHERS = "ECDHE+AESGCM:ECDHE+CHACHA20"


class TlsError(Exception):
    pass


OPENSSL_TIMEOUT = 60


def tls_dir() -> Path:
    return config_dir() / "tls"


def paths(folder: Path | None = None) -> tuple[Path, Path]:
    folder = folder or tls_dir()
    return folder / "cert.pem", folder / "key.pem"


def wanted_names(addresses: list[str]) -> set[str]:
    """subjectAltName entries the certificate should have, as openssl prints them."""
    host = socket.gethostname() or "kvm-studio"
    return {f"DNS:{host}", "DNS:localhost"} | {f"IP Address:{a}" for a in addresses}


def describe(cert: Path) -> tuple[float, float, set[str]] | None:
    """(start, end, subjectAltName entries) of a certificate, or None if unreadable."""
    try:
        out = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "openssl",
                "x509",
                "-noout",
                "-startdate",
                "-enddate",
                "-ext",
                "subjectAltName",
                "-in",
                str(cert),
            ],
            capture_output=True,
            text=True,
            timeout=OPENSSL_TIMEOUT,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    dates: dict[str, float] = {}
    names: set[str] = set()
    for line in out.splitlines():
        key, _, value = line.strip().partition("=")
        if key in ("notBefore", "notAfter"):
            try:
                dates[key] = ssl.cert_time_to_seconds(value)
            except ValueError:
                return None
        elif line.startswith(" ") and ":" in line:
            names |= {n.strip() for n in line.split(",") if n.strip()}
    if len(dates) != 2:
        return None
    return dates["notBefore"], dates["notAfter"], names


def needs_renewal(cert: Path, addresses: list[str], now: float | None = None) -> bool:
    found = describe(cert)
    if found is None:
        return True
    start, end, names = found
    now = time.time() if now is None else now
    return (
        end - now < RENEW_BEFORE_S
        or end - start > (DAYS + 1) * 86400
        or names != wanted_names(addresses)
    )


def ensure_certificate(addresses: list[str], folder: Path | None = None) -> tuple[Path, Path]:
    """Certificate and key (EC P-256, two years), key readable by the user only."""
    cert, key = paths(folder)
    if cert.is_file() and key.is_file() and not needs_renewal(cert, addresses):
        return cert, key
    cert.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    host = socket.gethostname() or "kvm-studio"
    old = os.umask(0o077)
    try:
        _openssl(host, addresses, cert, key)
    finally:
        os.umask(old)
    return cert, key


def harden(context: ssl.SSLContext) -> None:
    """TLS 1.2 at least, and only ECDHE AEAD suites in TLS 1.2."""
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers(CIPHERS)


def _openssl(host: str, addresses: list[str], cert: Path, key: Path) -> None:
    names = ",".join(sorted(wanted_names(addresses))).replace("IP Address:", "IP:")
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
                f"subjectAltName={names}",
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
