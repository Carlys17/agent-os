"""A user route pin withdraws the ``router_control`` tool from the surface.

The pin already outranks the model inside the router step, so leaving the tool
exposed would only invite calls that cannot take effect. Denying it also drops
the Router Control prompt block, which ``TurnRunner._render_system_prompt``
renders only when the tool is present in ``tool_defs``.
"""

from __future__ import annotations

from types import SimpleNamespace

from agentos.engine.runtime import TurnRunner
from agentos.router_control import (
    HOLD_SOURCE_USER,
    RouterControlHoldStore,
    resolve_router_control_target,
)
from agentos.tools.types import ToolContext

_SESSION = "agent:main:main"


def _router_cfg() -> SimpleNamespace:
    return SimpleNamespace(
        enabled=True,
        tiers={
            "c0": {"model": "gemini-flash-lite", "provider": "openrouter"},
            "c3": {"model": "claude-opus-4-8", "provider": "openrouter"},
        },
    )


def _apply(store: RouterControlHoldStore, ctx: ToolContext) -> ToolContext:
    # The gate reads nothing but the hold store, so bind it to a stand-in rather
    # than paying for a fully wired TurnRunner.
    runner = SimpleNamespace(_router_control_hold_store=store)
    return TurnRunner._apply_user_route_pin_denies(runner, ctx)


def _pin(store: RouterControlHoldStore, tier: str = "c3") -> None:
    target = resolve_router_control_target(_router_cfg(), f"tier:{tier}")
    store.set_hold(_SESSION, target, evidence="user pin", source=HOLD_SOURCE_USER)


def test_user_pin_denies_router_control() -> None:
    store = RouterControlHoldStore()
    _pin(store)

    out = _apply(store, ToolContext(session_key=_SESSION))

    assert "router_control" in out.denied_tools


def test_no_pin_leaves_the_tool_exposed() -> None:
    out = _apply(RouterControlHoldStore(), ToolContext(session_key=_SESSION))

    assert "router_control" not in out.denied_tools


def test_model_installed_hold_does_not_hide_the_tool() -> None:
    """Hiding the tool on its own hold would strand the model with no way back."""

    store = RouterControlHoldStore()
    target = resolve_router_control_target(_router_cfg(), "tier:c3")
    store.set_hold(_SESSION, target, evidence="escalating")

    out = _apply(store, ToolContext(session_key=_SESSION))

    assert "router_control" not in out.denied_tools


def test_pin_on_another_session_does_not_leak() -> None:
    store = RouterControlHoldStore()
    _pin(store)

    out = _apply(store, ToolContext(session_key="agent:main:other"))

    assert "router_control" not in out.denied_tools


def test_existing_denies_are_preserved() -> None:
    store = RouterControlHoldStore()
    _pin(store)

    out = _apply(store, ToolContext(session_key=_SESSION, denied_tools={"exec_command"}))

    assert {"exec_command", "router_control"} <= out.denied_tools


def test_missing_session_key_is_a_no_op() -> None:
    out = _apply(RouterControlHoldStore(), ToolContext(session_key=None))

    assert "router_control" not in out.denied_tools
