"""Tell the model which developer tools this machine actually has."""

from __future__ import annotations

from agentos.engine.pipeline import TurnContext


async def inject_env_probe(ctx: TurnContext) -> TurnContext:
    """Append the local-toolchain block to the cacheable system prompt.

    This goes in the base rather than the uncached suffix on purpose: the
    probe result is constant for the process, so paying for it once per
    session beats paying for it once per turn.
    """

    prompt_cfg = getattr(ctx.config, "prompt", None) if ctx.config else None
    if not getattr(prompt_cfg, "env_probe_enabled", True):
        ctx.metadata["inject_env_probe__applied"] = False
        return ctx

    from agentos.engine.env_probe import available_tools, render_environment_block

    block = render_environment_block()
    if not block:
        ctx.metadata["inject_env_probe__applied"] = False
        return ctx

    if isinstance(ctx.system_prompt, str):
        base, suffix = ctx.system_prompt, ""
    else:
        base, suffix = ctx.system_prompt

    ctx.system_prompt = (f"{base}\n\n{block}" if base else block, suffix)
    ctx.metadata["inject_env_probe__applied"] = True
    ctx.metadata["env_probe_tool_count"] = len(available_tools())
    return ctx
