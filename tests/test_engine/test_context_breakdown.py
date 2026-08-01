from __future__ import annotations

from agentos.engine.context_breakdown import (
    build_breakdown,
    measure_tools,
    tokens_from_chars,
    tool_payload_chars,
)
from agentos.provider.types import ToolDefinition, ToolInputSchema


def _tool(name: str, description: str = "", properties: dict | None = None) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        input_schema=ToolInputSchema(properties=properties or {}, required=[]),
    )


def test_tokens_follow_the_runtime_four_char_rule() -> None:
    assert tokens_from_chars(0) == 0
    assert tokens_from_chars(3) == 0
    assert tokens_from_chars(4) == 1
    assert tokens_from_chars(4000) == 1000


def test_negative_char_counts_do_not_produce_negative_tokens() -> None:
    assert tokens_from_chars(-10) == 0


def test_tool_payload_measures_the_shape_sent_to_the_provider() -> None:
    small = _tool("a")
    large = _tool(
        "b",
        description="a much longer description",
        properties={"path": {"type": "string", "description": "where"}},
    )

    assert tool_payload_chars(large) > tool_payload_chars(small)


def test_a_tool_whose_schema_will_not_serialise_still_reports_a_size() -> None:
    broken = _tool("broken", description="d", properties={"x": {"default": object()}})

    # Falling back to zero would understate the payload and hide the tool.
    assert tool_payload_chars(broken) > 0


def test_tools_section_counts_every_tool() -> None:
    section, per_tool = measure_tools([_tool("a"), _tool("b"), _tool("c")])

    assert section.name == "tools"
    assert section.items == 3
    assert len(per_tool) == 3
    assert section.chars == sum(t.chars for t in per_tool)


def test_largest_tools_are_ranked_by_size() -> None:
    breakdown = build_breakdown(
        tools=[
            _tool("tiny"),
            _tool("huge", description="x" * 500),
            _tool("middling", description="y" * 100),
        ]
    )

    assert [t.name for t in breakdown.largest_tools(2)] == ["huge", "middling"]


def test_system_prompt_is_split_into_cached_and_per_turn() -> None:
    breakdown = build_breakdown(system_prompt=("BASE" * 100, "SUFFIX" * 10))

    names = [s.name for s in breakdown.sections]
    assert "system prompt (cached)" in names
    assert "system prompt (per-turn)" in names


def test_a_plain_string_prompt_reports_only_the_cached_part() -> None:
    breakdown = build_breakdown(system_prompt="BASE" * 100)

    names = [s.name for s in breakdown.sections]
    assert names == ["system prompt (cached)"]


def test_empty_inputs_produce_an_empty_breakdown() -> None:
    breakdown = build_breakdown()

    assert breakdown.sections == ()
    assert breakdown.total_tokens == 0


def test_totals_are_the_sum_of_the_sections() -> None:
    breakdown = build_breakdown(
        tools=[_tool("a", description="x" * 40)],
        system_prompt="y" * 80,
    )

    assert breakdown.total_chars == sum(s.chars for s in breakdown.sections)
    assert breakdown.total_tokens == tokens_from_chars(breakdown.total_chars)


def test_profiles_round_trip_through_the_serialised_form() -> None:
    breakdown = build_breakdown(
        tools=[_tool("a")],
        profiles={"full": (46, 7273), "coding": (14, 1648)},
    )

    payload = breakdown.to_dict()

    assert payload["profiles"]["coding"] == {"tools": 14, "tokens": 1648}
    assert payload["sections"][0]["name"] == "tools"
    assert payload["total_tokens"] == breakdown.total_tokens
