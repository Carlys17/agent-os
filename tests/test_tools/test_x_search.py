"""The x_search tool: input validation, degraded detection, retries, gating.

Offline by construction — every test swaps ``httpx.AsyncClient`` for a fake, so
nothing here reaches api.x.ai or needs a credential.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from agentos.tools.builtin import x_search as x_search_mod
from agentos.tools.registry import get_default_registry
from agentos.tools.visibility import effective_tool_context

XSearch = Callable[..., Awaitable[str]]

ENV_KEY = "XAI_API_KEY"
FAKE_KEY = "placeholder-not-a-real-key"


def _x_search() -> XSearch:
    return cast(XSearch, x_search_mod.x_search.__wrapped__.__wrapped__)


def _response(payload: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request("POST", "https://api.x.ai/v1/responses"),
    )


class _Recorder:
    """Captures every request body and replays a scripted list of responses."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []
        self.timeouts: list[float] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = self

        class FakeAsyncClient:
            def __init__(self, **kwargs: object) -> None:
                pass

            async def __aenter__(self) -> FakeAsyncClient:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def post(self, url: str, **kwargs: Any) -> httpx.Response:
                recorder.requests.append(
                    {"url": url, "json": kwargs.get("json"), "headers": kwargs.get("headers")}
                )
                recorder.timeouts.append(float(kwargs.get("timeout", 0.0)))
                if not recorder.responses:
                    raise AssertionError("no scripted response left for x_search")
                response = recorder.responses.pop(0)
                response.raise_for_status()
                return response

        monkeypatch.setattr(x_search_mod.httpx, "AsyncClient", FakeAsyncClient)

    @property
    def call_count(self) -> int:
        return len(self.requests)

    @property
    def last_payload(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.requests[-1]["json"])

    @property
    def tool_definition(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.last_payload["tools"][0])


@pytest.fixture(autouse=True)
def _clean_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Point the OAuth store at an empty temp file. Without this the tests read
    # the developer's real ~/.agentos/auth.json, and a machine that happens to
    # be logged in to xAI would take the OAuth branch instead of the key path.
    monkeypatch.setenv("AGENTOS_AUTH_STORE", str(tmp_path / "auth.json"))
    monkeypatch.setenv(ENV_KEY, FAKE_KEY)
    x_search_mod.reset_x_search_runtime()
    yield
    x_search_mod.reset_x_search_runtime()


@pytest.fixture
def answered(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    recorder = _Recorder([_response({"output_text": "people are talking about it"})])
    recorder.install(monkeypatch)
    return recorder


async def _call(**kwargs: Any) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(await _x_search()(**kwargs)))


# ── Input validation happens before any HTTP call ───────────────────────────


class TestInputValidation:
    @pytest.mark.asyncio
    async def test_blank_query_is_refused(self, answered: _Recorder) -> None:
        result = await _call(query="   ")
        assert result["success"] is False
        assert "query is required" in result["error"]
        assert answered.call_count == 0

    @pytest.mark.asyncio
    async def test_handles_are_stripped_and_deduplicated_of_blanks(
        self, answered: _Recorder
    ) -> None:
        await _call(query="grok", allowed_x_handles=["@xai", "  ", "grok"])
        assert answered.tool_definition["allowed_x_handles"] == ["xai", "grok"]

    @pytest.mark.asyncio
    async def test_more_than_ten_handles_is_refused(self, answered: _Recorder) -> None:
        result = await _call(query="grok", allowed_x_handles=[f"h{i}" for i in range(11)])
        assert result["success"] is False
        assert "at most 10 handles" in result["error"]
        assert answered.call_count == 0

    @pytest.mark.asyncio
    async def test_allowed_and_excluded_together_is_refused(self, answered: _Recorder) -> None:
        result = await _call(query="grok", allowed_x_handles=["a"], excluded_x_handles=["b"])
        assert result["success"] is False
        assert "cannot be used together" in result["error"]
        assert answered.call_count == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", ["2026-13-01", "08/10/2026", "yesterday", "2026-8"])
    async def test_a_malformed_date_never_reaches_xai(
        self, answered: _Recorder, bad: str
    ) -> None:
        result = await _call(query="grok", from_date=bad)
        assert result["success"] is False
        assert "must be YYYY-MM-DD" in result["error"]
        assert answered.call_count == 0

    @pytest.mark.asyncio
    async def test_an_inverted_range_is_refused(self, answered: _Recorder) -> None:
        result = await _call(query="grok", from_date="2026-08-10", to_date="2026-08-01")
        assert result["success"] is False
        assert "must be on or before" in result["error"]
        assert answered.call_count == 0

    @pytest.mark.asyncio
    async def test_a_future_from_date_is_refused(self, answered: _Recorder) -> None:
        tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
        result = await _call(query="grok", from_date=tomorrow)
        assert result["success"] is False
        assert "in the future" in result["error"]
        assert answered.call_count == 0

    @pytest.mark.asyncio
    async def test_a_future_to_date_is_allowed(self, answered: _Recorder) -> None:
        """"From yesterday to tomorrow" is how a caller asks for posts as they arrive."""
        tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
        result = await _call(query="grok", to_date=tomorrow)
        assert result["success"] is True
        assert answered.tool_definition["to_date"] == tomorrow

    @pytest.mark.asyncio
    async def test_an_unknown_reasoning_effort_is_refused(
        self, answered: _Recorder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(x_search_mod, "_active_reasoning_effort", "turbo")
        result = await _call(query="grok")
        assert result["success"] is False
        assert "reasoning_effort must be one of" in result["error"]
        assert answered.call_count == 0


# ── Request shape ───────────────────────────────────────────────────────────


class TestRequestShape:
    @pytest.mark.asyncio
    async def test_an_unfiltered_query_sends_only_the_tool_type(
        self, answered: _Recorder
    ) -> None:
        await _call(query="what is happening")
        assert answered.tool_definition == {"type": "x_search"}
        assert answered.last_payload["store"] is False
        assert "reasoning" not in answered.last_payload

    @pytest.mark.asyncio
    async def test_every_filter_is_forwarded(self, answered: _Recorder) -> None:
        await _call(
            query="grok",
            excluded_x_handles=["@spam"],
            from_date="2026-08-01",
            to_date="2026-08-09",
            enable_image_understanding=True,
            enable_video_understanding=True,
        )
        assert answered.tool_definition == {
            "type": "x_search",
            "excluded_x_handles": ["spam"],
            "from_date": "2026-08-01",
            "to_date": "2026-08-09",
            "enable_image_understanding": True,
            "enable_video_understanding": True,
        }

    @pytest.mark.asyncio
    async def test_reasoning_effort_is_sent_when_configured(
        self, answered: _Recorder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(x_search_mod, "_active_reasoning_effort", "low")
        await _call(query="grok")
        assert answered.last_payload["reasoning"] == {"effort": "low"}

    @pytest.mark.asyncio
    async def test_the_bearer_is_the_resolved_key(self, answered: _Recorder) -> None:
        await _call(query="grok")
        assert answered.requests[-1]["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"


# ── Response parsing ────────────────────────────────────────────────────────


class TestResponseParsing:
    @pytest.mark.asyncio
    async def test_answer_falls_back_to_message_content(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _Recorder(
            [
                _response(
                    {
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {"type": "output_text", "text": "first"},
                                    {"type": "text", "text": "second"},
                                ],
                            },
                            {"type": "reasoning", "content": [{"type": "text", "text": "skip"}]},
                        ]
                    }
                )
            ]
        )
        recorder.install(monkeypatch)
        result = await _call(query="grok")
        assert result["answer"] == "first\n\nsecond"

    @pytest.mark.asyncio
    async def test_inline_citations_are_extracted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = _Recorder(
            [
                _response(
                    {
                        "output_text": "answer",
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "answer",
                                        "annotations": [
                                            {
                                                "type": "url_citation",
                                                "url": "https://x.com/example/status/1",
                                                "title": "a post",
                                                "start_index": 0,
                                                "end_index": 6,
                                            },
                                            {"type": "file_citation", "url": "ignored"},
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                )
            ]
        )
        recorder.install(monkeypatch)
        result = await _call(query="grok")
        assert result["inline_citations"] == [
            {
                "url": "https://x.com/example/status/1",
                "title": "a post",
                "start_index": 0,
                "end_index": 6,
            }
        ]

    @pytest.mark.asyncio
    async def test_credential_source_is_always_the_api_key_path(
        self, answered: _Recorder
    ) -> None:
        """AgentOS has no xAI OAuth, unlike hermes-agent. The field stays for shape."""
        result = await _call(query="grok")
        assert result["credential_source"] == "xai"


# ── Degraded detection ──────────────────────────────────────────────────────


class TestDegradedDetection:
    @pytest.mark.asyncio
    async def test_a_filtered_query_with_no_citations_is_degraded(
        self, answered: _Recorder
    ) -> None:
        result = await _call(query="grok", allowed_x_handles=["xai"], from_date="2026-08-01")
        assert result["degraded"] is True
        assert "allowed_x_handles" in result["degraded_reason"]
        assert "from_date" in result["degraded_reason"]

    @pytest.mark.asyncio
    async def test_an_unfiltered_query_with_no_citations_is_not_degraded(
        self, answered: _Recorder
    ) -> None:
        """A broad answer with no citations is just an answer, not a filter miss."""
        result = await _call(query="grok")
        assert result["degraded"] is False
        assert result["degraded_reason"] is None

    @pytest.mark.asyncio
    async def test_top_level_citations_clear_the_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _Recorder(
            [_response({"output_text": "answer", "citations": ["https://x.com/a/status/1"]})]
        )
        recorder.install(monkeypatch)
        result = await _call(query="grok", allowed_x_handles=["xai"])
        assert result["degraded"] is False

    @pytest.mark.asyncio
    async def test_inline_citations_alone_clear_the_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _Recorder(
            [
                _response(
                    {
                        "output_text": "answer",
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "answer",
                                        "annotations": [
                                            {"type": "url_citation", "url": "https://x.com/a/1"}
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                )
            ]
        )
        recorder.install(monkeypatch)
        result = await _call(query="grok", excluded_x_handles=["spam"])
        assert result["degraded"] is False


# ── Failure handling ────────────────────────────────────────────────────────


class TestFailureHandling:
    @pytest.mark.asyncio
    async def test_a_5xx_is_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(x_search_mod, "_active_retries", 2)
        recorder = _Recorder(
            [
                _response({"error": "upstream"}, status=503),
                _response({"output_text": "recovered"}),
            ]
        )
        recorder.install(monkeypatch)
        monkeypatch.setattr(x_search_mod.asyncio, "sleep", _no_sleep)
        result = await _call(query="grok")
        assert result["success"] is True
        assert result["answer"] == "recovered"
        assert recorder.call_count == 2

    @pytest.mark.asyncio
    async def test_a_4xx_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A bad key or a model without x_search access fails the same way every time."""
        recorder = _Recorder([_response({"code": "invalid_request", "error": "no access"}, 400)])
        recorder.install(monkeypatch)
        result = await _call(query="grok")
        assert result["success"] is False
        assert result["error"] == "invalid_request: no access"
        assert recorder.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_stop_at_the_configured_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(x_search_mod, "_active_retries", 1)
        recorder = _Recorder([_response({"error": "upstream"}, 500) for _ in range(3)])
        recorder.install(monkeypatch)
        monkeypatch.setattr(x_search_mod.asyncio, "sleep", _no_sleep)
        result = await _call(query="grok")
        assert result["success"] is False
        assert recorder.call_count == 2

    @pytest.mark.asyncio
    async def test_an_exhausted_total_budget_reports_a_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(x_search_mod, "_active_total_timeout_seconds", 0.0)
        recorder = _Recorder([_response({"output_text": "never reached"})])
        recorder.install(monkeypatch)
        result = await _call(query="grok")
        assert result["success"] is False
        assert "timed out" in result["error"]
        assert recorder.call_count == 0

    @pytest.mark.asyncio
    async def test_an_attempt_never_outlives_the_total_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(x_search_mod, "_active_timeout_seconds", 180.0)
        monkeypatch.setattr(x_search_mod, "_active_total_timeout_seconds", 20.0)
        recorder = _Recorder([_response({"output_text": "ok"})])
        recorder.install(monkeypatch)
        await _call(query="grok")
        assert recorder.timeouts[0] <= 20.0

    @pytest.mark.asyncio
    async def test_a_coarse_clock_cannot_stretch_the_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A same-tick clock must not hand an attempt more than the total budget.

        Windows resolves ``monotonic()`` to ~15.6ms, so both reads routinely land
        on the same tick and ``deadline - now`` collapses to ``(t + 20.0) - t`` —
        which rounds *above* 20.0 for many values of ``t``. Pinning the clock
        reproduces on any platform what CI hits intermittently on Windows.
        """
        stuck = 32754.452514458473  # (stuck + 20.0) - stuck == 20.000000000003638
        assert (stuck + 20.0) - stuck > 20.0, "witness no longer rounds up"
        monkeypatch.setattr(x_search_mod.time, "monotonic", lambda: stuck)
        monkeypatch.setattr(x_search_mod, "_active_timeout_seconds", 180.0)
        monkeypatch.setattr(x_search_mod, "_active_total_timeout_seconds", 20.0)
        recorder = _Recorder([_response({"output_text": "ok"})])
        recorder.install(monkeypatch)
        await _call(query="grok")
        assert recorder.timeouts[0] <= 20.0

    @pytest.mark.asyncio
    async def test_an_error_body_is_bounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = _Recorder([_response({"error": "x" * 5000}, 500)])
        recorder.install(monkeypatch)
        monkeypatch.setattr(x_search_mod, "_active_retries", 0)
        result = await _call(query="grok")
        assert len(result["error"]) <= 500

    @pytest.mark.asyncio
    async def test_the_api_key_never_appears_in_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _Recorder([_response({"error": "unauthorized"}, 401)])
        recorder.install(monkeypatch)
        raw = await _x_search()(query="grok")
        assert FAKE_KEY not in raw

    @pytest.mark.asyncio
    async def test_a_missing_credential_is_reported_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ENV_KEY, raising=False)
        x_search_mod.reset_x_search_runtime()
        result = await _call(query="grok")
        assert result["success"] is False
        assert "No xAI credentials available" in result["error"]


async def _no_sleep(_seconds: float) -> None:
    return None


# ── Configuration and visibility ────────────────────────────────────────────


class _Cfg:
    def __init__(self, **kwargs: Any) -> None:
        defaults = {
            "enabled": True,
            "model": "grok-4.5",
            "base_url": "https://api.x.ai/v1",
            "api_key": "",
            "api_key_env": ENV_KEY,
            "reasoning_effort": "",
            "timeout_seconds": 180.0,
            "total_timeout_seconds": 300.0,
            "retries": 2,
        }
        defaults.update(kwargs)
        for key, value in defaults.items():
            setattr(self, key, value)


class TestConfiguration:
    def test_the_config_model_and_the_tool_agree_on_every_default(self) -> None:
        """Two sources of "the default" exist and must not drift.

        ``XSearchConfig`` supplies the setup form and the TOML defaults;
        the module constants supply the no-config path in
        ``configure_x_search(None)``. Onboarding reads only the former, so a
        silent divergence would make the form advertise settings the runtime
        does not use.
        """
        from agentos.gateway.config import XSearchConfig

        defaults = XSearchConfig()
        assert defaults.model == x_search_mod.DEFAULT_X_SEARCH_MODEL
        assert defaults.base_url == x_search_mod.DEFAULT_X_SEARCH_BASE_URL
        assert defaults.api_key_env == x_search_mod.DEFAULT_X_SEARCH_API_KEY_ENV
        assert defaults.timeout_seconds == x_search_mod.DEFAULT_X_SEARCH_TIMEOUT_SECONDS
        assert (
            defaults.total_timeout_seconds
            == x_search_mod.DEFAULT_X_SEARCH_TOTAL_TIMEOUT_SECONDS
        )
        assert defaults.retries == x_search_mod.DEFAULT_X_SEARCH_RETRIES

    def test_the_config_literal_covers_every_accepted_effort(self) -> None:
        from typing import get_args

        from agentos.gateway.config import XSearchConfig

        allowed = set(get_args(XSearchConfig.model_fields["reasoning_effort"].annotation))
        assert allowed == {"", *x_search_mod.X_SEARCH_REASONING_EFFORTS}

    def test_retries_survive_the_default_timeouts(self) -> None:
        """A budget-aware retry loop must not silently disable retries at boot."""
        x_search_mod.configure_x_search(_Cfg())
        assert x_search_mod._active_retries == 2

    def test_an_explicit_key_beats_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ENV_KEY, "from-env")
        x_search_mod.configure_x_search(_Cfg(api_key="from-config"))
        assert x_search_mod._resolve_api_key() == "from-config"

    def test_a_custom_env_var_is_honored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_XAI_KEY", "from-custom-env")
        x_search_mod.configure_x_search(_Cfg(api_key_env="MY_XAI_KEY"))
        assert x_search_mod._resolve_api_key() == "from-custom-env"

    @pytest.mark.parametrize(
        "base_url",
        ["http://api.x.ai/v1", "https://169.254.169.254/latest", ""],
    )
    def test_an_unusable_base_url_falls_back_to_the_default(self, base_url: str) -> None:
        x_search_mod.configure_x_search(_Cfg(base_url=base_url))
        assert x_search_mod._active_base_url == "https://api.x.ai/v1"

    def test_a_trailing_slash_is_trimmed(self) -> None:
        x_search_mod.configure_x_search(_Cfg(base_url="https://proxy.example.test/v1/"))
        assert x_search_mod._active_base_url == "https://proxy.example.test/v1"

    def test_disabling_hides_the_tool_even_with_a_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ENV_KEY, FAKE_KEY)
        x_search_mod.configure_x_search(_Cfg(enabled=False))
        assert x_search_mod.x_search_available() is False


class TestCredentialSelection:
    """OAuth wins over an API key: it spends a subscription the user already has."""

    @staticmethod
    def _login(monkeypatch: pytest.MonkeyPatch, token: str = "oauth-access-token") -> None:
        from agentos import xai_oauth

        async def _resolve(**_kwargs: Any) -> tuple[str, str]:
            return token, "https://api.x.ai/v1"

        monkeypatch.setattr(xai_oauth, "resolve_oauth_bearer", _resolve)

    @pytest.mark.asyncio
    async def test_oauth_is_preferred_over_the_api_key(
        self, answered: _Recorder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._login(monkeypatch)
        result = await _call(query="grok")
        assert result["credential_source"] == "xai-oauth"
        assert answered.requests[-1]["headers"]["Authorization"] == "Bearer oauth-access-token"

    @pytest.mark.asyncio
    async def test_the_api_key_is_used_when_no_login_exists(
        self, answered: _Recorder
    ) -> None:
        result = await _call(query="grok")
        assert result["credential_source"] == "xai"
        assert answered.requests[-1]["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"

    @pytest.mark.asyncio
    async def test_a_broken_login_is_reported_rather_than_skipped(
        self, answered: _Recorder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falling back would turn "your login expired" into "no credentials"."""
        from agentos import xai_oauth

        async def _resolve(**_kwargs: Any) -> tuple[str, str]:
            raise xai_oauth.XaiOAuthError(
                "xAI refused this OAuth account for API access (HTTP 403).",
                code="xai_oauth_tier_denied",
            )

        monkeypatch.setattr(xai_oauth, "resolve_oauth_bearer", _resolve)
        result = await _call(query="grok")
        assert result["success"] is False
        assert result["error_type"] == "xai_oauth_tier_denied"
        assert answered.call_count == 0

    @pytest.mark.asyncio
    async def test_the_oauth_base_url_overrides_the_configured_one(
        self, answered: _Recorder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bearer belongs to the OAuth origin, not to x_search.base_url."""
        from agentos import xai_oauth

        async def _resolve(**_kwargs: Any) -> tuple[str, str]:
            return "oauth-token", "https://staging.x.ai/v1"

        monkeypatch.setattr(xai_oauth, "resolve_oauth_bearer", _resolve)
        monkeypatch.setattr(x_search_mod, "_active_base_url", "https://proxy.example.test/v1")
        await _call(query="grok")
        assert answered.requests[-1]["url"] == "https://staging.x.ai/v1/responses"

    def test_a_stored_login_alone_makes_the_tool_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentos import xai_oauth

        monkeypatch.delenv(ENV_KEY, raising=False)
        x_search_mod.reset_x_search_runtime()
        assert x_search_mod.x_search_available() is False

        xai_oauth.write_oauth_state({"tokens": {"refresh_token": "r-1"}})
        assert x_search_mod.x_search_available() is True

    def test_availability_never_makes_a_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It runs on every tool-surface rebuild; a network call there is a per-turn cost."""
        from agentos import xai_oauth

        monkeypatch.delenv(ENV_KEY, raising=False)
        xai_oauth.write_oauth_state({"tokens": {"refresh_token": "r-1"}})

        def _explode(**_kwargs: Any) -> None:
            raise AssertionError("availability must not open a client")

        monkeypatch.setattr(xai_oauth.httpx, "AsyncClient", _explode)
        monkeypatch.setattr(xai_oauth.httpx, "Client", _explode)
        assert x_search_mod.x_search_available() is True


class TestToolVisibility:
    @staticmethod
    def _visible() -> bool:
        from agentos.tools.policy_runtime import (
            detect_runtime_tool_surface_capabilities,
            resolve_runtime_tool_surface,
        )

        ctx = resolve_runtime_tool_surface(
            effective_tool_context(session_key="chat:test", agent_id="main"),
            capabilities=detect_runtime_tool_surface_capabilities(),
        )
        return "x_search" in {d.name for d in get_default_registry().to_tool_definitions(ctx)}

    def test_the_tool_is_registered(self) -> None:
        assert "x_search" in get_default_registry().list_names()

    def test_no_credential_keeps_the_schema_out_of_the_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool schemas cost tokens on every call, so an unusable tool must not ship one."""
        monkeypatch.delenv(ENV_KEY, raising=False)
        x_search_mod.reset_x_search_runtime()
        assert self._visible() is False

    def test_a_credential_surfaces_the_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_KEY, FAKE_KEY)
        x_search_mod.reset_x_search_runtime()
        assert self._visible() is True

    def test_the_web_group_covers_x_search(self) -> None:
        """``deny = ["group:web"]`` should cut the route to api.x.ai too."""
        from agentos.tools.policy_config import expand_selectors

        available = frozenset(get_default_registry().list_names())
        assert "x_search" in expand_selectors(frozenset({"group:web"}), available)
