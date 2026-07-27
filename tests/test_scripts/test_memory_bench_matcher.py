"""Fact matching for the curated-memory benchmark.

The matcher decides whether a planted fact reached memory, so a bug in it
moves every rate the benchmark reports. It got this wrong twice: plain
substring matching scored `go` against "Django", and the first correction
anchored both ends and stopped `mock` matching "mocks", which read as a
40-point regression that had not happened.

Both mistakes are pinned here because the numbers exist to be compared
against a later rewrite, and a matcher wrong in either direction misreads
the result.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from memory_bench import _matches  # noqa: E402


@pytest.mark.parametrize(
    ("text", "alternative"),
    [
        ("I use Go and Postgres", "go"),
        ("never suggest mocks in tests", "mock"),
        ("Deploys happen on Fridays only", "friday"),
        ("Postgres via testcontainers", "postgres"),
        ("there is no problem", "no "),
        ("Timezone: UTC", "utc"),
    ],
)
def test_alternative_matches_at_a_word_start(text: str, alternative: str) -> None:
    """A suffix is allowed: memory paraphrases and pluralises freely."""
    assert _matches(text, [[alternative]]) is True


@pytest.mark.parametrize(
    ("text", "alternative"),
    [
        ("I use Django", "go"),
        ("the algorithm", "go"),
        ("nothing here", "no "),
        ("unmocked call", "mock"),
    ],
)
def test_alternative_does_not_match_mid_word(text: str, alternative: str) -> None:
    """Substring matching scored all of these as hits and inflated the rates."""
    assert _matches(text, [[alternative]]) is False


def test_groups_are_anded_and_alternatives_ored() -> None:
    """A two-part fact only counts when both parts survive."""
    expect = [["friday"], ["owns", "you own"]]

    assert _matches("Deploys Fridays only. Owns the release checklist.", expect) is True
    assert _matches("Deploys Fridays only.", expect) is False
    assert _matches("Owns the release checklist.", expect) is False


def test_matching_is_case_insensitive() -> None:
    assert _matches("WAREHOUSE_DSN", [["warehouse_dsn"]]) is True


def test_regex_metacharacters_in_an_alternative_are_literal() -> None:
    """Fact values carry dots and plus signs; they must not act as regex."""
    assert _matches("go 1.25", [["1.25"]]) is True
    assert _matches("go 1x25", [["1.25"]]) is False


def test_empty_expectation_matches_anything() -> None:
    """No groups means nothing to satisfy, which `all()` reports as true."""
    assert _matches("anything at all", []) is True
