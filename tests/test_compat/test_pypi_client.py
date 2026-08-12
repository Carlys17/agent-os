"""Isolated PyPI client — fully mocked, never hits the network."""

from __future__ import annotations

from typing import Any

import pytest

from agentos.compat import pypi_client


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _patch_get(monkeypatch: pytest.MonkeyPatch, fn: Any) -> None:
    import httpx

    monkeypatch.setattr(httpx, "get", fn)


def test_latest_version_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, **_: Any) -> _FakeResponse:
        assert "use-agent-os" in url
        return _FakeResponse(200, {"info": {"version": "2026.8.1"}})

    _patch_get(monkeypatch, fake_get)
    assert pypi_client.latest_version() == "2026.8.1"


def test_offline_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, **_: Any) -> _FakeResponse:
        raise OSError("network down")

    _patch_get(monkeypatch, fake_get)
    assert pypi_client.latest_version() is None


def test_non_200_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get(monkeypatch, lambda url, **_: _FakeResponse(404, {}))
    assert pypi_client.latest_version() is None


def test_malformed_body_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get(monkeypatch, lambda url, **_: _FakeResponse(200, ValueError("bad json")))
    assert pypi_client.latest_version() is None


def test_missing_version_field_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get(monkeypatch, lambda url, **_: _FakeResponse(200, {"info": {}}))
    assert pypi_client.latest_version() is None


def test_timeout_is_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        seen.update(kwargs)
        return _FakeResponse(200, {"info": {"version": "1.0"}})

    _patch_get(monkeypatch, fake_get)
    pypi_client.latest_version(timeout=2.0)
    assert seen["timeout"] == 2.0
