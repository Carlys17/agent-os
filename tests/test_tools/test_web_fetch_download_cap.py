"""Tests: web_fetch downloads are capped at a hard byte limit.

The display cap (max_chars) only controls what the model sees. Without a
download ceiling, a single response with an unbounded body (chunked encoding,
no content-length, or a lying content-length) is buffered fully into memory
before any truncation is applied, so one URL can exhaust the process.
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import httpx
import pytest

from agentos.sandbox.config import SandboxSettings
from agentos.sandbox.integration import configure_runtime, reset_runtime
from agentos.tools.builtin import web_fetch as wf
from agentos.tools.builtin.web_fetch import (
    _WEB_FETCH_DOWNLOAD_LIMIT_BYTES,
    _resolve_download_limit_bytes,
)


@pytest.fixture
def sandbox_off(tmp_path: Any) -> Any:
    """Configure a sandbox-off runtime so the @sandboxed tool runs inline."""
    from pathlib import Path

    configure_runtime(
        SandboxSettings(sandbox=False, security_grading=False, allow_legacy_mode=True),
        workspace=Path(tmp_path),
    )
    yield
    reset_runtime()


def _e2e_resolver(addr: str) -> Any:
    """Return a socket.getaddrinfo replacement resolving any host to addr."""

    def resolver(host: Any, port: Any, **_kw: Any) -> list[tuple[Any, ...]]:
        return [(2, 1, 6, "", (addr, 0))]

    return resolver


def _install_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Any
) -> None:
    real_async_client = httpx.AsyncClient

    def fake_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real_async_client(
            *args, transport=httpx.MockTransport(handler), **kwargs
        )

    monkeypatch.setattr("socket.getaddrinfo", _e2e_resolver("93.184.216.34"))
    monkeypatch.setattr(wf.httpx, "AsyncClient", fake_async_client)


def test_download_limit_default_and_env_override() -> None:
    assert _resolve_download_limit_bytes() == _WEB_FETCH_DOWNLOAD_LIMIT_BYTES

    with mock.patch.dict("os.environ", {"AGENTOS_WEB_FETCH_DOWNLOAD_LIMIT": "131072"}):
        assert _resolve_download_limit_bytes() == 131_072

    with mock.patch.dict("os.environ", {"AGENTOS_WEB_FETCH_DOWNLOAD_LIMIT": "100"}):
        # Values below the 64 KiB floor fall back to the default.
        assert _resolve_download_limit_bytes() == _WEB_FETCH_DOWNLOAD_LIMIT_BYTES

    with mock.patch.dict("os.environ", {"AGENTOS_WEB_FETCH_DOWNLOAD_LIMIT": "notanint"}):
        assert _resolve_download_limit_bytes() == _WEB_FETCH_DOWNLOAD_LIMIT_BYTES


@pytest.mark.asyncio
async def test_web_fetch_caps_unbounded_response_body(
    monkeypatch: pytest.MonkeyPatch,
    sandbox_off: Any,
) -> None:
    """A 2 MiB response is buffered only up to the download limit."""
    limit = 128 * 1024

    def handler(_request: httpx.Request) -> httpx.Response:
        # Non-HTML so the raw body is returned and its length is measurable.
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"A" * (2 * 1024 * 1024),
        )

    _install_transport(monkeypatch, handler)
    monkeypatch.setattr(wf, "_WEB_FETCH_DOWNLOAD_LIMIT_BYTES", limit)
    wf._cache.clear()

    result = json.loads(await wf.web_fetch(url="https://example.com/huge"))

    assert result["status"] == 200
    assert result["truncated"] is True
    # The buffered body must not exceed the download limit.
    assert result["length"] <= limit


@pytest.mark.asyncio
async def test_web_fetch_small_body_not_truncated(
    monkeypatch: pytest.MonkeyPatch,
    sandbox_off: Any,
) -> None:
    """A small body passes through without download truncation."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"hello world"
        )

    _install_transport(monkeypatch, handler)
    wf._cache.clear()

    result = json.loads(await wf.web_fetch(url="https://example.com/small"))

    assert result["status"] == 200
    assert result["truncated"] is False
    assert result["length"] == len("hello world")
    assert "hello world" in str(result["text"])
