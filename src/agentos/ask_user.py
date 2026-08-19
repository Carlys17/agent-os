"""Shared helpers for the ``ask_user`` tool.

This module is deliberately side-effect free (no registry imports) so the
tool-dispatch finalizer, the gateway channel renderer, and the CLI turn
stream can all import it without pulling in the tool registration path —
the same split as ``agentos.router_control`` vs
``agentos.tools.builtin.router_control``.

The tool follows an end-turn-and-resume contract: presenting a question
terminates the turn (via ``ToolResult.terminates_turn``), and the user's
answer arrives as the next user message. Nothing blocks waiting for the
answer, so the tool never races the engine's tool-execution timeout.
"""

from __future__ import annotations

import json
from typing import Any

ASK_USER_TOOL_NAME = "ask_user"

# Status stamped on a successful ask_user payload. The dispatch finalizer
# keys terminates_turn off this value, so renderers can rely on it too.
ASK_STATUS_PRESENTED = "question_presented"

MAX_QUESTIONS = 4
MIN_OPTIONS = 2
MAX_OPTIONS = 4
_MAX_QUESTION_CHARS = 500
_MAX_LABEL_CHARS = 100
_MAX_DESCRIPTION_CHARS = 300
_MAX_HEADER_CHARS = 24


def validate_questions(raw: object) -> list[dict[str, Any]]:
    """Normalize and validate the ``questions`` argument.

    Returns a list of ``{question, header?, options: [{label, description?}],
    multi_select}`` dicts with whitespace stripped and unknown keys dropped.
    Raises ``ValueError`` with an operator-readable message on any violation;
    the tool layer converts that into a ToolError the model can act on.
    """
    if not isinstance(raw, list) or not raw:
        raise ValueError("'questions' must be a non-empty array of question objects")
    if len(raw) > MAX_QUESTIONS:
        raise ValueError(f"'questions' allows at most {MAX_QUESTIONS} questions per call")

    normalized: list[dict[str, Any]] = []
    for qi, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ValueError(f"questions[{qi}] must be an object")
        question = str(item.get("question") or "").strip()
        if not question:
            raise ValueError(f"questions[{qi}].question must be a non-empty string")
        if len(question) > _MAX_QUESTION_CHARS:
            raise ValueError(f"questions[{qi}].question exceeds {_MAX_QUESTION_CHARS} characters")

        raw_options = item.get("options")
        if not isinstance(raw_options, list):
            raise ValueError(f"questions[{qi}].options must be an array")
        if not (MIN_OPTIONS <= len(raw_options) <= MAX_OPTIONS):
            raise ValueError(
                f"questions[{qi}].options must contain between {MIN_OPTIONS} and "
                f"{MAX_OPTIONS} options"
            )
        options: list[dict[str, str]] = []
        seen_labels: set[str] = set()
        for oi, opt in enumerate(raw_options, 1):
            if not isinstance(opt, dict):
                raise ValueError(f"questions[{qi}].options[{oi}] must be an object")
            label = str(opt.get("label") or "").strip()
            if not label:
                raise ValueError(f"questions[{qi}].options[{oi}].label must be a non-empty string")
            if len(label) > _MAX_LABEL_CHARS:
                raise ValueError(
                    f"questions[{qi}].options[{oi}].label exceeds {_MAX_LABEL_CHARS} characters"
                )
            if label.casefold() in seen_labels:
                raise ValueError(f"questions[{qi}] has duplicate option label: {label!r}")
            seen_labels.add(label.casefold())
            normalized_option: dict[str, str] = {"label": label}
            description = str(opt.get("description") or "").strip()
            if description:
                normalized_option["description"] = description[:_MAX_DESCRIPTION_CHARS]
            options.append(normalized_option)

        entry: dict[str, Any] = {
            "question": question,
            "options": options,
            "multi_select": bool(item.get("multi_select")),
        }
        header = str(item.get("header") or "").strip()
        if header:
            entry["header"] = header[:_MAX_HEADER_CHARS]
        normalized.append(entry)
    return normalized


def build_presented_payload(questions: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the tool-result payload for a successfully presented question."""
    return {
        "status": ASK_STATUS_PRESENTED,
        "questions": questions,
        "message": (
            "The question was presented to the user. This turn ends now; "
            "the user's answer will arrive as the next user message."
        ),
    }


def _presented_payload(content: object) -> dict[str, Any] | None:
    if isinstance(content, dict):
        payload: Any = content
    elif isinstance(content, str):
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return None
    else:
        return None
    if isinstance(payload, dict) and payload.get("status") == ASK_STATUS_PRESENTED:
        return payload
    return None


def ask_user_payload_terminates_turn(content: object) -> bool:
    """True when a tool-result payload is a successfully presented question."""
    return _presented_payload(content) is not None


def questions_from_tool_result(
    tool_name: object,
    content: object,
) -> list[dict[str, Any]] | None:
    """Extract presented questions from an ask_user tool result, else None.

    Used by text surfaces (channels, CLI) to render the question after the
    tool executed; they key off the result rather than the arguments so a
    validation failure never renders a half-formed question.
    """
    if tool_name != ASK_USER_TOOL_NAME:
        return None
    payload = _presented_payload(content)
    if payload is None:
        return None
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        return None
    return questions


def format_questions_as_text(questions: list[dict[str, Any]]) -> str:
    """Render questions as a numbered list for plain-text surfaces.

    Channels and the CLI have no buttons; the user answers by typing an
    option number or free text as their next message.
    """
    lines: list[str] = []
    multi_question = len(questions) > 1
    for qi, question in enumerate(questions, 1):
        header = str(question.get("header") or "").strip()
        title = str(question.get("question") or "").strip()
        prefix = f"Q{qi}. " if multi_question else ""
        heading = f"{prefix}{header}: {title}" if header else f"{prefix}{title}"
        lines.append(heading)
        options = question.get("options")
        for oi, option in enumerate(options if isinstance(options, list) else [], 1):
            label = str(option.get("label") or "").strip()
            description = str(option.get("description") or "").strip()
            suffix = f" — {description}" if description else ""
            lines.append(f"  {oi}. {label}{suffix}")
        if question.get("multi_select"):
            lines.append("  (choose one or more)")
    lines.append("Reply with the option number(s) or your own answer.")
    return "\n".join(lines)
