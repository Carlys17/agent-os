"""ask_user tool: present structured choices to the user and end the turn.

The tool never blocks waiting for the answer. Presenting the question is
the whole job: the dispatch finalizer marks the result ``terminates_turn``
(see ``agentos.tools.policy.finalize``), the turn ends, and the user's
answer arrives as the next user message. Interactive surfaces render the
questions as clickable options; plain-text surfaces render a numbered list.
"""

from __future__ import annotations

import json

from agentos.ask_user import build_presented_payload, validate_questions
from agentos.tools.registry import tool
from agentos.tools.types import (
    CallerKind,
    InteractionMode,
    SafeToolError,
    UnsupportedSurfaceError,
    current_tool_context,
)


@tool(
    name="ask_user",
    description=(
        "Ask the user up to 4 structured questions, each with 2-4 options, when a "
        "decision is genuinely theirs to make and different answers lead to "
        "materially different work. The turn ends after asking; the answer arrives "
        "as the next user message. The user can always reply with their own text "
        "instead of an option, so never add an 'Other' option yourself. Do not ask "
        "when a sensible default exists — pick it and state the assumption."
    ),
    params={
        "questions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 4,
            "description": "Questions to ask; batch every open question into one call.",
            "items": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The complete question, ending with a question mark.",
                    },
                    "header": {
                        "type": "string",
                        "description": "Optional short topic label (max 24 chars).",
                    },
                    "options": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 4,
                        "description": "Distinct answer choices.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {
                                    "type": "string",
                                    "description": "Concise choice text (1-5 words).",
                                },
                                "description": {
                                    "type": "string",
                                    "description": "What choosing this option means.",
                                },
                            },
                            "required": ["label"],
                        },
                    },
                    "multi_select": {
                        "type": "boolean",
                        "description": "Allow choosing multiple options.",
                        "default": False,
                    },
                },
                "required": ["question", "options"],
            },
        },
    },
    required=["questions"],
)
async def ask_user(questions: list[object]) -> str:
    ctx = current_tool_context.get()
    if (
        ctx is not None
        and ctx.interaction_mode is InteractionMode.UNATTENDED
        and ctx.caller_kind is not CallerKind.CHANNEL
    ):
        # Runtime-surface resolution already denies the tool on unattended
        # surfaces without a human on the other end; this guard keeps the
        # contract even for contexts built outside that path. Channel turns
        # are marked unattended (no approval operator) but DO have a human
        # responder, so they pass.
        raise UnsupportedSurfaceError(
            "ask_user requires a live user, but this run is unattended. "
            "Choose a sensible default and state the assumption instead."
        )
    try:
        normalized = validate_questions(questions)
    except ValueError as exc:
        # SafeToolError keeps the validation detail visible to the model so it
        # can correct the call instead of retrying blind.
        raise SafeToolError(str(exc)) from exc
    return json.dumps(build_presented_payload(normalized))
