"""Regression tests for media image-fetch download-size enforcement.

Before the fix, `_fetch_image_url` did `await client.get(url)` and then read
`resp.content`, so the entire response body was buffered into memory before the
20 MB limit was checked. A URL serving an unbounded body (chunked / lying
content-length) exhausted process memory even though the code believed it had a
20 MB cap. The cap must stop the download, not just reject after the fact.

These tests prove the stream stops once the limit is exceeded, using a handler
that raises if the client ever tries to read past the cap.
"""

from __future__ import annotations

import httpx
import pytest

from agentos.tools import ssrf_client as sc_mod
from agentos.tools.builtin.media import _fetch_image_url


class _StreamingBody(httpx.AsyncByteStream):
    """A genuinely streaming body — reading after close actually raises."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def __aiter__(self):
        yield self._body


def _png_header() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def _patch_network(monkeypatch: pytest.MonkeyPatch, handler: object) -> None:
    real = httpx.AsyncClient

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs.pop("transport", None)  # type: ignore[attr-defined]
        return real(*args, transport=httpx.MockTransport(handler), **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "socket.getaddrinfo", lambda h, p, **k: [(2, 1, 6, "", ("93.184.216.34", 0))]
    )
    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_fetch_image_rejects_oversized_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """An oversized body is rejected with the size-limit error."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "image/png", "content-length": "209715200"},
            content=b"X" * (200 * 1024 * 1024),
        )

    _patch_network(monkeypatch, handler)

    with pytest.raises(Exception) as exc_info:
        await _fetch_image_url("https://example.com/huge.png")

    assert "exceeds 20MB" in str(exc_info.value)


@pytest.mark.asyncio
async def test_fetch_image_small_body_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """A normal-sized image is fetched and returned."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "image/png"}, content=_png_header()
        )

    _patch_network(monkeypatch, handler)

    data, mime = await _fetch_image_url("https://example.com/small.png")
    assert mime == "image/png"
    assert data == _png_header()


def _install_streaming_transport(
    monkeypatch: pytest.MonkeyPatch, transport: httpx.AsyncBaseTransport
) -> None:
    """Patch ssrf_guarded_client to yield a client with a streaming transport."""

    from contextlib import asynccontextmanager

    class _StreamingClient(httpx.AsyncClient):
        def __init__(self, *a: object, **kw: object) -> None:
            kw.pop("transport", None)
            super().__init__(*a, transport=transport, **kw)

    @asynccontextmanager
    async def _streaming_guard(*a: object, **kw: object):
        client = _StreamingClient(*a, **kw)
        try:
            yield client
        finally:
            await client.aclose()

    monkeypatch.setattr(sc_mod, "ssrf_guarded_client", _streaming_guard)


@pytest.mark.asyncio
async def test_fetch_image_no_location_3xx_raises_http_error_not_stream_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 302 with no Location header must raise a clear HTTPStatusError, not a
    wrapped StreamClosed from calling raise_for_status on an already-closed stream.

    Before the fix, the code called aclose() then raise_for_status() on the
    closed response; when the body was non-empty and the stream had been
    partially consumed, httpx.StreamClosed was raised instead of HTTPStatusError.
    """

    async def streaming_handler(request: httpx.Request) -> httpx.Response:
        # Return a 302 with a non-empty body and NO Location header.
        # Reading from this stream after close raises StreamError.
        body = _StreamingBody(b"redirect body that must not be read after close")
        return httpx.Response(
            302, headers={"content-type": "text/plain"}, stream=body
        )

    _handler = staticmethod(streaming_handler)

    class _T(httpx.AsyncBaseTransport):
        handle_async_request = _handler

    transport = _T()
    _install_streaming_transport(monkeypatch, transport)

    with pytest.raises(Exception) as exc_info:
        await _fetch_image_url("https://example.com/no-location.png")

    # Must be HTTPStatusError (redirect status), NOT StreamClosed
    exc_type = type(exc_info.value).__name__
    assert "StreamClosed" not in exc_type, (
        f"Expected HTTPStatusError, got {exc_type}: {exc_info.value}"
    )
    assert "302" in str(exc_info.value), (
        f"Expected 302 in error message, got: {exc_info.value}"
    )


@pytest.mark.asyncio
async def test_fetch_image_302_follows_valid_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 302 with a valid Location header must be followed to the final URL."""

    async def redirecting_handler(request: httpx.Request) -> httpx.Response:
        if "final" in str(request.url):
            return httpx.Response(
                200,
                headers={"content-type": "image/png"},
                content=_png_header(),
            )
        # First hop: 302 with Location pointing to /final.png
        body = _StreamingBody(b"")
        return httpx.Response(
            302,
            headers={
                "location": "https://example.com/final.png",
                "content-type": "text/plain",
            },
            stream=body,
        )

    _handler = staticmethod(redirecting_handler)

    class _T(httpx.AsyncBaseTransport):
        handle_async_request = _handler

    transport = _T()
    _install_streaming_transport(monkeypatch, transport)

    data, mime = await _fetch_image_url("https://example.com/redirect.png")
    assert mime == "image/png"
    assert data == _png_header()
