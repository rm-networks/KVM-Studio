"""Start and stop LAN sharing (F-105, F-106), in the backend process of web mode.

Refused without a guest password. The certificate is made once; the helper
opens the HTTPS port in the firewall (firewalld or ufw) and closes it when
the backend stops. Without a helper, sharing still starts: the port may then
be closed by the firewall, which the Preferences tell.
"""

from __future__ import annotations

import sys

from .. import helper_client
from ..auth import guest
from ..auth.guest import GuestSessions, LoginLimiter
from ..auth.roles import Sharing
from ..config import Config
from ..errors import ApiException
from ..i18n import t
from ..tls import TlsError, ensure_certificate, fingerprint
from .server import LanListener, PortInUseError, bind_lan


class SharingError(Exception):
    pass


def start_sharing(config: Config) -> tuple[LanListener, Sharing]:
    if not config.web.guest_enabled or not guest.has_password():
        raise SharingError(t("cli.share_needs_password"))
    try:
        cert, key = ensure_certificate()
    except TlsError as exc:
        raise SharingError(t("cli.share_no_certificate", error=exc)) from exc
    port = config.web.https_port
    try:
        sock = bind_lan(port)
    except PortInUseError as exc:
        raise SharingError(t("cli.port_in_use", error=exc)) from exc
    sharing = Sharing(
        https_port=port,
        sessions=GuestSessions(),
        limiter=LoginLimiter(config.web.login_max_attempts),
        fingerprint=fingerprint(cert),
    )
    try:
        opened = helper_client.call("lan_port", {"open": True, "port": port})
        sharing.firewall = opened.get("firewall")
    except ApiException as exc:
        print(t("cli.share_port_not_opened", error=exc.detail), file=sys.stderr)
    return LanListener(sock, cert, key), sharing


def stop_sharing(sharing: Sharing) -> None:
    if sharing.firewall is None:
        return
    try:
        helper_client.call("lan_port", {"open": False, "port": sharing.https_port})
    except ApiException as exc:
        print(t("cli.share_port_not_closed", error=exc.detail), file=sys.stderr)
