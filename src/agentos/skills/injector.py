"""Injects active skill content into system prompts — full/compact modes."""

from __future__ import annotations

from agentos.skills.types import SkillLayer, SkillSpec

#: Character budget for the injected skills block when nothing configures one.
#: Kept here rather than at each call site: the same number is the default for
#: ``skills.max_skills_prompt_chars`` and the fallback the turn pipeline uses
#: when a turn arrives without a skills config, and those two drifting apart is
#: what silently forced default installs into name-only mode.
DEFAULT_MAX_SKILLS_PROMPT_CHARS = 24_000

# Highest precedence first — the same order that decides a name collision. When
# the budget forces a cut it lands on the tail, so a skill in a writable skills
# path outlives a shipped one, and `extra` (read-only config dirs) goes first.
_LAYER_PRECEDENCE: dict[SkillLayer, int] = {
    SkillLayer.WORKSPACE: 0,
    SkillLayer.PROJECT: 1,
    SkillLayer.PERSONAL: 2,
    SkillLayer.MANAGED: 3,
    SkillLayer.BUNDLED: 4,
    SkillLayer.EXTRA: 5,
}
_UNKNOWN_LAYER_RANK = len(_LAYER_PRECEDENCE)


def _escape_xml(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _layer_rank(skill: SkillSpec) -> int:
    return _LAYER_PRECEDENCE.get(skill.layer, _UNKNOWN_LAYER_RANK)


class SkillInjector:
    """Injects skill content into system prompts with budget control."""

    def inject_full(self, system_prompt: str, skills: list[SkillSpec]) -> str:
        """Full mode: name + description for each skill."""
        visible = [s for s in skills if not s.disable_model_invocation]
        if not visible:
            return system_prompt

        lines = [
            "\n\n## Skills",
            "Skills are task playbooks written for this install. They carry the "
            "endpoints, commands, conventions, and known pitfalls that a "
            "general-purpose approach misses.",
            "Skill names are identifiers for `skill_view`; they are not callable tools.",
            "Read <available_skills> before answering. When an entry relates to the "
            'request — even partially — call skill_view(name="<skill_name>") to load '
            "its instructions and follow them, then use only the tools available in "
            "this session.",
            # Bias deliberately toward loading. The two failure modes are not
            # symmetric: loading a skill you did not need wastes a little context,
            # while skipping one that encoded the right steps produces a confidently
            # wrong answer. A skill also encodes how the user wants the task done
            # here, which is not something the model can infer from the request.
            "Lean toward loading. Load a skill even for a task you already know how "
            "to do — it defines how that task should be done in this install.",
        ]
        lines.extend(
            [
                "Answer without a skill only when no entry relates to the request.",
                "",
                "<available_skills>",
            ]
        )
        for s in visible:
            lines.append("  <skill>")
            lines.append(f"    <name>{_escape_xml(s.name)}</name>")
            lines.append(f"    <description>{_escape_xml(s.description)}</description>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return system_prompt + "\n".join(lines)

    def inject_compact(self, system_prompt: str, skills: list[SkillSpec]) -> str:
        """Compact mode: name only (saves tokens). Use skill_view to read full content."""
        visible = [s for s in skills if not s.disable_model_invocation]
        if not visible:
            return system_prompt

        lines = [
            "\n\nSkills are task playbooks written for this install. Only their names "
            "are listed below — each one's description and instructions live inside it.",
            "Skill names are identifiers for `skill_view`; they are not callable tools.",
            # Compact mode strips the descriptions, so the model has nothing to judge
            # relevance against but a name. Telling it to load "only on a clear match"
            # would then be an instruction it cannot follow: no name clearly matches
            # anything. Ask it to open plausible entries instead of guessing.
            "A name alone is not enough to rule a skill out, so call skill_view(name="
            '"<skill_name>") on any entry that plausibly relates to the request before '
            "concluding it does not apply.",
        ]
        lines.extend(["", "<available_skills>"])
        for s in visible:
            lines.append("  <skill>")
            lines.append(f"    <name>{_escape_xml(s.name)}</name>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return system_prompt + "\n".join(lines)

    def inject_skills(
        self,
        system_prompt: str,
        skills: list[SkillSpec],
        max_chars: int = DEFAULT_MAX_SKILLS_PROMPT_CHARS,
    ) -> tuple[str, list[str]]:
        """Auto-select full/compact mode based on token budget.

        Returns the prompt plus the names of any skills the budget forced out,
        so callers can log and surface a silent capability loss.
        """
        if not skills:
            return system_prompt, []

        full = self.inject_full(system_prompt, skills)
        if len(full) - len(system_prompt) <= max_chars:
            return full, []

        compact = self.inject_compact(system_prompt, skills)
        if len(compact) - len(system_prompt) <= max_chars:
            return compact, []

        # Budget exceeded even in compact — truncate skills. Sort by layer
        # precedence first (stable, so within-layer order is untouched) so the
        # cut lands on bundled skills instead of whatever the operator installed.
        visible = [s for s in skills if not s.disable_model_invocation]
        ordered = sorted(visible, key=_layer_rank)
        lo, hi = 0, len(ordered)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            test = self.inject_compact(system_prompt, ordered[:mid])
            if len(test) - len(system_prompt) <= max_chars:
                lo = mid
            else:
                hi = mid - 1
        # If the safety header itself exceeds an extremely small budget, keep
        # one compact skill entry rather than dropping the whole skills section.
        # Losing the guard makes skill names more likely to be mistaken for tools.
        kept = max(lo, 1)
        dropped = [s.name for s in ordered[kept:]]
        return self.inject_compact(system_prompt, ordered[:kept]), dropped
