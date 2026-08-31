"""Regression tests for Slack webhook signature verification (issue #680)."""

from __future__ import annotations

from agentos.channels.slack import SlackChannel


def test_verify_signature_handles_non_utf8_body() -> None:
    """A non-UTF-8 body must not raise UnicodeDecodeError in _verify_signature."""
    channel = SlackChannel(
        token="xoxb-test",
        slack_channel_id="C1",
        signing_secret="test_secret",
    )
    body = b"\x80\x81\x82\xff\xfe"  # invalid UTF-8, valid latin-1
    # Must return a bool (False for a junk signature), not raise
    result = channel._verify_signature(body, "12345", "v0=junk")  # noqa: SLF001
    assert result is False


def test_verify_signature_still_accepts_valid_utf8() -> None:
    """UTF-8 bodies keep working with the latin-1 decode."""
    import hashlib
    import hmac as hmac_mod

    channel = SlackChannel(
        token="xoxb-test",
        slack_channel_id="C1",
        signing_secret="test_secret",
    )
    body = b'{"type": "event_callback"}'
    timestamp = "1234567890"
    sig_basestring = f"v0:{timestamp}:{body.decode('latin-1')}"
    expected = (
        "v0="
        + hmac_mod.HMAC(
            b"test_secret",
            sig_basestring.encode(),
            hashlib.sha256,
        ).hexdigest()
    )
    result = channel._verify_signature(  # noqa: SLF001
        body, timestamp, expected
    )
    assert result is True
