"""Why a skill is — or is not — offered to the agent right now.

The engine used to answer this question only by side effect: a skill either
appeared in the injected prompt or vanished, with nothing recording which of
the five gates dropped it. This module owns both halves of the decision as
pure functions so the same code answers it twice — once for the turn that
builds the prompt, once for a UI asking before any turn has run.

Nothing here reads process state or mutates its inputs; given the same skills,
tools and eligibility context it returns the same answer every time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from agentos.skills.eligibility import (
    EligibilityContext,
    EligibilityReport,
    check_eligibility,
    diagnose_eligibility,
)
from agentos.skills.injector import (
    RENDER_MODE_COMPACT,
    RENDER_MODE_FULL,
    SkillInjector,
)
from agentos.skills.types import SkillSpec

#: Reason codes. "" is reserved for an offered skill.
REASON_MODEL_INVOCATION_DISABLED = "model_invocation_disabled"
REASON_INELIGIBLE = "ineligible"
REASON_TOOL_GATE = "tool_gate"
REASON_FALLBACK_SUPERSEDED = "fallback_superseded"
REASON_NOT_RETRIEVED = "not_retrieved"
REASON_PROMPT_BUDGET = "prompt_budget"


@dataclass(frozen=True)
class SkillAvailability:
    """Whether the agent is being offered this skill, and why not if it isn't.

    ``detail`` is written for a person reading a tooltip, so it never carries a
    filesystem path — the operator cannot act on one, and the injected prompt
    already leaked home directories once.
    """

    offered: bool
    reason: str = ""
    detail: str = ""


class InjectionPlan(NamedTuple):
    """What ``plan_injection`` decided: the offered skills, why the rest are
    missing, and the prompt those decisions produce.

    The prompt is part of the result rather than something a caller re-renders:
    once the budget forces a truncation, re-running the injector over the kept
    subset can pick a *different* mode (that subset may now fit in full), so a
    second render is not guaranteed to reproduce the first.
    """

    offered: list[SkillSpec]
    availability: dict[str, SkillAvailability]
    prompt: str
    #: Names the budget cut, in the order the injector sacrificed them.
    dropped: list[str]
    #: One of the ``injector.RENDER_MODE_*`` values.
    mode: str = RENDER_MODE_FULL
    #: Cap applied to each description, or None when they are untrimmed.
    description_max_chars: int | None = None


_OFFERED = SkillAvailability(offered=True)


def _quote(names: list[str]) -> str:
    return ", ".join(f"`{n}`" for n in names)


def _plural(names: list[str], singular: str, plural: str) -> str:
    return singular if len(names) == 1 else plural


def _ineligible_detail(spec: SkillSpec, report: EligibilityReport) -> str:
    """Turn a structured eligibility report into one sentence an operator can act on."""
    clauses: list[str] = []

    if report.disabled:
        clauses.append("it is switched off for this workspace")

    if report.wrong_os:
        wanted = ", ".join(spec.metadata.os) if spec.metadata and spec.metadata.os else "another OS"
        clauses.append(f"it runs on {wanted} only")

    if report.missing_bins:
        verb = _plural(report.missing_bins, "is", "are")
        noun = _plural(report.missing_bins, "command", "commands")
        clauses.append(f"the {noun} {_quote(report.missing_bins)} {verb} not on PATH")

    if report.missing_env_detail:
        described = [
            f"`{var.name}` ({var.description})" if var.description else f"`{var.name}`"
            for var in report.missing_env_detail
        ]
        noun = _plural(described, "variable", "variables")
        verb = _plural(described, "is", "are")
        clauses.append(f"the environment {noun} {', '.join(described)} {verb} not set")
    elif report.missing_env:
        noun = _plural(report.missing_env, "variable", "variables")
        verb = _plural(report.missing_env, "is", "are")
        clauses.append(f"the environment {noun} {_quote(report.missing_env)} {verb} not set")

    if not clauses:
        # check_eligibility said no but no category matched — report whatever
        # the diagnosis collected rather than an empty sentence.
        clauses.append(
            "; ".join(report.reasons) if report.reasons else "its requirements are unmet"
        )

    detail = f"Installed, but not offered to the agent: {'; '.join(clauses)}."
    if report.install_hints:
        detail += f" Try: {report.install_hints[0].command}"
    return detail


def gate_skills(
    skills: list[SkillSpec],
    available_tools: set[str],
    elig_ctx: EligibilityContext,
) -> tuple[list[SkillSpec], dict[str, SkillAvailability]]:
    """Pure-Python gate: visibility, eligibility, requires_tools, fallback.

    Returns the skills that survived plus an availability entry for *every*
    input skill. Survivors are marked offered here provisionally — retrieval and
    the prompt budget still run downstream and may override the entry.
    """
    gated: list[SkillSpec] = []
    availability: dict[str, SkillAvailability] = {}

    for s in skills:
        if s.disable_model_invocation:
            availability[s.name] = SkillAvailability(
                offered=False,
                reason=REASON_MODEL_INVOCATION_DISABLED,
                detail=(
                    "Installed, but its manifest sets disable-model-invocation, so the "
                    "agent is never offered it. You can still run it yourself."
                ),
            )
            continue

        if not check_eligibility(s, elig_ctx):
            availability[s.name] = SkillAvailability(
                offered=False,
                reason=REASON_INELIGIBLE,
                detail=_ineligible_detail(s, diagnose_eligibility(s, elig_ctx)),
            )
            continue

        if s.requires_tools and not all(t in available_tools for t in s.requires_tools):
            missing = [t for t in s.requires_tools if t not in available_tools]
            noun = _plural(missing, "tool", "tools")
            verb = _plural(missing, "is", "are")
            availability[s.name] = SkillAvailability(
                offered=False,
                reason=REASON_TOOL_GATE,
                detail=(
                    f"Installed and ready, but not offered to the agent: it needs the "
                    f"{noun} {_quote(missing)}, which {verb} not enabled in this session."
                ),
            )
            continue

        if s.fallback_for_toolsets and any(t in available_tools for t in s.fallback_for_toolsets):
            covered = [t for t in s.fallback_for_toolsets if t in available_tools]
            noun = _plural(covered, "tool", "tools")
            availability[s.name] = SkillAvailability(
                offered=False,
                reason=REASON_FALLBACK_SUPERSEDED,
                detail=(
                    f"Not offered to the agent: it is a fallback for the {noun} "
                    f"{_quote(covered)}, which this session already has natively."
                ),
            )
            continue

        availability[s.name] = _OFFERED
        gated.append(s)

    return gated, availability


def plan_injection(
    gated: list[SkillSpec],
    max_chars: int,
    injection_mode: str = "system",
    *,
    skill_list_tool: bool = False,
) -> InjectionPlan:
    """Render the skills block and report which skills the budget cut.

    ``injection_mode="user_message"`` renders names-only unconditionally and so
    has no budget to exceed; "system" and "user_context" both spend the budget
    on as much description text as fits and may truncate.

    ``skill_list_tool`` says whether the session actually exposes ``skill_list``.
    It decides which route back to the descriptions the block advertises, so it
    must reflect the live tool surface rather than being assumed.
    """
    injector = SkillInjector()
    dropped: list[str]
    mode: str
    description_max_chars: int | None = None

    if injection_mode == "user_message":
        prompt = injector.inject_compact("", gated, skill_list_tool=skill_list_tool)
        dropped = []
        mode = RENDER_MODE_COMPACT if gated else RENDER_MODE_FULL
    else:
        block = injector.render("", gated, max_chars, skill_list_tool=skill_list_tool)
        prompt, dropped = block.text, block.dropped
        mode, description_max_chars = block.mode, block.description_max_chars

    dropped_names = set(dropped)
    offered = [s for s in gated if not s.disable_model_invocation and s.name not in dropped_names]

    availability: dict[str, SkillAvailability] = {}
    detail = (
        f"Installed and ready, but not offered to the agent: the skills section is full "
        f"({max_chars} characters). {len(dropped)} "
        f"{_plural(dropped, 'skill is', 'skills are')} being dropped."
    )
    for s in gated:
        if s.name in dropped_names:
            availability[s.name] = SkillAvailability(
                offered=False,
                reason=REASON_PROMPT_BUDGET,
                detail=detail,
            )
        elif not s.disable_model_invocation:
            availability[s.name] = _OFFERED

    return InjectionPlan(
        offered=offered,
        availability=availability,
        prompt=prompt,
        dropped=dropped,
        mode=mode,
        description_max_chars=description_max_chars,
    )


def retrieval_availability(
    skipped: list[SkillSpec],
    top_k: int,
) -> dict[str, SkillAvailability]:
    """Explain skills that relevance filtering left out of this turn.

    Only reachable when ``skills.filter_enabled`` is on (it defaults to off), and
    the answer depends on the message being answered — hence the detail says so
    rather than presenting it as a standing property of the skill.
    """
    detail = (
        f"Installed and ready, but not offered for this message: relevance filtering is on "
        f"and kept only the {top_k} closest matches, which did not include this skill. "
        "A differently worded message can bring it back."
    )
    return {
        s.name: SkillAvailability(offered=False, reason=REASON_NOT_RETRIEVED, detail=detail)
        for s in skipped
    }
