from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agentos.engine.pipeline import TurnContext
from agentos.engine.steps.skills_filter import filter_skills
from agentos.gateway.config import GatewayConfig
from agentos.skills.injector import SkillInjector
from agentos.skills.loader import SkillLoader
from agentos.skills.types import SkillLayer, SkillSpec

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "src" / "agentos" / "skills" / "bundled"


def _skill(
    name: str,
    *,
    layer: SkillLayer = SkillLayer.BUNDLED,
    description: str = "Use when exercising the injector.",
    disable_model_invocation: bool = False,
) -> SkillSpec:
    """A spec carrying the on-disk fields the injector used to leak."""
    base_dir = f"/opt/example/agentos/skills/{name}"
    return SkillSpec(
        name=name,
        description=description,
        layer=layer,
        always=False,
        triggers=[],
        content=f"# {name}",
        path=Path(base_dir),
        base_dir=base_dir,
        file_path=f"{base_dir}/SKILL.md",
        disable_model_invocation=disable_model_invocation,
    )


def test_neither_mode_emits_a_skill_location() -> None:
    skills = [_skill("alpha"), _skill("beta")]
    injector = SkillInjector()

    full = injector.inject_full("", skills)
    compact = injector.inject_compact("", skills)

    for prompt in (full, compact):
        assert "<location>" not in prompt
        assert "SKILL.md" not in prompt
        assert "/opt/example" not in prompt


def test_full_mode_is_used_when_it_fits_the_budget() -> None:
    skills = [_skill("alpha", description="Use when alpha things happen.")]

    prompt, dropped = SkillInjector().inject_skills("", skills, max_chars=10_000)

    assert "<description>Use when alpha things happen.</description>" in prompt
    assert "<name>alpha</name>" in prompt
    assert dropped == []


def test_compact_mode_takes_over_when_descriptions_do_not_fit() -> None:
    skills = [_skill(f"skill-{i}", description="d" * 400) for i in range(10)]

    prompt, dropped = SkillInjector().inject_skills("", skills, max_chars=1_000)

    assert "<description>" not in prompt
    for i in range(10):
        assert f"<name>skill-{i}</name>" in prompt
    assert dropped == []


def test_truncation_sacrifices_the_lowest_precedence_layers_first() -> None:
    keep = [
        _skill("workspace-0", layer=SkillLayer.WORKSPACE),
        *(_skill(f"managed-{i}", layer=SkillLayer.MANAGED) for i in range(3)),
    ]
    skills = [*(_skill(f"bundled-{i}") for i in range(20)), *keep]
    injector = SkillInjector()
    # Budget derived from a real render, not a magic number: the block's guidance
    # text is prose and does change, and a hardcoded budget silently turns this
    # into a different test (or a passing one that proves less) when it does.
    budget = len(injector.inject_compact("", keep))

    prompt, dropped = injector.inject_skills("", skills, max_chars=budget)

    for spec in keep:
        assert f"<name>{spec.name}</name>" in prompt
    assert dropped
    assert all(name.startswith("bundled-") for name in dropped)


def test_dropped_names_match_what_is_missing_from_the_prompt() -> None:
    skills = [
        *(_skill(f"bundled-{i}") for i in range(30)),
        *(_skill(f"managed-{i}", layer=SkillLayer.MANAGED) for i in range(5)),
    ]

    prompt, dropped = SkillInjector().inject_skills("", skills, max_chars=700)

    missing = {s.name for s in skills if f"<name>{s.name}</name>" not in prompt}
    # Without this the assertion below passes vacuously (empty == empty) the day
    # a wider budget stops truncation firing at all.
    assert dropped
    assert set(dropped) == missing
    assert len(dropped) == len(set(dropped))


def test_truncation_preserves_within_layer_order() -> None:
    skills = [_skill(f"bundled-{i:02d}") for i in range(30)]

    prompt, dropped = SkillInjector().inject_skills("", skills, max_chars=500)

    kept = [s.name for s in skills if f"<name>{s.name}</name>" in prompt]
    assert kept == sorted(kept)
    assert dropped == [s.name for s in skills if s.name not in kept]


def test_model_invisible_skills_are_never_reported_as_dropped() -> None:
    skills = [
        _skill("hidden", disable_model_invocation=True),
        *(_skill(f"bundled-{i}") for i in range(20)),
    ]

    prompt, dropped = SkillInjector().inject_skills("", skills, max_chars=400)

    assert "<name>hidden</name>" not in prompt
    assert "hidden" not in dropped


def test_a_tiny_budget_still_keeps_one_skill_and_the_guard() -> None:
    skills = [_skill(f"bundled-{i}") for i in range(5)]

    prompt, dropped = SkillInjector().inject_skills("", skills, max_chars=1)

    assert "they are not callable tools" in prompt
    assert prompt.count("<name>") == 1
    assert len(dropped) == 4


def _ctx(loader: SkillLoader, skills_config: object) -> TurnContext:
    tool_defs = [
        SimpleNamespace(name=name)
        for name in (
            "background_process",
            "cron",
            "exec_command",
            "memory_get",
            "memory_save",
            "memory_search",
            "process",
        )
    ]
    return TurnContext(
        message="please help with anything",
        session_key="agent:main:webchat:default",
        config=SimpleNamespace(
            tools=SimpleNamespace(profile="standard"),
            skills=skills_config,
        ),
        provider=None,
        model="test-model",
        tool_defs=tool_defs,
        system_prompt="base",
        metadata={"skill_loader": loader},
    )


@pytest.mark.asyncio
async def test_shipped_default_budget_keeps_every_managed_skill(tmp_path: Path) -> None:
    """The shipped default must fit the bundled set plus installed skills.

    The old 8000-char default could not hold the bundled set even in compact
    mode, and truncation kept a bundled-first prefix — so the skills an
    operator installed were the first thing dropped, silently.
    """
    managed = tmp_path / "managed"
    installed = [f"community-skill-{i}" for i in range(6)]
    for name in installed:
        skill_dir = managed / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\n"
            "description: Use when testing installed skills.\n"
            f"---\n\n# {name}\n",
            encoding="utf-8",
        )
    loader = SkillLoader(
        bundled_dir=BUNDLED,
        managed_dir=managed,
        snapshot_path=tmp_path / "snapshot.json",
    )

    ctx = await filter_skills(_ctx(loader, GatewayConfig().skills))

    prompt = ctx.system_prompt[1]
    for name in installed:
        assert f"<name>{name}</name>" in prompt
    assert ctx.metadata["skills_dropped_for_budget"] == []
    # Descriptions are the whole point of the budget: without them the model
    # cannot tell which skill matches the request.
    assert "<description>" in prompt


@pytest.mark.asyncio
async def test_budget_truncation_is_reported_in_metadata(tmp_path: Path) -> None:
    managed = tmp_path / "managed"
    skill_dir = managed / "community-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: community-skill\ndescription: Use when testing installed skills.\n---\n\n# c\n",
        encoding="utf-8",
    )
    loader = SkillLoader(
        bundled_dir=BUNDLED,
        managed_dir=managed,
        snapshot_path=tmp_path / "snapshot.json",
    )
    skills_config = SimpleNamespace(
        filter_enabled=False,
        max_skills_prompt_chars=300,
        injection_mode="system",
    )

    ctx = await filter_skills(_ctx(loader, skills_config))

    prompt = ctx.system_prompt[1]
    dropped = ctx.metadata["skills_dropped_for_budget"]
    assert dropped
    assert "community-skill" not in dropped
    assert "<name>community-skill</name>" in prompt
    assert ctx.metadata["skill_count"] == prompt.count("<name>")
    assert all(name not in ctx.metadata["filtered_skill_ids"] for name in dropped)
