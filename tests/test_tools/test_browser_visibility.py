"""Browser tool visibility, cron exclusion, and the routing hints in its description."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agentos.tools.builtin import browser as browser_mod
from agentos.tools.policy_runtime import (
    ToolSurfaceCapabilities,
    resolve_runtime_tool_surface,
)
from agentos.tools.registry import get_default_registry
from agentos.tools.types import CRON_AGENT_ALLOW, CallerKind, InteractionMode, ToolContext
from agentos.tools.visibility import is_tool_visible


def _browser_tool():
    tool = get_default_registry().get("browser")
    assert tool is not None, "browser tool must be registered"
    return tool


def _ctx(browser_capable: bool) -> ToolContext:
    base = ToolContext(caller_kind=CallerKind.AGENT, interaction_mode=InteractionMode.INTERACTIVE)
    return resolve_runtime_tool_surface(
        base, capabilities=ToolSurfaceCapabilities(browser=browser_capable)
    )


def test_visible_when_capability_present() -> None:
    assert is_tool_visible(_browser_tool(), _ctx(browser_capable=True)) is True


def test_hidden_when_capability_absent() -> None:
    assert is_tool_visible(_browser_tool(), _ctx(browser_capable=False)) is False


def test_browser_excluded_from_cron_allowlist() -> None:
    # The cron surface is a strict allowlist; browser must never be on it.
    assert "browser" not in CRON_AGENT_ALLOW


def test_browser_denied_on_cron_context() -> None:
    cron_ctx = ToolContext(
        caller_kind=CallerKind.CRON,
        interaction_mode=InteractionMode.UNATTENDED,
        allowed_tools=set(CRON_AGENT_ALLOW),
    )
    resolved = resolve_runtime_tool_surface(
        cron_ctx, capabilities=ToolSurfaceCapabilities(browser=True)
    )
    assert is_tool_visible(_browser_tool(), resolved) is False


# ---------------------------------------------------------------------------
# Routing: the model has to pick this tool on its own from the description.
# ---------------------------------------------------------------------------


def _config(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "enabled": True,
        "headless": True,
        "binary_path": "",
        "cdp_port": 0,
        "attach_confirmed": False,
        "persist_profile": False,
        "session_ttl_minutes": 15,
        "max_sessions": 3,
        "allowed_domains": [],
        "snapshot_max_chars": 24000,
        "dialog_policy": "must_respond",
        "dialog_timeout_s": 300.0,
        "restrict_evaluate": False,
        "allow_unsafe_evaluate": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _restore_runtime() -> Any:
    yield
    browser_mod.reset_browser_runtime()


def test_description_tells_the_model_to_honor_an_explicit_browser_request() -> None:
    """A user who names a site or says "search Google" must not be routed to
    web_search — that regression is what made the tool look missing."""
    description = _browser_tool().spec.description
    assert "search Google" in description
    assert "always wins" in description
    assert "do not substitute" in description.lower()


def test_attach_mode_hint_prefers_browser_for_search() -> None:
    browser_mod.configure_browser(_config(cdp_port=9222, attach_confirmed=True))
    hint = browser_mod.browser_mode_hint()
    assert "visible browser" in hint
    assert "prefer this tool over web_search" in hint


def test_headless_hint_warns_about_captcha() -> None:
    browser_mod.configure_browser(_config(cdp_port=0))
    hint = browser_mod.browser_mode_hint()
    assert "headless" in hint
    assert "CAPTCHA" in hint
    assert "web_search" in hint


def test_execution_ceiling_clears_the_worst_single_call() -> None:
    """navigate is open + snapshot; the harness ceiling must sit above their sum,
    or it cuts a call the adapter still considers live."""
    from agentos.tools import agent_browser

    worst_call = agent_browser.FIRST_OPEN_TIMEOUT + agent_browser.DEFAULT_COMMAND_TIMEOUT
    ceiling = _browser_tool().spec.execution_timeout_seconds
    assert ceiling is not None
    assert ceiling > worst_call


def test_denying_web_access_also_denies_the_browser() -> None:
    """``deny = ["group:web"]`` means "no web" — a full browser is not an
    exception to that."""
    from agentos.tools.policy_config import _TOOL_GROUPS

    assert "browser" in _TOOL_GROUPS["group:web"]
    assert _TOOL_GROUPS["group:browser"] == frozenset({"browser"})


def test_registry_appends_the_mode_hint_to_the_exported_description() -> None:
    browser_mod.configure_browser(_config(cdp_port=9222, attach_confirmed=True))
    registry = get_default_registry()
    ctx = ToolContext(caller_kind=CallerKind.AGENT, interaction_mode=InteractionMode.INTERACTIVE)
    exported = {d.name: d.description for d in registry.to_tool_definitions(ctx)}
    assert "browser" in exported
    assert "RUNTIME:" in exported["browser"]
    assert "prefer this tool over web_search" in exported["browser"]
