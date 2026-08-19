"""exit_plan_mode tool: present the finished plan and end the turn.

Only visible while plan mode is on (it is absent from the default surface
and enters through the plan-mode allowlist). Like ask_user, it never
blocks: presenting the plan terminates the turn via the dispatch finalizer,
and the user's approval or feedback arrives as the next user message.
Approval itself is out of band — the Web UI plan card or ``/plan off`` —
so the model can never talk itself out of plan mode.
"""

from __future__ import annotations

import json

from agentos.plan_mode import (
    build_plan_presented_payload,
    get_plan_mode_store,
    validate_plan,
)
from agentos.tools.registry import tool
from agentos.tools.types import (
    CallerKind,
    InteractionMode,
    SafeToolError,
    UnsupportedSurfaceError,
    current_tool_context,
)


@tool(
    name="exit_plan_mode",
    description=(
        "Present your finished implementation plan to the user for approval. "
        "Call this once your research is complete and the plan is concrete; the "
        "turn ends and the user reviews the plan. Plan mode stays on until the "
        "user explicitly approves — a typed 'yes' in chat does not end plan "
        "mode, so call this tool again after refining if asked."
    ),
    params={
        "plan": {
            "type": "string",
            "description": (
                "The complete implementation plan, in markdown: what will change, "
                "file by file, in execution order, with verification steps."
            ),
        },
    },
    required=["plan"],
    exposed_by_default=False,
)
async def exit_plan_mode(plan: str) -> str:
    ctx = current_tool_context.get()
    if (
        ctx is not None
        and ctx.interaction_mode is InteractionMode.UNATTENDED
        and ctx.caller_kind is not CallerKind.CHANNEL
    ):
        # Channel turns are marked unattended (no approval operator) but a
        # human responder is on the other end — the same exception ask_user
        # makes.
        raise UnsupportedSurfaceError(
            "exit_plan_mode requires a live user to approve the plan, but this run is unattended."
        )
    session_key = getattr(ctx, "session_key", None) or ""
    if not get_plan_mode_store().is_enabled(session_key):
        raise SafeToolError(
            "Plan mode is not active for this session, so there is no plan "
            "gate to exit. Proceed with the work directly."
        )
    try:
        normalized = validate_plan(plan)
    except ValueError as exc:
        raise SafeToolError(str(exc)) from exc
    return json.dumps(build_plan_presented_payload(normalized))
