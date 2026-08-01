from __future__ import annotations

import pytest

from agentos.provider.error_body import (
    DEFAULT_ERROR_BODY_LIMIT,
    read_bounded_body,
    summarize_error_body,
)


class _StreamingResponse:
    """Minimal stand-in for the httpx streaming response shape."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.consumed = 0

    async def aiter_bytes(self):
        for chunk in self._chunks:
            self.consumed += len(chunk)
            yield chunk


# ---------------------------------------------------------------------------
# bounded reads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_short_body_is_read_whole() -> None:
    response = _StreamingResponse([b'{"error": {"message": "nope"}}'])

    body = await read_bounded_body(response)

    assert body == b'{"error": {"message": "nope"}}'


@pytest.mark.asyncio
async def test_an_oversized_body_stops_at_the_limit() -> None:
    # A WAF block page has no size contract; the read must not follow it.
    response = _StreamingResponse([b"x" * 4096] * 100)

    body = await read_bounded_body(response)

    assert len(body) == DEFAULT_ERROR_BODY_LIMIT
    # And the rest was never pulled off the socket.
    assert response.consumed <= DEFAULT_ERROR_BODY_LIMIT + 4096


@pytest.mark.asyncio
async def test_a_response_without_streaming_falls_back_to_a_whole_read() -> None:
    class _NonStreaming:
        async def aread(self) -> bytes:
            return b'{"error": {"message": "document block malformed"}}'

    body = await read_bounded_body(_NonStreaming())

    # Losing the error entirely is worse than buffering it.
    assert summarize_error_body(body) == "document block malformed"


@pytest.mark.asyncio
async def test_the_fallback_read_is_clipped_too() -> None:
    class _NonStreaming:
        async def aread(self) -> bytes:
            return b"y" * 100_000

    body = await read_bounded_body(_NonStreaming())

    assert len(body) == DEFAULT_ERROR_BODY_LIMIT


@pytest.mark.asyncio
async def test_a_broken_stream_yields_what_arrived_instead_of_raising() -> None:
    class _Broken(_StreamingResponse):
        async def aiter_bytes(self):
            yield b"partial"
            raise RuntimeError("connection reset")

    body = await read_bounded_body(_Broken([]))

    # The HTTP error is the story; a failure reading its body must not mask it.
    assert body == b"partial"


# ---------------------------------------------------------------------------
# summaries
# ---------------------------------------------------------------------------


def test_json_error_message_is_extracted() -> None:
    body = b'{"error": {"message": "model not found", "type": "invalid_request"}}'

    assert summarize_error_body(body) == "model not found"


def test_top_level_message_is_extracted() -> None:
    assert summarize_error_body('{"message": "rate limited"}') == "rate limited"


def test_string_error_field_is_extracted() -> None:
    assert summarize_error_body('{"error": "bad key"}') == "bad key"


def test_html_block_page_collapses_to_its_title() -> None:
    body = (
        "<!DOCTYPE html><html><head><title>403 Forbidden</title></head>"
        "<body><h1>Access denied</h1>" + "<p>padding</p>" * 500 + "</body></html>"
    )

    summary = summarize_error_body(body)

    # The title carries the whole signal; the markup carries none of it.
    assert "403 Forbidden" in summary
    assert "HTML error page" in summary
    assert "<p>" not in summary
    assert len(summary) < 300


def test_html_without_a_title_still_avoids_emitting_markup() -> None:
    body = "<html><body><h1>Gateway Timeout</h1></body></html>"

    summary = summarize_error_body(body)

    assert "Gateway Timeout" in summary
    assert "<h1>" not in summary


def test_plain_text_is_truncated_visibly() -> None:
    summary = summarize_error_body("z" * 5000, max_chars=100)

    assert summary.startswith("z" * 100)
    assert "truncated" in summary
    assert "5000" in summary


def test_short_plain_text_passes_through_unchanged() -> None:
    assert summarize_error_body("upstream connect error") == "upstream connect error"


def test_empty_body_summarizes_to_nothing() -> None:
    assert summarize_error_body(b"") == ""
    assert summarize_error_body("   ") == ""


def test_invalid_utf8_does_not_raise() -> None:
    assert summarize_error_body(b"\xff\xfe broken") != ""
