"""A tool may raise the ceiling its own results are persisted under.

The default stays where it has always been, so a tool that says nothing keeps
today's behaviour byte for byte. Only a tool that registers a resolver is
treated differently, and the resolver is asked at persistence time so it
follows a config change instead of freezing whatever was true at boot.
"""

from collections.abc import Iterator

import pytest

from agentos.engine.runtime import _MAX_TOOL_RESULT_CHARS, _persisted_tool_result_segment
from agentos.engine.types import ToolResultEvent
from agentos.result_budget import (
    clear_persisted_result_budgets,
    persisted_result_max_chars,
    register_persisted_result_budget,
)


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    clear_persisted_result_budgets()
    yield
    clear_persisted_result_budgets()


def _segment(tool_name: str, chars: int) -> dict:
    return _persisted_tool_result_segment(
        ToolResultEvent(
            tool_use_id="call_1",
            tool_name=tool_name,
            result="x" * chars,
            is_error=False,
        )
    )


def test_unregistered_tool_keeps_the_default_ceiling() -> None:
    assert persisted_result_max_chars("exec_command", default=_MAX_TOOL_RESULT_CHARS) == 2000


def test_volatile_output_is_still_cut_at_two_thousand() -> None:
    register_persisted_result_budget("skill_view", lambda: 14_000)

    segment = _segment("exec_command", 9_000)

    assert segment["result_truncated"] is True
    assert len(segment["result"]) == 2000


def test_registered_tool_persists_a_result_under_its_own_ceiling_whole() -> None:
    register_persisted_result_budget("skill_view", lambda: 14_000)

    segment = _segment("skill_view", 11_996)

    assert segment["result"] == "x" * 11_996
    assert "result_truncated" not in segment


def test_registered_ceiling_is_a_ceiling_not_a_licence() -> None:
    register_persisted_result_budget("skill_view", lambda: 14_000)

    segment = _segment("skill_view", 20_000)

    assert segment["result_truncated"] is True
    assert len(segment["result"]) == 14_000


def test_resolver_is_asked_at_persistence_time() -> None:
    """A config change between two calls has to be visible to the second."""
    ceiling = 14_000
    register_persisted_result_budget("skill_view", lambda: ceiling)

    assert "result_truncated" not in _segment("skill_view", 11_996)

    ceiling = 3_000
    later = _segment("skill_view", 11_996)

    assert later["result_truncated"] is True
    assert len(later["result"]) == 3_000


def test_resolver_returning_zero_disables_truncation() -> None:
    """`max_skill_view_chars = 0` turns the read ceiling off; persistence follows."""
    register_persisted_result_budget("skill_view", lambda: 0)

    segment = _segment("skill_view", 90_000)

    assert segment["result"] == "x" * 90_000
    assert "result_truncated" not in segment


def test_a_failing_resolver_falls_back_to_the_default() -> None:
    """Persisting a turn is never worth failing on."""

    def _broken() -> int:
        raise RuntimeError("config went away")

    register_persisted_result_budget("skill_view", _broken)

    segment = _segment("skill_view", 9_000)

    assert segment["result_truncated"] is True
    assert len(segment["result"]) == 2000
