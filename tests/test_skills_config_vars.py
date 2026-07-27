"""Tests for skill-declared settings (skills.config.*).

The distinction being enforced: credentials go to .env, ordinary settings go
to the TOML config. This file covers the second half — declaring a setting,
resolving what is in effect, and handing it to the agent when it opens the
skill.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agentos.gateway.config import GatewayConfig
from agentos.skills.config_vars import (
    discover_skill_config_vars,
    missing_skill_config_vars,
    render_skill_config_block,
    resolve_skill_config_values,
)
from agentos.skills.loader import SkillLoader
from agentos.skills.types import SkillConfigVar, SkillPlatformMeta


def _write_skill(root: Path, name: str, config_block: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: Test skill {name}\n"
        "metadata:\n"
        "  agentos:\n"
        f"{config_block}"
        "---\n"
        "body text\n",
        encoding="utf-8",
    )


@pytest.fixture
def wiki_loader(tmp_path: Path) -> SkillLoader:
    skills = tmp_path / "skills"
    skills.mkdir()
    _write_skill(
        skills,
        "wiki",
        "    config:\n"
        "      - key: wiki.path\n"
        "        description: Path to the knowledge base directory\n"
        '        default: "~/wiki"\n'
        "      - key: wiki.format\n"
        "        description: Output format\n",
    )
    return SkillLoader(bundled_dir=skills, snapshot_path=tmp_path / "snapshot.json")


class TestDeclaration:
    def test_manifest_declarations_load(self, wiki_loader: SkillLoader) -> None:
        skill = next(s for s in wiki_loader.load_all() if s.name == "wiki")
        assert skill.metadata is not None
        keys = [c.key for c in skill.metadata.config_vars]
        assert keys == ["wiki.path", "wiki.format"]
        assert skill.metadata.config_vars[0].default == "~/wiki"

    def test_entries_without_a_key_or_description_are_skipped(self) -> None:
        meta = SkillPlatformMeta(
            config_vars=[  # type: ignore[list-item]
                {"key": "good", "description": "d"},
                {"key": "", "description": "d"},
                {"key": "no-desc"},
                "not-a-mapping",
                None,
            ]
        )
        assert [c.key for c in meta.config_vars] == ["good"]

    def test_prompt_falls_back_to_the_description(self) -> None:
        entry = SkillConfigVar.coerce({"key": "k", "description": "Explain this"})
        assert entry is not None and entry.prompt == "Explain this"

    def test_round_trips_through_the_cache_dict_form(self) -> None:
        original = SkillConfigVar(key="k", description="d", default=3, prompt="p")
        meta = SkillPlatformMeta(config_vars=[original.to_dict()])  # type: ignore[list-item]
        assert meta.config_vars[0] == original

    def test_snapshot_reload_keeps_declarations(self, tmp_path: Path) -> None:
        # A cache hit must not quietly strip settings the manifest declared.
        skills = tmp_path / "skills"
        skills.mkdir()
        _write_skill(
            skills,
            "wiki",
            "    config:\n      - key: wiki.path\n        description: Where the wiki lives\n",
        )
        snapshot = tmp_path / "snapshot.json"
        SkillLoader(bundled_dir=skills, snapshot_path=snapshot).load_all()
        SkillLoader(bundled_dir=skills, snapshot_path=snapshot).save_snapshot()

        reloaded = SkillLoader(bundled_dir=skills, snapshot_path=snapshot)
        restored = reloaded.load_snapshot()
        assert restored is not None
        skill = next(s for s in restored if s.name == "wiki")
        assert skill.metadata is not None
        assert [c.key for c in skill.metadata.config_vars] == ["wiki.path"]


class TestDiscovery:
    def test_lists_declarations_with_their_owning_skill(self, wiki_loader: SkillLoader) -> None:
        found = discover_skill_config_vars(wiki_loader)
        assert [(name, var.key) for name, var in found] == [
            ("wiki", "wiki.path"),
            ("wiki", "wiki.format"),
        ]

    def test_duplicate_keys_collapse(self, tmp_path: Path) -> None:
        # Two skills naming one key want the same setting; prompting twice for
        # one value is worse than picking one description.
        skills = tmp_path / "skills"
        skills.mkdir()
        for name in ("alpha", "beta"):
            _write_skill(
                skills,
                name,
                "    config:\n      - key: shared.key\n        description: Shared setting\n",
            )
        loader = SkillLoader(bundled_dir=skills, snapshot_path=tmp_path / "snap.json")
        assert len(discover_skill_config_vars(loader)) == 1

    def test_a_broken_loader_degrades_quietly(self) -> None:
        class ExplodingLoader:
            def load_all(self) -> list[object]:
                raise RuntimeError("unreadable skills dir")

        assert discover_skill_config_vars(ExplodingLoader()) == []  # type: ignore[arg-type]

    def test_no_loader_is_not_an_error(self) -> None:
        assert discover_skill_config_vars(None) == []


class TestResolution:
    def test_configured_value_wins_over_the_default(self) -> None:
        config = GatewayConfig(skills={"config": {"wiki": {"path": "/srv/wiki"}}})
        declared = SkillConfigVar(key="wiki.path", description="d", default="~/wiki")
        assert resolve_skill_config_values([declared], config) == {"wiki.path": "/srv/wiki"}

    def test_default_applies_when_nothing_is_configured(self) -> None:
        config = GatewayConfig()
        declared = SkillConfigVar(key="wiki.format", description="d", default="markdown")
        assert resolve_skill_config_values([declared], config) == {"wiki.format": "markdown"}

    def test_blank_configured_value_falls_back_to_the_default(self) -> None:
        config = GatewayConfig(skills={"config": {"wiki": {"format": "   "}}})
        declared = SkillConfigVar(key="wiki.format", description="d", default="markdown")
        assert resolve_skill_config_values([declared], config) == {"wiki.format": "markdown"}

    def test_home_relative_paths_are_expanded(self) -> None:
        # An unexpanded "~/wiki" is a directory literally named "~".
        config = GatewayConfig()
        declared = SkillConfigVar(key="wiki.path", description="d", default="~/wiki")
        resolved = resolve_skill_config_values([declared], config)["wiki.path"]
        assert not str(resolved).startswith("~")

    def test_unset_and_undefaulted_resolves_to_none(self) -> None:
        config = GatewayConfig()
        declared = SkillConfigVar(key="wiki.format", description="d")
        assert resolve_skill_config_values([declared], config) == {"wiki.format": None}


class TestMissing:
    def test_a_declaration_with_a_default_is_not_missing(self, wiki_loader: SkillLoader) -> None:
        missing = missing_skill_config_vars(wiki_loader, GatewayConfig())
        keys = [entry["key"] for entry in missing]
        assert "wiki.path" not in keys  # has a default, works out of the box
        assert "wiki.format" in keys

    def test_configured_values_are_not_reported(self, wiki_loader: SkillLoader) -> None:
        config = GatewayConfig(skills={"config": {"wiki": {"format": "markdown"}}})
        assert missing_skill_config_vars(wiki_loader, config) == []


class TestRenderedBlock:
    def test_block_lists_the_values_in_effect(self) -> None:
        skill = SimpleNamespace(
            metadata=SkillPlatformMeta(
                config_vars=[  # type: ignore[list-item]
                    {"key": "wiki.path", "description": "d", "default": "/srv/wiki"},
                ]
            )
        )
        block = render_skill_config_block(skill, GatewayConfig(), config_path="/tmp/agentos.toml")
        assert "[Skill config (from /tmp/agentos.toml):" in block
        assert "wiki.path = /srv/wiki" in block

    def test_unset_values_are_shown_as_such_rather_than_blank(self) -> None:
        skill = SimpleNamespace(
            metadata=SkillPlatformMeta(
                config_vars=[{"key": "wiki.format", "description": "d"}]  # type: ignore[list-item]
            )
        )
        assert "(not set)" in render_skill_config_block(skill, GatewayConfig())

    def test_a_skill_declaring_nothing_costs_nothing(self) -> None:
        skill = SimpleNamespace(metadata=SkillPlatformMeta())
        assert render_skill_config_block(skill, GatewayConfig()) == ""

    def test_a_skill_without_metadata_is_handled(self) -> None:
        assert render_skill_config_block(SimpleNamespace(metadata=None), GatewayConfig()) == ""


class TestConfigModel:
    def test_arbitrary_skill_keys_are_accepted(self) -> None:
        # The keys belong to the skills, so this section cannot be a fixed
        # schema without AgentOS knowing every skill anyone might install.
        config = GatewayConfig(skills={"config": {"anything": {"nested": {"deep": 1}}}})
        assert config.skills.config["anything"]["nested"]["deep"] == 1

    def test_defaults_to_empty(self) -> None:
        assert GatewayConfig().skills.config == {}


class TestUpgradeSafety:
    def test_an_install_using_no_skill_config_writes_no_new_section(self) -> None:
        """Upgrading must not change a config file that does not use the feature.

        Every nested config model forbids unknown keys, so an empty
        ``[skills.config]`` written on upgrade would be rejected by any older
        AgentOS the operator rolls back to — for a feature they never used.
        """
        written = GatewayConfig().to_toml_dict()
        assert "config" not in (written.get("skills") or {})

    def test_a_configured_value_is_still_written(self) -> None:
        config = GatewayConfig(skills={"config": {"wiki": {"path": "/srv/wiki"}}})
        written = config.to_toml_dict()
        assert written["skills"]["config"] == {"wiki": {"path": "/srv/wiki"}}

    def test_round_trips_through_the_toml_form(self) -> None:
        config = GatewayConfig(skills={"config": {"wiki": {"path": "/srv/wiki"}}})
        restored = GatewayConfig(**config.to_toml_dict())
        assert restored.skills.config == {"wiki": {"path": "/srv/wiki"}}
