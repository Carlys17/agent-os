"""A hub install must not silently replace a skill that ships with AgentOS.

Managed outranks bundled, so a same-named catalog row takes over every session
while the shipped files sit untouched on disk. Nothing in the old flow said so,
and the way an agent reaches that state is ordinary: a bundled skill declaring
`requires` is dropped from the prompt until it is configured, so "install X"
for an X that is already here reads as "X is missing" and sends it shopping.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from agentos.skills.hub import installer as installer_module
from agentos.skills.hub.installer import SkillInstaller
from agentos.skills.hub.source import SkillBundle, SkillMeta
from agentos.skills.loader import SkillLoader
from agentos.tools.builtin import skill_tools as skill_tools_module

BUNDLED_NAME = "shipped-skill"


class FakeRouter:
    def __init__(self, bundle: SkillBundle | None) -> None:
        self.bundle = bundle
        self.searched: list[str] = []

    async def fetch(self, identifier: str, source_id: str) -> SkillBundle | None:
        return self.bundle

    async def inspect(self, identifier: str, source_id: str) -> SkillMeta | None:
        return self.bundle.meta if self.bundle is not None else None

    async def search(
        self, query: str, limit: int = 10, source_id: str | None = None
    ) -> list[SkillMeta]:
        self.searched.append(query)
        return [SkillMeta(name=query, description="A catalog row", identifier=query)]


def _write_skill(root: Path, name: str, *, requires: str = "") -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    block = ""
    if requires:
        block = "metadata:\n  agentos:\n" + requires
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when testing skills.\n{block}---\n\n# {name}\n",
        encoding="utf-8",
    )


def _installer(tmp_path: Path, bundle_name: str) -> SkillInstaller:
    return SkillInstaller(
        router=FakeRouter(
            SkillBundle(
                name=bundle_name,
                files={
                    "SKILL.md": (
                        f"---\nname: {bundle_name}\ndescription: From the hub.\n---\n\n# Hub\n"
                    )
                },
            )
        ),
        managed_dir=tmp_path / "managed",
        quarantine_dir=tmp_path / "quarantine",
        lockfile_path=tmp_path / "lock.json",
    )


@pytest.fixture
def bundled_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in bundled tree, so the guard is tested against known names."""
    root = tmp_path / "bundled"
    _write_skill(root, BUNDLED_NAME)
    monkeypatch.setattr(installer_module, "default_bundled_skills_dir", lambda: root)
    return root


@pytest.mark.asyncio
async def test_install_refuses_to_shadow_a_bundled_skill(tmp_path: Path, bundled_dir: Path) -> None:
    result = await _installer(tmp_path, BUNDLED_NAME).install(BUNDLED_NAME, "clawhub")

    assert result.success is False
    assert not (tmp_path / "managed" / BUNDLED_NAME).exists()
    # The message has to say what to do instead, or the agent reports a dead end.
    assert "already ships with AgentOS" in result.message
    assert "agentos skills list" in result.message
    assert "force" in result.message


@pytest.mark.asyncio
async def test_force_installs_over_a_bundled_skill(tmp_path: Path, bundled_dir: Path) -> None:
    result = await _installer(tmp_path, BUNDLED_NAME).install(BUNDLED_NAME, "clawhub", force=True)

    assert result.success is True
    assert (tmp_path / "managed" / BUNDLED_NAME / "SKILL.md").is_file()


@pytest.mark.asyncio
async def test_reinstall_of_an_existing_shadow_is_not_a_new_decision(
    tmp_path: Path, bundled_dir: Path
) -> None:
    """`agentos skills update` must not start failing once a shadow exists."""
    _write_skill(tmp_path / "managed", BUNDLED_NAME)

    result = await _installer(tmp_path, BUNDLED_NAME).install(BUNDLED_NAME, "clawhub")

    assert result.success is True


@pytest.mark.asyncio
async def test_a_name_that_is_not_bundled_installs_normally(
    tmp_path: Path, bundled_dir: Path
) -> None:
    result = await _installer(tmp_path, "community-only").install("community-only", "clawhub")

    assert result.success is True
    assert (tmp_path / "managed" / "community-only" / "SKILL.md").is_file()


# ── skill_search_community answers with the local truth first ────────────────


async def _search(query: str) -> dict[str, Any]:
    from agentos.tools.registry import get_default_registry

    registered = get_default_registry().get("skill_search_community")
    assert registered is not None
    return json.loads(await registered.handler(query=query))


@pytest.fixture
def searchable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SkillLoader]:
    bundled = tmp_path / "bundled"
    _write_skill(
        bundled,
        "needs-setup",
        requires=(
            "    requires:\n"
            "      bins: [definitely-not-a-real-binary]\n"
            "      env:\n"
            "        - name: DEMO_SKILL_TOKEN\n"
            "          description: Token for the demo service.\n"
            "          url: https://example.com/keys\n"
        ),
    )
    _write_skill(bundled, "ready-skill")
    monkeypatch.delenv("DEMO_SKILL_TOKEN", raising=False)

    loader = SkillLoader(bundled_dir=bundled, snapshot_path=tmp_path / "snapshot.json")
    monkeypatch.setattr(skill_tools_module, "get_default_skill_router", lambda: FakeRouter(None))
    # create_skill_tools sets a module-level loader; tests run in random order,
    # so put back whatever the process had.
    previous_loader = skill_tools_module._loader
    skill_tools_module.create_skill_tools(loader)
    try:
        yield loader
    finally:
        skill_tools_module._loader = previous_loader


@pytest.mark.asyncio
async def test_search_reports_an_unconfigured_bundled_skill_as_installed(
    searchable: SkillLoader,
) -> None:
    payload = await _search("needs-setup")

    match = payload["installed_match"]
    assert match["name"] == "needs-setup"
    assert match["eligible"] is False
    assert "definitely-not-a-real-binary (binary)" in match["missing"]
    assert "DEMO_SKILL_TOKEN (env var)" in match["missing"]
    assert match["needs_env"][0]["url"] == "https://example.com/keys"
    assert "already installed" in match["note"]
    # Browsing is not withheld — the local answer just comes first.
    assert "results" in payload
    assert list(payload).index("installed_match") < list(payload).index("results")


@pytest.mark.asyncio
async def test_search_still_reports_a_ready_skill_as_installed(
    searchable: SkillLoader,
) -> None:
    payload = await _search("ready-skill")

    assert payload["installed_match"]["eligible"] is True


@pytest.mark.asyncio
async def test_search_for_a_partial_name_points_at_what_is_installed(
    searchable: SkillLoader,
) -> None:
    """A near miss still has to reach the agent — 'gmgn' must find 'gmgn-token'."""
    payload = await _search("needs")

    assert payload["installed_match"] == {"similar_installed": ["needs-setup"]}


@pytest.mark.asyncio
async def test_search_for_an_unknown_name_carries_no_local_match(
    searchable: SkillLoader,
) -> None:
    payload = await _search("nothing-like-this")

    assert "installed_match" not in payload
