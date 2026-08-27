"""Tests for the DNS-rebinding TOCTOU guard (ValidatingNetworkBackend).

The URL-level guard (validate_http_url_for_fetch) resolves a hostname and
checks the result, but httpx/httpcore then resolve the same hostname AGAIN at
connect time. With a short-TTL (rebinding) domain the two resolutions can
differ, so the guard validates one address and the socket connects to another
(e.g. 169.254.169.254). ValidatingNetworkBackend closes that window by
resolving and validating the destination itself at connect time.
"""
from __future__ import annotations

import socket

import pytest

from agentos.tools import ssrf
from agentos.tools.types import SSRFBlockedError


def _fake_getaddrinfo(ip: str):
    def resolver(hostname: str, port: int | None, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 443))]

    return resolver


@pytest.fixture(autouse=True)
def reset_trusted_fake_ip_cidrs():
    ssrf.configure_trusted_fake_ip_cidrs([])
    yield
    ssrf.configure_trusted_fake_ip_cidrs([])


# --- resolve_safe_addresses -------------------------------------------------


def test_resolve_safe_addresses_blocks_metadata(monkeypatch):
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", _fake_getaddrinfo("169.254.169.254"))
    with pytest.raises(SSRFBlockedError):
        ssrf.resolve_safe_addresses("rebind.example")


def test_resolve_safe_addresses_blocks_private(monkeypatch):
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", _fake_getaddrinfo("10.0.0.5"))
    with pytest.raises(SSRFBlockedError):
        ssrf.resolve_safe_addresses("rebind.example")


def test_resolve_safe_addresses_returns_public_ip(monkeypatch):
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    assert ssrf.resolve_safe_addresses("example.com") == ["93.184.216.34"]


def test_resolve_safe_addresses_metadata_only_allows_private(monkeypatch):
    # metadata_only flavour (http_request) keeps ordinary private reachable.
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", _fake_getaddrinfo("10.0.0.5"))
    assert ssrf.resolve_safe_addresses("internal.example", metadata_only=True) == ["10.0.0.5"]


def test_resolve_safe_addresses_metadata_only_still_blocks_metadata(monkeypatch):
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", _fake_getaddrinfo("169.254.169.254"))
    with pytest.raises(SSRFBlockedError):
        ssrf.resolve_safe_addresses("rebind.example", metadata_only=True)


# --- ValidatingNetworkBackend.connect_tcp -----------------------------------


class _RecordingBackend:
    """Fake inner backend that records the IP it was asked to connect to."""

    def __init__(self) -> None:
        self.connected: list[str] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connected.append(host)
        return object()

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        return object()

    async def sleep(self, seconds):
        return None


@pytest.mark.asyncio
async def test_backend_blocks_rebinding_to_metadata(monkeypatch):
    """The core TOCTOU: URL guard saw a public IP, but connect-time resolution
    returns the metadata endpoint. The backend must block at connect time."""
    inner = _RecordingBackend()
    backend = ssrf.ValidatingNetworkBackend(inner=inner)
    # connect-time resolution returns the metadata address.
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", _fake_getaddrinfo("169.254.169.254"))
    with pytest.raises(SSRFBlockedError):
        await backend.connect_tcp("rebind.example", 443)
    assert inner.connected == []  # never reached the socket


@pytest.mark.asyncio
async def test_backend_connects_to_validated_public_ip(monkeypatch):
    inner = _RecordingBackend()
    backend = ssrf.ValidatingNetworkBackend(inner=inner)
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    await backend.connect_tcp("example.com", 443)
    # The backend connects to the validated IP literal, not the hostname.
    assert inner.connected == ["93.184.216.34"]


@pytest.mark.asyncio
async def test_backend_blocks_metadata_ip_literal():
    inner = _RecordingBackend()
    backend = ssrf.ValidatingNetworkBackend(inner=inner)
    with pytest.raises(SSRFBlockedError):
        await backend.connect_tcp("169.254.169.254", 80)
    assert inner.connected == []


@pytest.mark.asyncio
async def test_backend_metadata_only_allows_private_literal():
    inner = _RecordingBackend()
    backend = ssrf.ValidatingNetworkBackend(metadata_only=True, inner=inner)
    await backend.connect_tcp("10.0.0.5", 80)
    assert inner.connected == ["10.0.0.5"]


@pytest.mark.asyncio
async def test_backend_blocks_metadata_hostname_by_name():
    inner = _RecordingBackend()
    backend = ssrf.ValidatingNetworkBackend(inner=inner)
    with pytest.raises(SSRFBlockedError):
        await backend.connect_tcp("metadata.google.internal", 80)
    assert inner.connected == []


# --- ssrf_guarded_client ----------------------------------------------------


def test_guarded_client_swaps_backend_on_default_pool():
    client = ssrf.ssrf_guarded_client(timeout=5.0)
    backend = client._transport._pool._network_backend
    assert isinstance(backend, ssrf.ValidatingNetworkBackend)


def test_guarded_client_metadata_only_flag():
    client = ssrf.ssrf_guarded_client(timeout=5.0, metadata_only=True)
    backend = client._transport._pool._network_backend
    assert backend._metadata_only is True
