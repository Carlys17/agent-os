"""Issue #248: user-supplied session names normalize to one stored shape.

Every rename surface (``/rename``, ``agentos sessions rename``, the Web UI
title editor, ``sessions.patch``) funnels through
:func:`normalize_session_name`, so the rules live in one place and are
tested once here.
"""

from __future__ import annotations

import pytest

from agentos.session.naming import MAX_SESSION_NAME_LENGTH, normalize_session_name


def test_trims_and_collapses_whitespace() -> None:
    assert normalize_session_name("  api   refactor  ") == "api refactor"


def test_newlines_collapse_to_single_spaces() -> None:
    # Pasting a multi-line label into a terminal must not store a name that
    # breaks the CLI toolbar chip or a table row.
    assert normalize_session_name("bug\n46\n\ttriage") == "bug 46 triage"


def test_empty_and_whitespace_only_clear_the_name() -> None:
    assert normalize_session_name("") is None
    assert normalize_session_name("   \n\t ") is None
    assert normalize_session_name(None) is None


def test_control_characters_are_dropped() -> None:
    assert normalize_session_name("deep\x00research\x07") == "deepresearch"


def test_long_names_truncate_without_trailing_space() -> None:
    name = normalize_session_name("x" * (MAX_SESSION_NAME_LENGTH + 40))

    assert name is not None
    assert len(name) == MAX_SESSION_NAME_LENGTH

    # A cut landing mid-gap must not leave the stored value ending in a space.
    padded = normalize_session_name("y" * (MAX_SESSION_NAME_LENGTH - 1) + " tail")
    assert padded == "y" * (MAX_SESSION_NAME_LENGTH - 1)


def test_non_string_names_are_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_session_name(42)
