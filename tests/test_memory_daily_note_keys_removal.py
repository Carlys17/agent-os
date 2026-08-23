"""Removing the dead daily-note size keys must not break installs carrying them.

`memory.daily_note_max_chars` and `memory.daily_notes_total_max_chars`
survived the daily-note removal (PR #111) with no consumer, so they are
dropped from `MemoryConfig` and `memory_mode_fingerprint()`. Because
`MemoryConfig` forbids extras, an existing agentos.toml carrying either key
would fail validation at boot without the deprecated-field migration.
"""

from __future__ import annotations

from pathlib import Path

from agentos.gateway.config import GatewayConfig

# -- config -------------------------------------------------------------------


def test_an_existing_config_with_daily_note_keys_still_loads(tmp_path: Path) -> None:
    """The decisive case: MemoryConfig forbids extras, so this would 500 at boot."""
    config_path = tmp_path / "agentos.toml"
    config_path.write_text(
        "[memory]\n"
        "inject_limit = 6400\n"
        "daily_note_max_chars = 4000\n"
        "daily_notes_total_max_chars = 8000\n",
        encoding="utf-8",
    )

    config = GatewayConfig.load(config_path)

    assert config.memory.inject_limit == 6400
    assert not hasattr(config.memory, "daily_note_max_chars")
    assert not hasattr(config.memory, "daily_notes_total_max_chars")


def test_the_dropped_keys_are_reported_not_silently_eaten() -> None:
    from agentos.gateway.config_migration import DEPRECATED_MEMORY_FIELDS

    assert "memory.daily_note_max_chars" in DEPRECATED_MEMORY_FIELDS
    assert "memory.daily_notes_total_max_chars" in DEPRECATED_MEMORY_FIELDS


def test_the_fingerprint_no_longer_carries_daily_note_keys() -> None:
    fingerprint = GatewayConfig().memory_mode_fingerprint()
    assert "daily_note_max_chars" not in fingerprint
    assert "daily_notes_total_max_chars" not in fingerprint


def test_the_keys_are_not_configurable() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GatewayConfig(memory={"daily_note_max_chars": 4000})
    with pytest.raises(ValidationError):
        GatewayConfig(memory={"daily_notes_total_max_chars": 8000})
