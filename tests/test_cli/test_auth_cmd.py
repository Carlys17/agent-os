"""`agentos auth` — the split login an agent or a script can drive.

Exit codes are the contract here: a caller that cannot read prose branches on
them, so they are asserted rather than the wording around them.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from agentos import xai_oauth as oauth
from agentos.cli.auth_cmd import EXIT_STILL_PENDING, auth_app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "auth.json"
    monkeypatch.setenv("AGENTOS_AUTH_STORE", str(path))
    return path


def _pending(**overrides: Any) -> oauth.PendingDeviceLogin:
    base: dict[str, Any] = {
        "login_id": "login-1",
        "device_code": "dev-secret",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://accounts.x.ai/oauth2/device?user_code=ABCD-EFGH",
        "interval": 5,
        "expires_at": time.time() + 600,
        "token_endpoint": "https://auth.x.ai/oauth2/token",
        "discovery": {"token_endpoint": "https://auth.x.ai/oauth2/token"},
    }
    base.update(overrides)
    return oauth.PendingDeviceLogin(**base)


def _payload(result: Any) -> dict[str, Any]:
    return json.loads(result.stdout)


class TestNoWait:
    def test_it_prints_what_the_user_must_approve_and_exits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(oauth, "start_device_login", lambda **_kw: _pending())

        result = runner.invoke(auth_app, ["login", "xai", "--no-wait", "--json"])

        assert result.exit_code == 0
        payload = _payload(result)
        assert payload["status"] == "pending"
        assert payload["userCode"] == "ABCD-EFGH"
        assert payload["loginId"] == "login-1"
        # The device code is the client's half of the grant; it has no business
        # in a transcript an agent might echo.
        assert "dev-secret" not in result.stdout

    def test_a_start_failure_exits_nonzero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(**_kw: Any) -> None:
            raise oauth.XaiOAuthError("discovery failed", code="xai_discovery_failed")

        monkeypatch.setattr(oauth, "start_device_login", _boom)

        result = runner.invoke(auth_app, ["login", "xai", "--no-wait", "--json"])

        assert result.exit_code == 1
        assert _payload(result)["code"] == "xai_discovery_failed"


class TestResume:
    def test_not_approved_yet_is_its_own_exit_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Distinct from failure so a caller retries instead of giving up."""
        monkeypatch.setattr(oauth, "latest_pending_login", lambda: _pending())
        monkeypatch.setattr(oauth, "poll_device_login", lambda _p, **_kw: (False, 7))

        result = runner.invoke(auth_app, ["login", "xai", "--resume", "--json"])

        assert result.exit_code == EXIT_STILL_PENDING
        assert _payload(result) == {"status": "pending", "interval": 7, "loginId": "login-1"}

    def test_approval_completes_with_exit_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(oauth, "latest_pending_login", lambda: _pending())
        monkeypatch.setattr(oauth, "poll_device_login", lambda _p, **_kw: (True, 5))

        result = runner.invoke(auth_app, ["login", "xai", "--resume", "--json"])

        assert result.exit_code == 0
        assert _payload(result)["status"] == "complete"

    def test_nothing_pending_says_so_rather_than_hanging(self) -> None:
        result = runner.invoke(auth_app, ["login", "xai", "--resume", "--json"])

        assert result.exit_code == 1
        assert _payload(result)["status"] == "expired"

    def test_an_explicit_login_id_is_honoured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[str] = []

        def _get(login_id: str) -> oauth.PendingDeviceLogin:
            seen.append(login_id)
            return _pending(login_id=login_id)

        monkeypatch.setattr(oauth, "get_pending_login", _get)
        monkeypatch.setattr(oauth, "poll_device_login", lambda _p, **_kw: (True, 5))

        result = runner.invoke(
            auth_app, ["login", "xai", "--resume", "--login-id", "other", "--json"]
        )

        assert result.exit_code == 0
        assert seen == ["other"]

    def test_a_terminal_failure_exits_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(_p: Any, **_kw: Any) -> None:
            raise oauth.XaiOAuthError("access_denied", code="xai_device_token_failed")

        monkeypatch.setattr(oauth, "latest_pending_login", lambda: _pending())
        monkeypatch.setattr(oauth, "poll_device_login", _boom)

        result = runner.invoke(auth_app, ["login", "xai", "--resume", "--json"])

        assert result.exit_code == 1
        assert _payload(result)["status"] == "failed"


class TestArgumentHandling:
    def test_the_two_split_flags_are_mutually_exclusive(self) -> None:
        result = runner.invoke(auth_app, ["login", "xai", "--no-wait", "--resume"])
        assert result.exit_code == 2

    @pytest.mark.parametrize("command", [["login", "github"], ["logout", "github"]])
    def test_an_unknown_provider_is_refused(self, command: list[str]) -> None:
        assert runner.invoke(auth_app, command).exit_code == 2

    @pytest.mark.parametrize("alias", ["xai", "grok", "supergrok", "xai-oauth"])
    def test_the_provider_aliases_all_resolve(
        self, monkeypatch: pytest.MonkeyPatch, alias: str
    ) -> None:
        monkeypatch.setattr(oauth, "start_device_login", lambda **_kw: _pending())
        result = runner.invoke(auth_app, ["login", alias, "--no-wait", "--json"])
        assert result.exit_code == 0


class TestStatus:
    def test_status_never_prints_a_token(self) -> None:
        oauth.write_oauth_state(
            {"tokens": {"access_token": "a-token", "refresh_token": "r-token"}}
        )

        result = runner.invoke(auth_app, ["status", "--json"])

        assert result.exit_code == 0
        assert "r-token" not in result.stdout
        assert "a-token" not in result.stdout
        assert _payload(result)["xai"]["logged_in"] is True

    def test_logout_is_idempotent(self) -> None:
        oauth.write_oauth_state({"tokens": {"refresh_token": "r"}})
        assert runner.invoke(auth_app, ["logout", "xai"]).exit_code == 0
        assert runner.invoke(auth_app, ["logout", "xai"]).exit_code == 0
        assert oauth.has_oauth_credentials() is False
