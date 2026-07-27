from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentos.engine.pipeline import TurnContext
from agentos.engine.steps.skills_filter import filter_skills
from agentos.skills.availability import (
    REASON_FALLBACK_SUPERSEDED,
    REASON_INELIGIBLE,
    REASON_MODEL_INVOCATION_DISABLED,
    REASON_NOT_RETRIEVED,
    REASON_PROMPT_BUDGET,
    REASON_TOOL_GATE,
    SkillAvailability,
    gate_skills,
    plan_injection,
)
from agentos.skills.eligibility import EligibilityContext
from agentos.skills.loader import SkillLoader
from agentos.skills.types import (
    SkillEnvVar,
    SkillInstallSpec,
    SkillLayer,
    SkillPlatformMeta,
    SkillRequires,
    SkillSpec,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "src" / "agentos" / "skills" / "bundled"

# A stand-in install root. Absolute on purpose: this is exactly the shape of
# string that must never reach a detail sentence.
FAKE_BASE = "/opt/example/agentos/skills"


def _skill(
    name: str,
    *,
    layer: SkillLayer = SkillLayer.BUNDLED,
    description: str = "Use when exercising availability.",
    disable_model_invocation: bool = False,
    always: bool = False,
    requires_tools: list[str] | None = None,
    fallback_for_toolsets: list[str] | None = None,
    metadata: SkillPlatformMeta | None = None,
    triggers: list[str] | None = None,
) -> SkillSpec:
    base_dir = f"{FAKE_BASE}/{name}"
    return SkillSpec(
        name=name,
        description=description,
        layer=layer,
        always=always,
        triggers=triggers or [],
        content=f"# {name}",
        path=Path(base_dir),
        base_dir=base_dir,
        file_path=f"{base_dir}/SKILL.md",
        disable_model_invocation=disable_model_invocation,
        requires_tools=requires_tools or [],
        fallback_for_toolsets=fallback_for_toolsets or [],
        metadata=metadata,
    )


def _empty_ctx() -> EligibilityContext:
    """An eligibility context that answers from its caches, never the host."""
    return EligibilityContext(os_name="linux")


# ── reason coverage ─────────────────────────────────────────────────────────


def test_model_invocation_disabled_is_reported_with_a_detail() -> None:
    skill = _skill("hidden", disable_model_invocation=True)

    gated, availability = gate_skills([skill], set(), _empty_ctx())

    assert gated == []
    assert availability["hidden"].offered is False
    assert availability["hidden"].reason == REASON_MODEL_INVOCATION_DISABLED
    assert "disable-model-invocation" in availability["hidden"].detail


def test_ineligible_detail_names_the_missing_binary_and_the_install_command() -> None:
    skill = _skill(
        "mailer",
        metadata=SkillPlatformMeta(
            requires=SkillRequires(bins=["himalaya"]),
            install=[SkillInstallSpec(id="himalaya", kind="brew", bins=["himalaya"])],
        ),
    )
    ctx = EligibilityContext(os_name="linux", has_bin_cache={"himalaya": False})

    _, availability = gate_skills([skill], set(), ctx)

    detail = availability["mailer"].detail
    assert availability["mailer"].reason == REASON_INELIGIBLE
    assert "himalaya" in detail
    assert "not on PATH" in detail
    assert "brew install himalaya" in detail


def test_ineligible_detail_explains_what_a_missing_variable_is_for() -> None:
    skill = _skill(
        "trader",
        metadata=SkillPlatformMeta(
            requires=SkillRequires(
                env=[SkillEnvVar(name="EXAMPLE_API_KEY", description="Example broker API key")]
            )
        ),
    )
    ctx = EligibilityContext(os_name="linux", env_cache={"EXAMPLE_API_KEY": None})

    _, availability = gate_skills([skill], set(), ctx)

    detail = availability["trader"].detail
    assert availability["trader"].reason == REASON_INELIGIBLE
    assert "EXAMPLE_API_KEY" in detail
    assert "Example broker API key" in detail
    assert "not set" in detail


def test_wrong_os_says_which_platform_the_skill_wants() -> None:
    skill = _skill("mac-only", metadata=SkillPlatformMeta(os=["darwin"]))

    _, availability = gate_skills([skill], set(), EligibilityContext(os_name="linux"))

    assert availability["mac-only"].reason == REASON_INELIGIBLE
    assert "darwin" in availability["mac-only"].detail


def test_tool_gate_lists_only_the_tools_this_session_is_missing() -> None:
    skill = _skill("browser", requires_tools=["browser_open", "exec_command"])

    gated, availability = gate_skills([skill], {"exec_command"}, _empty_ctx())

    assert gated == []
    assert availability["browser"].reason == REASON_TOOL_GATE
    assert "browser_open" in availability["browser"].detail
    assert "exec_command" not in availability["browser"].detail


def test_fallback_superseded_names_the_native_tool_that_won() -> None:
    skill = _skill("http-fetch", fallback_for_toolsets=["web_fetch"])

    gated, availability = gate_skills([skill], {"web_fetch"}, _empty_ctx())

    assert gated == []
    assert availability["http-fetch"].reason == REASON_FALLBACK_SUPERSEDED
    assert "web_fetch" in availability["http-fetch"].detail


def test_prompt_budget_is_reported_instead_of_ineligible() -> None:
    skills = [_skill(f"bundled-{i}") for i in range(30)]

    gated, gate_availability = gate_skills(skills, set(), _empty_ctx())
    plan = plan_injection(gated, max_chars=400, injection_mode="system")

    assert plan.dropped
    for name in plan.dropped:
        assert gate_availability[name] == SkillAvailability(offered=True)
        assert plan.availability[name].reason == REASON_PROMPT_BUDGET
        assert "skills section is full (400 characters)" in plan.availability[name].detail
    assert {s.name for s in plan.offered}.isdisjoint(plan.dropped)


def test_every_reason_value_carries_a_non_empty_detail() -> None:
    skills = [
        _skill("hidden", disable_model_invocation=True),
        _skill("mac-only", metadata=SkillPlatformMeta(os=["darwin"])),
        _skill("browser", requires_tools=["browser_open"]),
        _skill("http-fetch", fallback_for_toolsets=["web_fetch"]),
        *(_skill(f"bundled-{i}") for i in range(30)),
    ]

    gated, availability = gate_skills(skills, {"web_fetch"}, _empty_ctx())
    plan = plan_injection(gated, max_chars=400, injection_mode="system")
    availability.update(plan.availability)

    seen = {a.reason for a in availability.values() if not a.offered}
    assert seen == {
        REASON_MODEL_INVOCATION_DISABLED,
        REASON_INELIGIBLE,
        REASON_TOOL_GATE,
        REASON_FALLBACK_SUPERSEDED,
        REASON_PROMPT_BUDGET,
    }
    for name, entry in availability.items():
        if entry.offered:
            assert entry.reason == ""
        else:
            assert entry.detail.strip(), name


def test_no_detail_string_leaks_a_filesystem_path() -> None:
    skills = [
        _skill("hidden", disable_model_invocation=True),
        _skill("mac-only", metadata=SkillPlatformMeta(os=["darwin"])),
        _skill("browser", requires_tools=["browser_open"]),
        _skill("http-fetch", fallback_for_toolsets=["web_fetch"]),
        _skill(
            "mailer",
            metadata=SkillPlatformMeta(
                requires=SkillRequires(bins=["himalaya"]),
                install=[SkillInstallSpec(id="himalaya", kind="brew", bins=["himalaya"])],
            ),
        ),
        *(_skill(f"bundled-{i}") for i in range(30)),
    ]
    ctx = EligibilityContext(os_name="linux", has_bin_cache={"himalaya": False})

    _, availability = gate_skills(skills, {"web_fetch"}, ctx)
    gated, _ = gate_skills(skills, {"web_fetch"}, ctx)
    availability.update(plan_injection(gated, max_chars=400).availability)

    for name, entry in availability.items():
        assert FAKE_BASE not in entry.detail, name
        assert "SKILL.md" not in entry.detail, name
        # No absolute POSIX path and no Windows drive path.
        assert not re.search(r"(?<![\w`])/[\w.]+/", entry.detail), name
        assert not re.search(r"[A-Za-z]:\\\\", entry.detail), name


# ── the property the design rests on ────────────────────────────────────────


def _turn_ctx(loader: SkillLoader, skills_config: object, tools: set[str]) -> TurnContext:
    return TurnContext(
        message="please help with anything",
        session_key="agent:main:webchat:default",
        config=SimpleNamespace(
            tools=SimpleNamespace(profile="standard"),
            skills=skills_config,
        ),
        provider=None,
        model="test-model",
        tool_defs=[SimpleNamespace(name=name) for name in sorted(tools)],
        system_prompt="base",
        metadata={"skill_loader": loader},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("max_chars", [300, 100_000])
async def test_standalone_recomputation_matches_the_engine_offered_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    max_chars: int,
) -> None:
    """The RPC answers before any turn has run, so it must recompute the same set.

    Both budgets are exercised: one that truncates and one that does not.
    """
    import agentos.engine.steps.skills_filter as skills_filter_step

    monkeypatch.setattr(
        skills_filter_step, "_eligibility_context", lambda: EligibilityContext(os_name="linux")
    )
    managed = tmp_path / "managed"
    for i in range(4):
        skill_dir = managed / f"community-skill-{i}"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: community-skill-{i}\n"
            "description: Use when testing installed skills.\n---\n\n# s\n",
            encoding="utf-8",
        )
    loader = SkillLoader(
        bundled_dir=BUNDLED,
        managed_dir=managed,
        snapshot_path=tmp_path / "snapshot.json",
    )
    tools = {"cron", "exec_command", "memory_get", "memory_save", "memory_search", "process"}
    skills_config = SimpleNamespace(
        filter_enabled=False,
        max_skills_prompt_chars=max_chars,
        injection_mode="system",
    )

    ctx = await filter_skills(_turn_ctx(loader, skills_config, tools))

    # Standalone path — no turn, no shared state, same inputs.
    gated, availability = gate_skills(loader.load_all(), tools, EligibilityContext(os_name="linux"))
    plan = plan_injection(gated, max_chars, "system")
    availability.update(plan.availability)

    engine_offered = {
        name for name, entry in ctx.metadata["skill_availability"].items() if entry.offered
    }
    standalone_offered = {name for name, entry in availability.items() if entry.offered}

    assert standalone_offered == engine_offered
    assert standalone_offered == {s.name for s in plan.offered}
    assert plan.prompt == ctx.system_prompt[1]
    assert len(standalone_offered) == ctx.metadata["skill_count"]


# ── engine wiring ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_publishes_a_budget_reason_for_every_dropped_skill(
    tmp_path: Path,
) -> None:
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snapshot.json")
    skills_config = SimpleNamespace(
        filter_enabled=False,
        max_skills_prompt_chars=300,
        injection_mode="system",
    )

    ctx = await filter_skills(_turn_ctx(loader, skills_config, {"exec_command"}))

    availability = ctx.metadata["skill_availability"]
    dropped = ctx.metadata["skills_dropped_for_budget"]
    assert dropped
    for name in dropped:
        assert availability[name].reason == REASON_PROMPT_BUDGET
    offered = {name for name, entry in availability.items() if entry.offered}
    assert offered.isdisjoint(dropped)
    assert len(offered) == ctx.metadata["skill_count"]


@pytest.mark.asyncio
async def test_retrieval_misses_are_reported_as_query_dependent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    for name, description, triggers in (
        ("weather-local", "Fetch weather forecasts.", "[weather, forecast]"),
        ("github-local", "Inspect GitHub pull requests.", "[github, pull request]"),
    ):
        skill_dir = workspace / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\ntriggers: {triggers}\n"
            f"---\n\n# {name}\n",
            encoding="utf-8",
        )
    loader = SkillLoader(workspace_dir=workspace, snapshot_path=tmp_path / "snapshot.json")
    skills_config = SimpleNamespace(
        filter_enabled=True,
        filter_top_k=1,
        filter_strategy="lexical",
        filter_lexical_top_n=20,
        filter_semantic_top_n=20,
        filter_rrf_k=60,
        filter_embedding_model="BAAI/bge-small-zh-v1.5",
        max_skills_prompt_chars=100_000,
        injection_mode="system",
    )
    turn = _turn_ctx(loader, skills_config, {"exec_command"})
    turn.message = "please check the weather forecast"

    ctx = await filter_skills(turn)

    availability = ctx.metadata["skill_availability"]
    assert availability["weather-local"].offered is True
    missed = availability["github-local"]
    assert missed.offered is False
    assert missed.reason == REASON_NOT_RETRIEVED
    # Query-dependent, not a standing property of the skill — say so.
    assert "this message" in missed.detail
    assert "worded" in missed.detail
