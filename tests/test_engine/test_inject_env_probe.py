"""The local-toolchain block: what it says, where it lands, what it never leaks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from agentos.engine import env_probe
from agentos.engine.env_probe import available_tools, render_environment_block
from agentos.engine.steps.inject_env_probe import inject_env_probe


@dataclass
class _MiniContext:
    system_prompt: object
    config: object = None
    metadata: dict = field(default_factory=dict)


def _config(*, env_probe_enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(prompt=SimpleNamespace(env_probe_enabled=env_probe_enabled))


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def test_block_lists_the_supplied_tools() -> None:
    block = render_environment_block(("git", "uv", "rg"))

    assert "Local Toolchain" in block
    assert "git, uv, rg" in block


def test_no_tools_renders_nothing_rather_than_an_empty_heading() -> None:
    assert render_environment_block(()) == ""


def test_a_very_long_tool_list_is_clipped() -> None:
    block = render_environment_block(tuple(f"tool{i}" for i in range(200)))

    assert len(block) < 700
    assert "…" in block


def test_rendered_block_never_contains_a_filesystem_path() -> None:
    # shutil.which answers with an absolute path that usually contains the
    # operator's home directory. Only names may reach the prompt.
    block = render_environment_block()

    assert "/" not in block.split("Present on PATH:")[-1].split(".\n")[0]
    assert "\\" not in block


def test_probe_returns_bare_names_only() -> None:
    for name in available_tools():
        assert re.fullmatch(r"[a-z0-9_.+-]+", name), name


# ---------------------------------------------------------------------------
# placement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_block_lands_in_the_cacheable_base_not_the_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        env_probe,
        "render_environment_block",
        lambda *_a, **_k: "## Local Toolchain\n\nPresent on PATH: git.",
    )
    ctx = _MiniContext(system_prompt=("BASE", "SUFFIX"), config=_config())

    out = await inject_env_probe(ctx)

    base, suffix = out.system_prompt
    # The probe is constant for the process, so it belongs where it is paid
    # for once rather than on every turn.
    assert "Local Toolchain" in base
    assert suffix == "SUFFIX"


@pytest.mark.asyncio
async def test_a_plain_string_prompt_keeps_an_empty_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(env_probe, "render_environment_block", lambda *_a, **_k: "BLOCK")
    ctx = _MiniContext(system_prompt="BASE", config=_config())

    out = await inject_env_probe(ctx)

    assert out.system_prompt == ("BASE\n\nBLOCK", "")
    assert out.metadata["inject_env_probe__applied"] is True


@pytest.mark.asyncio
async def test_disabled_by_config_is_a_noop() -> None:
    ctx = _MiniContext(system_prompt="BASE", config=_config(env_probe_enabled=False))

    out = await inject_env_probe(ctx)

    assert out.system_prompt == "BASE"
    assert out.metadata["inject_env_probe__applied"] is False


@pytest.mark.asyncio
async def test_an_empty_probe_leaves_the_prompt_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(env_probe, "render_environment_block", lambda *_a, **_k: "")
    ctx = _MiniContext(system_prompt=("BASE", "SUFFIX"), config=_config())

    out = await inject_env_probe(ctx)

    assert out.system_prompt == ("BASE", "SUFFIX")
    assert out.metadata["inject_env_probe__applied"] is False


@pytest.mark.asyncio
async def test_missing_config_still_injects() -> None:
    # A caller that never set prompt config should get the default behaviour,
    # not a crash.
    ctx = _MiniContext(system_prompt="BASE", config=None)

    out = await inject_env_probe(ctx)

    assert isinstance(out.system_prompt, tuple)
