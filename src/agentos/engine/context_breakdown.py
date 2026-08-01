"""Where the request budget actually goes, before a turn is ever run.

Every provider request carries fixed overhead the operator never sees: the
tool schemas, the system prompt, the skills block. On a stock install the tool
schemas alone are around 7,000 tokens, paid on every call in every turn — and
nothing surfaced that number, so the only way to learn it was to write a script
against the registry.

This module answers it directly, and prices the lever that changes it. The
`[tools] profile` key already narrows the tool surface sharply, but an operator
cannot weigh a lever whose cost they cannot see.

Estimates use the same ~4-chars-per-token rule as the rest of the runtime
(`engine.tool_token_estimate`). It is deliberately a rough count: the point is
the relative weight of each section, which is stable across tokenizers, not a
billing-grade figure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from agentos.provider.types import ToolDefinition

# Mirrors agentos.engine.tool_token_estimate.estimate_tokens, which takes the
# text itself. Only character counts are carried here, so the rule is applied
# to the count directly rather than rebuilding the text to measure it again.
_CHARS_PER_TOKEN = 4


def tokens_from_chars(chars: int) -> int:
    return max(0, chars // _CHARS_PER_TOKEN)


@dataclass(frozen=True)
class SectionCost:
    """One named contributor to the per-request payload."""

    name: str
    chars: int
    items: int = 0

    @property
    def tokens(self) -> int:
        return tokens_from_chars(self.chars)


@dataclass(frozen=True)
class ToolCost:
    name: str
    chars: int

    @property
    def tokens(self) -> int:
        return tokens_from_chars(self.chars)


@dataclass(frozen=True)
class ContextBreakdown:
    """The fixed cost of a request, split by what produced it."""

    sections: tuple[SectionCost, ...] = ()
    tools: tuple[ToolCost, ...] = ()
    profiles: dict[str, tuple[int, int]] = field(default_factory=dict)
    """profile name -> (tool count, estimated tokens)."""

    @property
    def total_chars(self) -> int:
        return sum(section.chars for section in self.sections)

    @property
    def total_tokens(self) -> int:
        return tokens_from_chars(self.total_chars)

    def largest_tools(self, limit: int = 10) -> tuple[ToolCost, ...]:
        return tuple(sorted(self.tools, key=lambda t: t.chars, reverse=True)[:limit])

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_chars": self.total_chars,
            "total_tokens": self.total_tokens,
            "sections": [
                {
                    "name": section.name,
                    "chars": section.chars,
                    "tokens": section.tokens,
                    "items": section.items,
                }
                for section in self.sections
            ],
            "largest_tools": [
                {"name": tool.name, "chars": tool.chars, "tokens": tool.tokens}
                for tool in self.largest_tools()
            ],
            "profiles": {
                name: {"tools": count, "tokens": tokens}
                for name, (count, tokens) in self.profiles.items()
            },
        }


def tool_payload_chars(tool: ToolDefinition) -> int:
    """Serialized size of one tool as it reaches the provider."""

    try:
        payload = {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema.model_dump(exclude_none=True),
        }
        return len(json.dumps(payload, ensure_ascii=False))
    except (TypeError, ValueError):
        return len(str(tool.name)) + len(str(tool.description))


def measure_tools(tools: list[ToolDefinition]) -> tuple[SectionCost, tuple[ToolCost, ...]]:
    per_tool = tuple(ToolCost(name=tool.name, chars=tool_payload_chars(tool)) for tool in tools)
    total = sum(tool.chars for tool in per_tool)
    return SectionCost(name="tools", chars=total, items=len(per_tool)), per_tool


def build_breakdown(
    *,
    tools: list[ToolDefinition] | None = None,
    system_prompt: str | tuple[str, str] | None = None,
    extra_sections: dict[str, str] | None = None,
    profiles: dict[str, tuple[int, int]] | None = None,
) -> ContextBreakdown:
    """Measure the fixed parts of a request.

    Messages are deliberately excluded: they are the conversation, and their
    size is the user's, not something an operator can configure away.
    """

    sections: list[SectionCost] = []
    per_tool: tuple[ToolCost, ...] = ()

    if tools:
        tool_section, per_tool = measure_tools(tools)
        sections.append(tool_section)

    if system_prompt:
        if isinstance(system_prompt, str):
            base, suffix = system_prompt, ""
        else:
            base, suffix = system_prompt
        if base:
            sections.append(SectionCost(name="system prompt (cached)", chars=len(base)))
        if suffix:
            sections.append(SectionCost(name="system prompt (per-turn)", chars=len(suffix)))

    for name, text in (extra_sections or {}).items():
        if text:
            sections.append(SectionCost(name=name, chars=len(text)))

    return ContextBreakdown(
        sections=tuple(sections),
        tools=per_tool,
        profiles=dict(profiles or {}),
    )
