"""Inject the plan-mode block into the dynamic prompt suffix when active.

Plan mode toggles mid-session, so the block lives in the uncached suffix
(the ``inject_platform_hint`` pattern), never in the cacheable base.
"""

from __future__ import annotations

from agentos.engine.pipeline import TurnContext

_PLAN_MODE_BLOCK = """## Plan Mode (Active)

This session is in plan mode: research and design only.
- Mutating tools (file writes, shell, code execution, messaging, publishing,
  scheduling) are disabled for now; read, search, and analysis tools remain
  available. Never try to work around a disabled tool.
- Explore the code and context as deeply as needed, then produce ONE concrete
  implementation plan: what changes, file by file, in execution order, with
  verification steps.
- Present the finished plan by calling `exit_plan_mode` with the full plan
  text. That ends your turn; the user reviews it.
- Plan mode ends only when the user approves out of band (the plan card or
  `/plan off`). A typed "yes" does NOT end plan mode — refine if asked and
  call `exit_plan_mode` again.
- Use `ask_user` for decisions that shape the plan and are genuinely the
  user's to make."""


async def inject_plan_mode(ctx: TurnContext) -> TurnContext:
    """Append the plan-mode instructions to the uncached suffix when on."""
    from agentos.plan_mode import get_plan_mode_store

    if not get_plan_mode_store().is_enabled(ctx.session_key):
        ctx.metadata["inject_plan_mode__applied"] = False
        return ctx

    if isinstance(ctx.system_prompt, str):
        base, suffix = ctx.system_prompt, ""
    else:
        base, suffix = ctx.system_prompt

    ctx.system_prompt = (
        base,
        f"{suffix}\n\n{_PLAN_MODE_BLOCK}" if suffix else _PLAN_MODE_BLOCK,
    )
    ctx.metadata["inject_plan_mode__applied"] = True
    return ctx
