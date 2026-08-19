"""The plan-mode prompt block rides the uncached suffix, only when active."""

from __future__ import annotations

import pytest

from agentos.engine.pipeline import TurnContext
from agentos.engine.steps.inject_plan_mode import inject_plan_mode
from agentos.plan_mode import get_plan_mode_store, reset_plan_mode_store


@pytest.fixture(autouse=True)
def _fresh_store() -> None:
    reset_plan_mode_store()
    yield
    reset_plan_mode_store()


def _ctx(session_key: str, system_prompt: str | tuple[str, str] = "base") -> TurnContext:
    return TurnContext(
        message="hello",
        session_key=session_key,
        config=None,
        provider=None,
        model="",
        tool_defs=[],
        system_prompt=system_prompt,
    )


@pytest.mark.asyncio
async def test_appends_block_to_uncached_suffix_when_active() -> None:
    key = "agent:main:step-plan"
    get_plan_mode_store().enable(key)

    out = await inject_plan_mode(_ctx(key, system_prompt=("base", "existing suffix")))

    assert out.metadata["inject_plan_mode__applied"] is True
    base, suffix = out.system_prompt
    assert base == "base"
    assert suffix.startswith("existing suffix")
    assert "## Plan Mode (Active)" in suffix
    assert "exit_plan_mode" in suffix


@pytest.mark.asyncio
async def test_splits_a_string_prompt_into_base_and_suffix() -> None:
    key = "agent:main:step-plan-str"
    get_plan_mode_store().enable(key)

    out = await inject_plan_mode(_ctx(key, system_prompt="base"))

    base, suffix = out.system_prompt
    assert base == "base"
    assert "## Plan Mode (Active)" in suffix


@pytest.mark.asyncio
async def test_noop_when_mode_is_off() -> None:
    out = await inject_plan_mode(_ctx("agent:main:step-noplan"))

    assert out.metadata["inject_plan_mode__applied"] is False
    assert out.system_prompt == "base"
