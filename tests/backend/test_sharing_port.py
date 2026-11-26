"""The LAN sharing port is closed without a password, and left over ports too."""

from __future__ import annotations

from typing import Any

import pytest

from kvmstudio import helper_client
from kvmstudio.auth.guest import GuestSessions, LoginLimiter
from kvmstudio.auth.roles import Sharing
from kvmstudio.errors import ApiException
from kvmstudio.shell import sharing


def test_stopping_closes_with_the_close_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def record(op: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append((op, params))
        return {}

    monkeypatch.setattr(helper_client, "call", record)
    state = Sharing(60443, GuestSessions(), LoginLimiter(5), firewall="firewalld")
    sharing.stop_sharing(state)
    assert calls == [("close_lan_port", {})]


def test_a_leftover_port_is_closed_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(_op: str, _params: dict[str, Any]) -> dict[str, Any]:
        raise ApiException(503, "helper.unavailable", "no helper")

    monkeypatch.setattr(helper_client, "call", refuse)
    sharing.close_leftover_port()  # no helper, inactive session: nothing raised
