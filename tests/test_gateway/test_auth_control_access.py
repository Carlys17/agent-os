from __future__ import annotations

from agentos.gateway.access import ConnectionSurface
from agentos.gateway.auth import resolve_auth
from agentos.gateway.config import AuthConfig, GatewayConfig


def test_open_auth_loopback_admits_control_without_credentials() -> None:
    access = resolve_auth(
        GatewayConfig(debug=False, host="127.0.0.1"),
        {},
        "control",
        peer_ip="127.0.0.1",
    )

    assert access is not None
    assert access.surface is ConnectionSurface.CONTROL
    assert access.admitted is True
    assert access.credential_verified is False


def test_open_auth_public_listener_fails_even_for_loopback_peer() -> None:
    access = resolve_auth(
        GatewayConfig(debug=False, host="0.0.0.0"),
        {},
        "control",
        peer_ip="127.0.0.1",
    )

    assert access is None


def test_token_auth_admits_complete_control_surface() -> None:
    access = resolve_auth(
        GatewayConfig(
            host="0.0.0.0",
            auth=AuthConfig(mode="token", token="secret"),
        ),
        {"token": "secret"},
        "control",
        peer_ip="203.0.113.7",
    )

    assert access is not None
    assert access.surface is ConnectionSurface.CONTROL
    assert access.admitted is True
    assert access.credential_verified is True


def test_token_auth_without_configured_token_fails_closed() -> None:
    config = GatewayConfig(auth=AuthConfig(mode="token", token=None))

    assert resolve_auth(config, {}, "control", peer_ip="127.0.0.1") is None
