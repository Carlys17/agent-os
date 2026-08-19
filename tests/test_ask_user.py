"""Unit tests for the side-effect-free ask_user helpers (agentos.ask_user)."""

from __future__ import annotations

import json

import pytest

from agentos.ask_user import (
    ASK_STATUS_PRESENTED,
    ask_user_payload_terminates_turn,
    build_presented_payload,
    format_questions_as_text,
    questions_from_tool_result,
    validate_questions,
)


def _question(**overrides: object) -> dict:
    base: dict = {
        "question": "Deploy now?",
        "options": [{"label": "Yes"}, {"label": "No", "description": "wait for CI"}],
    }
    base.update(overrides)
    return base


class TestValidateQuestions:
    def test_normalizes_a_valid_question(self) -> None:
        out = validate_questions([_question(header="  Deploy  ", multi_select=1)])
        assert out == [
            {
                "question": "Deploy now?",
                "options": [
                    {"label": "Yes"},
                    {"label": "No", "description": "wait for CI"},
                ],
                "multi_select": True,
                "header": "Deploy",
            }
        ]

    def test_rejects_non_list_and_empty(self) -> None:
        for bad in (None, "x", {}, []):
            with pytest.raises(ValueError, match="non-empty array"):
                validate_questions(bad)  # type: ignore[arg-type]

    def test_rejects_more_than_four_questions(self) -> None:
        with pytest.raises(ValueError, match="at most 4"):
            validate_questions([_question() for _ in range(5)])

    def test_rejects_empty_question_text(self) -> None:
        with pytest.raises(ValueError, match="question must be a non-empty string"):
            validate_questions([_question(question="   ")])

    def test_rejects_option_count_out_of_bounds(self) -> None:
        with pytest.raises(ValueError, match="between 2 and 4"):
            validate_questions([_question(options=[{"label": "only"}])])
        with pytest.raises(ValueError, match="between 2 and 4"):
            validate_questions([_question(options=[{"label": f"o{i}"} for i in range(5)])])

    def test_rejects_blank_and_duplicate_labels(self) -> None:
        with pytest.raises(ValueError, match="label must be a non-empty string"):
            validate_questions([_question(options=[{"label": "a"}, {"label": " "}])])
        with pytest.raises(ValueError, match="duplicate option label"):
            validate_questions([_question(options=[{"label": "A"}, {"label": "a"}])])


class TestPayloadHelpers:
    def test_presented_payload_terminates_turn(self) -> None:
        payload = build_presented_payload(validate_questions([_question()]))
        assert payload["status"] == ASK_STATUS_PRESENTED
        assert ask_user_payload_terminates_turn(json.dumps(payload)) is True
        assert ask_user_payload_terminates_turn(payload) is True

    def test_non_presented_content_does_not_terminate(self) -> None:
        assert ask_user_payload_terminates_turn("not json") is False
        assert ask_user_payload_terminates_turn(json.dumps({"status": "error"})) is False
        assert ask_user_payload_terminates_turn(None) is False

    def test_questions_from_tool_result_gates_on_tool_and_status(self) -> None:
        payload = json.dumps(build_presented_payload(validate_questions([_question()])))
        assert questions_from_tool_result("ask_user", payload) is not None
        assert questions_from_tool_result("exec_command", payload) is None
        assert questions_from_tool_result("ask_user", '{"status": "error"}') is None


class TestFormatQuestionsAsText:
    def test_single_question_layout(self) -> None:
        text = format_questions_as_text(validate_questions([_question(header="Deploy")]))
        assert text.splitlines() == [
            "Deploy: Deploy now?",
            "  1. Yes",
            "  2. No — wait for CI",
            "Reply with the option number(s) or your own answer.",
        ]

    def test_multi_question_numbering_and_multi_select_hint(self) -> None:
        text = format_questions_as_text(
            validate_questions(
                [
                    _question(),
                    _question(question="Which env?", multi_select=True),
                ]
            )
        )
        lines = text.splitlines()
        assert lines[0] == "Q1. Deploy now?"
        assert "Q2. Which env?" in lines
        assert "  (choose one or more)" in lines
