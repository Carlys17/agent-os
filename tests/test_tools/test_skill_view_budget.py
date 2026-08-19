from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentos.skills.loader import SkillLoader
from agentos.skills.outline import DEFAULT_MAX_SKILL_VIEW_CHARS
from agentos.tools.builtin import control as control_module
from agentos.tools.builtin import skill_tools as skill_tools_module
from agentos.tools.registry import get_default_registry


async def _skill_view(name: str, **kwargs: object) -> str:
    registered = get_default_registry().get("skill_view")
    assert registered is not None
    return await registered.handler(name=name, **kwargs)


def _body(result: str) -> str:
    """Drop the leading ``[Skill directory: ...]`` line.

    Every view opens with it so the model knows where the skill's scripts live;
    what this file asserts on is what comes after. See
    ``test_skill_view_base_dir.py`` for the line itself.
    """
    marker = "]\n\n"
    if result.startswith("[Skill directory: ") and marker in result:
        return result.split(marker, 1)[1]
    return result


def _long_skill(dir_: Path, name: str, *, sections: int, section_chars: int) -> str:
    """A skill shaped like the ones that motivated the ceiling: one '# Title'
    owning the body, then several '##' sections."""
    body = [f"# {name.title()}", "", "One-line overview of what this does.", ""]
    for index in range(sections):
        body += [f"## Section {index}", "", "w" * section_chars, ""]
    text = "\n".join(body)
    skill_dir = dir_ / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when testing the view budget.\n---\n{text}",
        encoding="utf-8",
    )
    return text


@pytest.fixture()
def loaded(tmp_path: Path) -> Iterator[SkillLoader]:
    bundled = tmp_path / "bundled"
    _long_skill(bundled, "big-skill", sections=12, section_chars=3_000)
    _long_skill(bundled, "small-skill", sections=2, section_chars=200)

    # Barely over the ceiling, with many small sections: the shape three real
    # skills have (11.4k / 40 sections, 10.4k / 14, 10.3k / 18).
    _long_skill(bundled, "narrow-skill", sections=40, section_chars=240)

    prose = bundled / "prose-skill"
    prose.mkdir(parents=True)
    (prose / "SKILL.md").write_text(
        "---\nname: prose-skill\ndescription: Use when testing headingless bodies.\n---\n"
        + ("no headings here at all. " * 1_000),
        encoding="utf-8",
    )

    refs = bundled / "big-skill" / "references"
    refs.mkdir()
    (refs / "api.md").write_text("reference body\n", encoding="utf-8")

    loader = SkillLoader(
        bundled_dir=bundled,
        workspace_dir=tmp_path / "workspace",
        managed_dir=tmp_path / "managed",
        personal_agents_dir=tmp_path / "personal",
        project_agents_dir=tmp_path / "project",
        snapshot_path=tmp_path / "skills.snapshot.json",
    )
    previous_loader = skill_tools_module._loader
    previous_config = control_module._gateway_config
    skill_tools_module.create_skill_tools(loader)
    try:
        yield loader
    finally:
        skill_tools_module._loader = previous_loader
        control_module._gateway_config = previous_config


def _set_budget(value: int | None) -> None:
    if value is None:
        control_module._gateway_config = None
        return
    control_module._gateway_config = SimpleNamespace(
        skills=SimpleNamespace(max_skill_view_chars=value)
    )


@pytest.mark.asyncio
async def test_a_small_skill_comes_back_whole(loaded: SkillLoader) -> None:
    """The shipped set is small — median 2.4k characters — and must be untouched."""
    _set_budget(None)
    raw = loaded.get_by_name("small-skill").content

    result = await _skill_view("small-skill")

    assert _body(result).startswith(raw)
    assert "indexed below" not in result


@pytest.mark.asyncio
async def test_a_large_skill_returns_its_opening_plus_an_index(loaded: SkillLoader) -> None:
    """A 56k hub skill cost ~14k tokens per read, and again on every re-read."""
    _set_budget(None)
    raw = loaded.get_by_name("big-skill").content

    result = await _skill_view("big-skill")

    assert len(result) < len(raw) / 2
    # The opening is real content, not just an index.
    assert "One-line overview" in result
    assert "Section 0" in result
    assert "Sections:" in result
    assert 'skill_view(name="big-skill", section="<title>")' in result
    # Supporting files are named, never inlined — and named with forward
    # slashes on every platform, because the model quotes these back as
    # file_path, where a backslash is a JSON escape.
    assert "references/api.md" in result
    assert "references\\api.md" not in result
    assert "reference body" not in result


@pytest.mark.asyncio
async def test_a_named_section_comes_back_whole(loaded: SkillLoader) -> None:
    _set_budget(None)

    result = await _skill_view("big-skill", section="Section 7")

    assert _body(result).startswith("## Section 7")
    assert "Section 8" not in result


@pytest.mark.asyncio
async def test_an_unknown_section_names_the_ones_that_exist(loaded: SkillLoader) -> None:
    _set_budget(None)

    result = await _skill_view("big-skill", section="nowhere")

    assert "No section 'nowhere'" in result
    assert "Section 3" in result


@pytest.mark.asyncio
async def test_a_body_that_would_grow_is_returned_whole(loaded: SkillLoader) -> None:
    """Just over the ceiling, the index costs more than it saves.

    The head is nearly the whole body and the index is pure addition, so
    outlining would hand back *more* than the skill.
    """
    _set_budget(None)
    raw = loaded.get_by_name("narrow-skill").content
    assert len(raw) > DEFAULT_MAX_SKILL_VIEW_CHARS

    result = await _skill_view("narrow-skill")

    assert _body(result).startswith(raw)
    assert "Sections:" not in result


@pytest.mark.asyncio
async def test_a_body_with_no_headings_is_never_cut(loaded: SkillLoader) -> None:
    """Nothing to index means no way back to the rest, and a body cut off with
    no next step is worse than an expensive one."""
    _set_budget(None)
    raw = loaded.get_by_name("prose-skill").content
    assert len(raw) > DEFAULT_MAX_SKILL_VIEW_CHARS

    result = await _skill_view("prose-skill")

    assert _body(result).startswith(raw)


@pytest.mark.asyncio
async def test_the_ceiling_can_be_switched_off(loaded: SkillLoader) -> None:
    _set_budget(0)
    raw = loaded.get_by_name("big-skill").content

    result = await _skill_view("big-skill")

    assert _body(result).startswith(raw)


@pytest.mark.asyncio
async def test_a_missing_config_still_applies_the_ceiling(loaded: SkillLoader) -> None:
    """A boot-ordering detail must not silently restore whole-body reads."""
    control_module._gateway_config = None

    result = await _skill_view("big-skill")

    assert "Sections:" in result


@pytest.mark.asyncio
async def test_a_missing_skill_is_pointed_at_the_hub_that_may_carry_it(
    loaded: SkillLoader,
) -> None:
    """A skill named in the catalog but not installed is not a failure.

    The old text offered no next step beyond "tell the user", so a model asked
    for a hub skill reported the lookup as broken — the issue behind this said
    `skill_view` "returned error: 14", a code that exists nowhere in AgentOS.
    """
    _set_budget(None)

    result = await _skill_view("capminal")

    assert "Skill not found: capminal" in result
    assert 'skill_search_community(query="capminal")' in result
    # Installing touches the machine, so it is offered, never assumed.
    assert "ask the user before" in result
    assert "Do not report this as a tool error" in result


@pytest.mark.asyncio
async def test_a_near_miss_names_the_installed_skill_it_probably_meant(
    loaded: SkillLoader,
) -> None:
    _set_budget(None)

    result = await _skill_view("big-skil")

    assert "`big-skill`" in result


@pytest.mark.asyncio
async def test_the_hub_is_not_suggested_to_a_session_that_cannot_reach_it(
    loaded: SkillLoader,
) -> None:
    """Cron runs under an allowlist that carries neither hub tool."""
    from agentos.tools.types import CRON_AGENT_ALLOW, CallerKind, ToolContext, current_tool_context

    _set_budget(None)
    token = current_tool_context.set(
        ToolContext(caller_kind=CallerKind.CRON, allowed_tools=set(CRON_AGENT_ALLOW))
    )
    try:
        result = await _skill_view("capminal")
    finally:
        current_tool_context.reset(token)

    assert "skill_search_community" not in result
    assert "skill_install_community" not in result
    assert "skill_list" in result


def _pinned_skill(dir_: Path, name: str) -> None:
    """A skill whose rule sits at the very end, past any budget cut.

    The shape that motivated pinning: `senior-unilp-manager` grew to 44k
    characters, and two merged fixes wrote their rules into the last quarter of
    it, where a 10k budget never reached. Both were silently ignored.
    """
    body = ["# Big", "", "Overview line.", ""]
    for index in range(12):
        body += [f"## Section {index}", "", "w" * 3_000, ""]
    body += [
        "<!-- always -->",
        "## Rules",
        "",
        "Put every file under its own directory.",
        "",
    ]
    skill_dir = dir_ / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when testing pinned sections.\n---\n"
        + "\n".join(body),
        encoding="utf-8",
    )


@pytest.fixture()
def pinned(tmp_path: Path) -> Iterator[SkillLoader]:
    bundled = tmp_path / "bundled"
    _pinned_skill(bundled, "pinned-skill")
    _long_skill(bundled, "unpinned-skill", sections=12, section_chars=3_000)

    loader = SkillLoader(
        bundled_dir=bundled,
        workspace_dir=tmp_path / "workspace",
        managed_dir=tmp_path / "managed",
        personal_agents_dir=tmp_path / "personal",
        project_agents_dir=tmp_path / "project",
        snapshot_path=tmp_path / "skills.snapshot.json",
    )
    previous_loader = skill_tools_module._loader
    previous_config = control_module._gateway_config
    skill_tools_module.create_skill_tools(loader)
    try:
        yield loader
    finally:
        skill_tools_module._loader = previous_loader
        control_module._gateway_config = previous_config


@pytest.mark.asyncio
async def test_a_pinned_section_survives_the_cut(pinned: SkillLoader) -> None:
    _set_budget(None)

    result = await _skill_view("pinned-skill")

    assert "Put every file under its own directory." in result
    # And the index does not send the model back for what it just received.
    rules_line = next(
        line for line in result.splitlines() if line.strip().startswith("- ") and "Rules" in line
    )
    assert rules_line.endswith("(shown above)")


@pytest.mark.asyncio
async def test_pinning_does_not_push_the_view_past_its_ceiling(pinned: SkillLoader) -> None:
    """The head gives up room for the rule; the total does not grow."""
    _set_budget(None)
    unpinned = await _skill_view("unpinned-skill")

    result = await _skill_view("pinned-skill")

    # Only the sentence introducing the pinned block is new: the rule's own
    # characters came out of the head's allowance, not out of thin air.
    assert len(_body(result)) <= len(_body(unpinned)) + 400
    assert "Overview line." in result  # the head is still real content
