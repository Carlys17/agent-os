"""Regression: BreakerSettings degrades non-numeric config values instead of raising."""

from __future__ import annotations

from typing import Any

from agentos.provider.circuit_breaker import (
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_MAX_COOLDOWN_SECONDS,
    BreakerSettings,
)


class _FakeConfig:
    """Config object whose fields hold non-numeric string values."""

    def __init__(
        self,
        failure_threshold: Any = None,
        cooldown_seconds: Any = None,
        max_cooldown_seconds: Any = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.max_cooldown_seconds = max_cooldown_seconds


# ── __init__ path ───────────────────────────────────────────────────────────


def test_non_numeric_failure_threshold_degrades_to_default() -> None:
    s = BreakerSettings(failure_threshold="three")
    assert s.failure_threshold == DEFAULT_FAILURE_THRESHOLD


def test_non_numeric_cooldown_seconds_degrades_to_default() -> None:
    s = BreakerSettings(cooldown_seconds="invalid")
    assert s.cooldown_seconds == DEFAULT_COOLDOWN_SECONDS


def test_non_numeric_max_cooldown_degrades_to_default() -> None:
    s = BreakerSettings(max_cooldown_seconds="bad")
    assert s.max_cooldown_seconds == DEFAULT_MAX_COOLDOWN_SECONDS


def test_none_field_values_degrade_to_defaults() -> None:
    s = BreakerSettings(failure_threshold=None, cooldown_seconds=None, max_cooldown_seconds=None)
    assert s.failure_threshold == DEFAULT_FAILURE_THRESHOLD
    assert s.cooldown_seconds == DEFAULT_COOLDOWN_SECONDS
    assert s.max_cooldown_seconds == DEFAULT_MAX_COOLDOWN_SECONDS


def test_numeric_values_unchanged() -> None:
    s = BreakerSettings(failure_threshold=7, cooldown_seconds=90.0, max_cooldown_seconds=300.0)
    assert s.failure_threshold == 7
    assert s.cooldown_seconds == 90.0
    assert s.max_cooldown_seconds == 300.0


# ── from_config path ─────────────────────────────────────────────────────────


def test_from_config_non_numeric_degrades_to_defaults() -> None:
    cfg = _FakeConfig(
        failure_threshold="ten",
        cooldown_seconds="ninety",
        max_cooldown_seconds="five hundred",
    )
    s = BreakerSettings.from_config(cfg)
    assert s.failure_threshold == DEFAULT_FAILURE_THRESHOLD
    assert s.cooldown_seconds == DEFAULT_COOLDOWN_SECONDS
    assert s.max_cooldown_seconds == DEFAULT_MAX_COOLDOWN_SECONDS


def test_from_config_none_returns_defaults() -> None:
    s = BreakerSettings.from_config(None)
    assert s.failure_threshold == DEFAULT_FAILURE_THRESHOLD
    assert s.cooldown_seconds == DEFAULT_COOLDOWN_SECONDS
    assert s.max_cooldown_seconds == DEFAULT_MAX_COOLDOWN_SECONDS
