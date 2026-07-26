"""Compaction must not demand a flush receipt nothing can produce.

`flush_compaction_safety_mode = "block"` tells compaction to refuse unless a
safe flush receipt exists. That is a reasonable demand *while the flush path
is running*. With flush disabled -- the default, and the end state once the
flush stack is removed -- no receipt is ever written, so "block" refuses
compaction on every single turn.

The failure is slow and quiet: the context window fills, the provider
eventually errors, and the only clue is one warning line. So the requirement
is gated on flush actually being enabled.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agentos.session.compaction_lifecycle import (
    compaction_memory_status,
    pre_compaction_flush_enabled,
    pre_compaction_flush_requires_safe_receipt,
)


def _config(
    *,
    mode: str | None = None,
    legacy: bool = False,
    flush_enabled: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        memory=SimpleNamespace(
            flush_compaction_safety_mode=mode,
            flush_compaction_requires_safe_receipt=legacy,
            flush_enabled=flush_enabled,
        )
    )


def _compaction_allowed(config: SimpleNamespace) -> bool:
    """Does compaction proceed when no receipt exists (flush service absent)?"""
    requires = pre_compaction_flush_requires_safe_receipt(config)
    status = compaction_memory_status(
        None,
        deterministic_receipt_safe=not requires,
        required=True,
    )
    return status.allows_destructive_compaction


# -- the regression --------------------------------------------------------


def test_block_mode_does_not_stall_compaction_when_flush_is_off():
    """The decisive case: "block" with no flush path must not wedge compaction."""
    assert _compaction_allowed(_config(mode="block")) is True


def test_legacy_requires_safe_receipt_does_not_stall_compaction_when_flush_is_off():
    """The legacy flag escalates to "block" internally -- same trap."""
    assert _compaction_allowed(_config(legacy=True)) is True


# -- the feature still works where it means something ----------------------


def test_block_mode_is_still_enforced_when_flush_is_enabled():
    """Gating must not quietly disable the safety mode for users relying on it."""
    config = _config(mode="block", flush_enabled=True)
    assert pre_compaction_flush_requires_safe_receipt(config) is True
    assert _compaction_allowed(config) is False


def test_the_gate_matches_pre_compaction_flush_enabled():
    """Both predicates answer the same underlying question, so they agree."""
    for flush_enabled in (True, False):
        config = _config(mode="block", flush_enabled=flush_enabled)
        assert pre_compaction_flush_requires_safe_receipt(config) == (
            pre_compaction_flush_enabled(config)
        )


# -- everything else is unchanged ------------------------------------------


@pytest.mark.parametrize(
    "mode",
    [
        pytest.param(None, id="unset"),
        pytest.param("protect", id="protect"),
        pytest.param("best_effort", id="best_effort"),
        pytest.param("off", id="off"),
    ],
)
def test_non_block_modes_never_required_a_receipt(mode: str | None):
    for flush_enabled in (True, False):
        config = _config(mode=mode, flush_enabled=flush_enabled)
        assert pre_compaction_flush_requires_safe_receipt(config) is False
        assert _compaction_allowed(config) is True


def test_a_missing_memory_config_is_safe():
    assert pre_compaction_flush_requires_safe_receipt(SimpleNamespace(memory=None)) is False


def test_kill_switch_also_releases_the_requirement(monkeypatch: pytest.MonkeyPatch):
    """AGENTOS_SESSION_FLUSH=0 disables flush, so the demand must lift with it."""
    monkeypatch.setenv("AGENTOS_SESSION_FLUSH", "0")
    config = _config(mode="block", flush_enabled=True)
    assert pre_compaction_flush_requires_safe_receipt(config) is False
    assert _compaction_allowed(config) is True
