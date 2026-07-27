"""Compaction must not demand a flush receipt nothing can produce.

`flush_compaction_safety_mode = "block"` told compaction to refuse unless a
safe flush receipt existed. That was a reasonable demand while the flush path
was running. It is not any more: the flush service was removed, so no receipt
can ever be written and the demand can never be satisfied.

Left reachable, that combination refuses compaction on every single turn. The
failure is slow and quiet -- the context window fills, the provider eventually
errors, and the only clue is one warning line.

The three keys are therefore rejected by `GatewayConfig` rather than merely
defaulted off, which makes `pre_compaction_flush_enabled()` false for good.
These tests pin that: the keys cannot be set, an existing `agentos.toml`
carrying them still boots, and compaction proceeds regardless.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentos.gateway.config import GatewayConfig
from agentos.gateway.config_migration import (
    DEPRECATED_MEMORY_FIELDS,
    migrate_config_payload,
)
from agentos.session.compaction_lifecycle import (
    compaction_memory_status,
    pre_compaction_flush_enabled,
    pre_compaction_flush_requires_safe_receipt,
)

REMOVED_GATE_KEYS = (
    "flush_enabled",
    "flush_compaction_safety_mode",
    "flush_compaction_requires_safe_receipt",
)


def _compaction_allowed(config: GatewayConfig) -> bool:
    """Does compaction proceed when no receipt exists (flush service absent)?"""
    requires = pre_compaction_flush_requires_safe_receipt(config)
    status = compaction_memory_status(
        None,
        deterministic_receipt_safe=not requires,
        required=pre_compaction_flush_enabled(config),
    )
    return status.allows_destructive_compaction


# -- the keys are gone, not merely defaulted off --------------------------


@pytest.mark.parametrize("key", REMOVED_GATE_KEYS)
def test_safety_gate_keys_are_rejected_by_config(key: str) -> None:
    """Setting one must fail loudly rather than silently wedge compaction."""
    value = "block" if key == "flush_compaction_safety_mode" else True
    with pytest.raises(ValidationError):
        GatewayConfig(memory={key: value})


@pytest.mark.parametrize("key", REMOVED_GATE_KEYS)
def test_existing_config_files_carrying_the_keys_still_boot(key: str) -> None:
    """MemoryConfig forbids extras, so migration has to drop them first."""
    assert f"memory.{key}" in DEPRECATED_MEMORY_FIELDS

    value = "block" if key == "flush_compaction_safety_mode" else True
    result = migrate_config_payload({"memory": {key: value, "source": "workspace"}})

    assert f"memory.{key}" in result.removed_fields
    assert key not in result.payload.get("memory", {})
    assert result.payload["memory"]["source"] == "workspace"
    GatewayConfig(**result.payload)


# -- and so the gate can never re-arm -------------------------------------


def test_flush_is_unconditionally_disabled() -> None:
    assert pre_compaction_flush_enabled(GatewayConfig()) is False
    assert pre_compaction_flush_requires_safe_receipt(GatewayConfig()) is False


def test_env_kill_switch_cannot_re_enable_flush(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENTOS_SESSION_FLUSH=1 is not a back door now that the key is gone."""
    monkeypatch.setenv("AGENTOS_SESSION_FLUSH", "1")
    assert pre_compaction_flush_enabled(GatewayConfig()) is False


def test_compaction_is_allowed_without_a_receipt() -> None:
    """The decisive case: nothing can wedge compaction on a missing receipt."""
    assert _compaction_allowed(GatewayConfig()) is True


def test_a_missing_memory_config_is_safe() -> None:
    from types import SimpleNamespace

    assert pre_compaction_flush_requires_safe_receipt(SimpleNamespace(memory=None)) is False
