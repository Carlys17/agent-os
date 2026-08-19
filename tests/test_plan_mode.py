"""Unit tests for the side-effect-free plan-mode helpers (agentos.plan_mode)."""

from __future__ import annotations

import json

import pytest

from agentos.plan_mode import (
    PLAN_MODE_TOOL_ALLOW,
    PLAN_STATUS_PRESENTED,
    PlanModeStore,
    build_plan_presented_payload,
    exit_plan_payload_terminates_turn,
    format_plan_as_text,
    plan_from_tool_result,
    validate_plan,
)


class TestPlanModeStore:
    def test_enable_disable_roundtrip(self) -> None:
        store = PlanModeStore()
        key = "agent:main:t"
        assert store.is_enabled(key) is False
        store.enable(key)
        assert store.is_enabled(key) is True
        # No TTL: still on until an explicit disable.
        assert store.get(key) is not None
        assert store.disable(key) is True
        assert store.is_enabled(key) is False
        assert store.disable(key) is False

    def test_enable_requires_a_key(self) -> None:
        with pytest.raises(ValueError, match="session_key"):
            PlanModeStore().enable("  ")

    def test_sessions_are_independent(self) -> None:
        store = PlanModeStore()
        store.enable("agent:main:a")
        assert store.is_enabled("agent:main:b") is False


class TestAllowlist:
    def test_contains_only_read_research_tools(self) -> None:
        forbidden = {
            "write_file",
            "edit_file",
            "apply_patch",
            "exec_command",
            "execute_code",
            "background_process",
            "git_commit",
            "message",
            "publish_artifact",
            "cron",
            "gateway",
            "memory",
            "memory_save",
            "sessions_send",
            "sessions_spawn",
            "skill_create",
            "skill_edit",
            "skill_delete",
            "image_generate",
        }
        assert not (PLAN_MODE_TOOL_ALLOW & forbidden)

    def test_contains_the_exit_door_and_the_question_tool(self) -> None:
        assert "exit_plan_mode" in PLAN_MODE_TOOL_ALLOW
        assert "ask_user" in PLAN_MODE_TOOL_ALLOW


class TestPayloadHelpers:
    def test_validate_plan_normalizes_and_rejects(self) -> None:
        assert validate_plan("  do X  ") == "do X"
        with pytest.raises(ValueError, match="non-empty"):
            validate_plan("   ")
        with pytest.raises(ValueError, match="exceeds"):
            validate_plan("x" * 40_001)

    def test_presented_payload_terminates_turn(self) -> None:
        payload = build_plan_presented_payload("## Plan\n1. Do X")
        assert payload["status"] == PLAN_STATUS_PRESENTED
        assert exit_plan_payload_terminates_turn(json.dumps(payload)) is True
        assert exit_plan_payload_terminates_turn(payload) is True
        assert exit_plan_payload_terminates_turn("not json") is False
        assert exit_plan_payload_terminates_turn(json.dumps({"status": "error"})) is False

    def test_plan_from_tool_result_gates_on_tool_and_status(self) -> None:
        payload = json.dumps(build_plan_presented_payload("Do X"))
        assert plan_from_tool_result("exit_plan_mode", payload) == "Do X"
        assert plan_from_tool_result("ask_user", payload) is None
        assert plan_from_tool_result("exit_plan_mode", '{"status": "error"}') is None

    def test_format_plan_as_text_carries_the_approval_hint(self) -> None:
        text = format_plan_as_text("1. Do X")
        assert "1. Do X" in text
        assert "/plan off" in text
