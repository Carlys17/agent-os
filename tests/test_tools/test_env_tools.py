"""Tests for the agent-facing env tools.

The asymmetry between the two tools is the point: listing is safe enough to
expose by default because it carries no values, while writing is hidden and
needs a human. Both halves are asserted here, along with the approval binding
that stops a grant for one variable being replayed against another.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agentos import env_store
from agentos.gateway.approval_queue import get_approval_queue, reset_approval_queue
from agentos.tools.builtin.env_tools import env_list, env_set
from agentos.tools.registry import get_default_registry
from agentos.tools.types import ToolError

SECRET = "sk-live-" + "w" * 40 + "tail"


@pytest.fixture(autouse=True)
def env_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state = tmp_path / "state"
    state.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("AGENTOS_STATE_DIR", str(state))
    monkeypatch.chdir(work)
    snapshot = dict(os.environ)
    reset_approval_queue()
    yield state
    os.environ.clear()
    os.environ.update(snapshot)
    reset_approval_queue()


@pytest.fixture
def auto_approve():
    queue = get_approval_queue()
    queue.set_settings(mode="auto-approve")
    return queue


class TestExposure:
    def test_listing_is_available_to_the_model_by_default(self) -> None:
        entry = get_default_registry().get("env_list")
        assert entry is not None and entry.spec.exposed_by_default is True

    def test_writing_is_not(self) -> None:
        # Setting a credential is an operator action; the model gets it only
        # when a session explicitly allows the tool.
        entry = get_default_registry().get("env_set")
        assert entry is not None and entry.spec.exposed_by_default is False

    def test_there_is_no_reveal_tool(self) -> None:
        # A model that can read stored credentials is one prompt injection
        # away from exfiltrating them.
        names = set(get_default_registry().list_names())
        assert not any("reveal" in name for name in names if name.startswith("env"))


class TestEnvList:
    @pytest.mark.asyncio
    async def test_never_returns_values_not_even_masked(self) -> None:
        env_store.set_env_var("OPENAI_API_KEY", SECRET)
        payload = json.loads(await env_list())
        assert SECRET not in json.dumps(payload)
        row = next(r for r in payload["vars"] if r["name"] == "OPENAI_API_KEY")
        assert row["is_set"] is True
        assert "masked" not in row and "value" not in row

    @pytest.mark.asyncio
    async def test_missing_only_filters_to_the_actionable_ones(self) -> None:
        env_store.set_env_var("OPENAI_API_KEY", SECRET)
        payload = json.loads(await env_list(missing_only=True))
        names = {r["name"] for r in payload["vars"]}
        assert "OPENAI_API_KEY" not in names
        assert "ANTHROPIC_API_KEY" in names


class TestEnvSetPolicy:
    @pytest.mark.asyncio
    async def test_denylisted_name_is_refused_before_any_approval(self) -> None:
        # Refused outright, not queued: an operator should not be given the
        # chance to wave through a sandbox escape by clicking approve.
        with pytest.raises(ToolError, match="cannot be written through AgentOS"):
            await env_set("LD_PRELOAD", "/tmp/evil.so")
        assert get_approval_queue().list_pending() == []

    @pytest.mark.asyncio
    async def test_invalid_name_is_refused(self) -> None:
        with pytest.raises(ToolError, match="Invalid environment variable name"):
            await env_set("1BAD", "x")

    @pytest.mark.asyncio
    async def test_line_break_in_value_is_refused(self) -> None:
        with pytest.raises(ToolError, match="line break"):
            await env_set("GOOD_TOKEN", "a\nINJECTED=1")


class TestEnvSetApproval:
    @pytest.mark.asyncio
    async def test_first_call_asks_for_approval_and_writes_nothing(self) -> None:
        result = json.loads(await env_set("BASE_RPC_URL", "https://rpc.example.invalid"))
        assert result["status"] == "approval_required"
        assert result["approval_id"]
        assert not env_store.env_file_path().exists()

    @pytest.mark.asyncio
    async def test_the_approval_record_does_not_carry_the_value(self) -> None:
        await env_set("OPENAI_API_KEY", SECRET)
        pending = get_approval_queue().list_pending()
        assert pending
        assert SECRET not in json.dumps(pending)

    @pytest.mark.asyncio
    async def test_write_proceeds_once_approved(self) -> None:
        first = json.loads(await env_set("BASE_RPC_URL", "https://rpc.example.invalid"))
        get_approval_queue().resolve(first["approval_id"], True)

        second = json.loads(
            await env_set(
                "BASE_RPC_URL", "https://rpc.example.invalid", approval_id=first["approval_id"]
            )
        )
        assert second["status"] == "ok"
        assert env_store.read_env_file()["BASE_RPC_URL"] == "https://rpc.example.invalid"

    @pytest.mark.asyncio
    async def test_denied_approval_does_not_write(self) -> None:
        first = json.loads(await env_set("BASE_RPC_URL", "https://rpc.example.invalid"))
        get_approval_queue().resolve(first["approval_id"], False)

        second = json.loads(
            await env_set(
                "BASE_RPC_URL", "https://rpc.example.invalid", approval_id=first["approval_id"]
            )
        )
        assert second["status"] == "approval_denied"
        assert not env_store.env_file_path().exists()

    @pytest.mark.asyncio
    async def test_pending_approval_reports_rather_than_writing(self) -> None:
        first = json.loads(await env_set("BASE_RPC_URL", "https://rpc.example.invalid"))
        second = json.loads(
            await env_set(
                "BASE_RPC_URL", "https://rpc.example.invalid", approval_id=first["approval_id"]
            )
        )
        assert second["status"] == "approval_pending"
        assert not env_store.env_file_path().exists()

    @pytest.mark.asyncio
    async def test_an_approval_cannot_be_replayed_against_another_variable(self) -> None:
        granted = json.loads(await env_set("BASE_RPC_URL", "https://rpc.example.invalid"))
        get_approval_queue().resolve(granted["approval_id"], True)

        with pytest.raises(ToolError, match="does not match the requested variable"):
            await env_set("OPENAI_API_KEY", SECRET, approval_id=granted["approval_id"])
        assert not env_store.env_file_path().exists()

    @pytest.mark.asyncio
    async def test_an_approval_cannot_be_used_twice(self) -> None:
        first = json.loads(await env_set("BASE_RPC_URL", "https://rpc.example.invalid"))
        get_approval_queue().resolve(first["approval_id"], True)
        await env_set(
            "BASE_RPC_URL", "https://rpc.example.invalid", approval_id=first["approval_id"]
        )

        with pytest.raises(ToolError, match="already consumed"):
            await env_set(
                "BASE_RPC_URL", "https://other.example.invalid", approval_id=first["approval_id"]
            )

    @pytest.mark.asyncio
    async def test_auto_approve_policy_writes_without_a_round_trip(self, auto_approve) -> None:
        result = json.loads(await env_set("BASE_RPC_URL", "https://rpc.example.invalid"))
        assert result["status"] == "ok"
        assert env_store.read_env_file()["BASE_RPC_URL"] == "https://rpc.example.invalid"

    @pytest.mark.asyncio
    async def test_result_never_echoes_the_written_value(self, auto_approve) -> None:
        result = await env_set("OPENAI_API_KEY", SECRET)
        assert SECRET not in result

    @pytest.mark.asyncio
    async def test_result_says_when_a_restart_is_needed(self, auto_approve) -> None:
        provider = json.loads(await env_set("OPENAI_API_KEY", SECRET))
        assert provider["restart_required"] is True
        other = json.loads(await env_set("MY_OWN_VARIABLE", "v"))
        assert other["restart_required"] is False
