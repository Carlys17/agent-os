"""Eligibility edge cases that decide what the Skills UI calls a skill."""

from __future__ import annotations

import pytest

from agentos.gateway.rpc_skills import _status_detail, _status_from_report
from agentos.skills.eligibility import (
    EligibilityContext,
    check_eligibility,
    diagnose_eligibility,
)
from agentos.skills.types import (
    SkillLayer,
    SkillPlatformMeta,
    SkillRequires,
    SkillSpec,
)


def _spec(name: str = "demo", *, requires: SkillRequires | None = None) -> SkillSpec:
    return SkillSpec(
        name=name,
        description="A skill",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=[],
        content="",
        metadata=SkillPlatformMeta(requires=requires) if requires else None,
    )


# ── requires.env: "set" has to mean "usable" ────────────────────────────────


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_a_blank_required_env_var_counts_as_missing(monkeypatch, value: str) -> None:
    """``export ORACLE_KEY=`` is not a configured key.

    Declaring a variable under ``requires.env`` says the skill cannot run
    without it — an API key, a token, a path. Treating a blank value as present
    reported the skill Ready right up until it failed at runtime, which is the
    one failure the check exists to prevent.
    """
    monkeypatch.setenv("ORACLE_KEY", value)
    spec = _spec(requires=SkillRequires(env=["ORACLE_KEY"]))
    ctx = EligibilityContext()

    assert check_eligibility(spec, ctx) is False

    report = diagnose_eligibility(spec, EligibilityContext())
    assert report.eligible is False
    assert report.missing_env == ["ORACLE_KEY"]
    assert _status_from_report(report) == "needs_setup"


def test_a_populated_required_env_var_is_satisfied(monkeypatch) -> None:
    monkeypatch.setenv("ORACLE_KEY", "sk-live-123")
    spec = _spec(requires=SkillRequires(env=["ORACLE_KEY"]))

    assert check_eligibility(spec, EligibilityContext()) is True
    assert diagnose_eligibility(spec, EligibilityContext()).eligible is True


def test_the_env_cache_agrees_with_a_cold_read(monkeypatch) -> None:
    """The cached branch must apply the same blank rule as the first read.

    The two branches are separate returns, so a fix to one silently leaves the
    other honouring ``export FOO=`` for every skill after the first.
    """
    monkeypatch.setenv("ORACLE_KEY", "")
    spec = _spec(requires=SkillRequires(env=["ORACLE_KEY"]))
    ctx = EligibilityContext()

    first = check_eligibility(spec, ctx)
    assert "ORACLE_KEY" in ctx.env_cache  # second call takes the cached path
    assert check_eligibility(spec, ctx) == first is False


# ── Disabled is not "needs setup" ───────────────────────────────────────────


def test_a_disabled_skill_is_not_described_as_needing_setup() -> None:
    """Nothing is missing — an operator switched it off.

    The wire ``status`` still folds this into ``needs_setup`` (the client splits
    the buckets apart via the ``disabled`` flag), but the human-readable detail
    must not send someone looking for a dependency to install.
    """
    spec = _spec()
    ctx = EligibilityContext(disabled_set={"demo"})

    report = diagnose_eligibility(spec, ctx)

    assert report.disabled is True
    assert report.eligible is False
    assert _status_detail(spec, report) == "Disabled in config"
    assert "Needs setup" not in _status_detail(spec, report)


def test_a_skill_outside_the_enabled_set_reads_as_disabled_too() -> None:
    """Whitelist mode is the same operator decision, reached the other way."""
    spec = _spec()
    report = diagnose_eligibility(spec, EligibilityContext(enabled_set={"other"}))

    assert report.disabled is True
    assert _status_detail(spec, report) == "Disabled in config"


def test_a_genuinely_missing_dependency_still_says_needs_setup(monkeypatch) -> None:
    """The regression guard for the two tests above: amber still means amber."""
    monkeypatch.delenv("ORACLE_KEY", raising=False)
    spec = _spec(requires=SkillRequires(env=["ORACLE_KEY"]))

    report = diagnose_eligibility(spec, EligibilityContext())

    assert report.disabled is False
    assert _status_detail(spec, report) == "Needs setup — missing: ORACLE_KEY"
