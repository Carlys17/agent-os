#!/usr/bin/env python3
"""Measure how much curated memory actually retains and hands back.

Motivation: "memory works poorly" is a felt thing, not a number, so a rebuild
has nothing to prove itself against. This drives the REAL turn path
(``build_services`` -> ``TurnRunner.run`` -> nudge review -> ``memory`` tool)
against a throwaway workspace and reports three rates:

- **capture** — of N planted durable facts, how many reached MEMORY.md/USER.md
- **recall**  — how many a FRESH session answers with no tools, i.e. purely
  from the curated block injected into its system prompt
- **noise**   — entries written that match no planted fact

capture and recall are deliberately separate. A fact can be written and still
be unreachable (injection budget, formatting, a store the prompt never reads),
and that failure is invisible if you only diff the files.

Two things this had to get right, both of which silently corrupt the numbers:

1. Services are built ONCE and held open for the whole run. The nudge review
   is a background turn scheduled after the reply is already on the wire, so a
   harness that builds and tears down services per turn kills the review with
   "Storage not connected" and ends up measuring only what the agent wrote
   unprompted -- while still reporting a healthy-looking capture rate.
2. Both curated files ship with seeded template boilerplate ("Use this file
   for...", "- Name:"). Counting entries naively scores that scaffolding as
   agent-written noise, so the pre-plant snapshot is subtracted.

Everything runs under a temp AGENTOS home: the caller's ~/.agentos is never
read or written. Turns cost real provider tokens, and the model is stochastic,
so trust `--trials 3+` before drawing conclusions.

Usage:
    uv run python scripts/memory_bench.py --model z-ai/glm-5.2
    uv run python scripts/memory_bench.py --trials 3 --out bench.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import statistics
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_FACTS = REPO_ROOT / "tests" / "data" / "memory_bench" / "facts.jsonl"

# Kept low so reviews actually fire inside a short scripted run. The shipped
# default is 10, which no benchmark of this length would ever reach.
NUDGE_INTERVAL = 2

# The nudge is deliberately fire-and-forget after the reply. Give the last
# review room to land before reading the files.
NUDGE_SETTLE_SECONDS = 8.0

RECALL_PREFIX = (
    "Answer from memory only. Do not call any tools. "
    "If you do not know, reply exactly 'I don't know'.\n\n"
)

ENTRY_DELIMITER = "§"

# OpenRouter intermittently routes a model to a provider that does not host it
# and answers 404. That is infrastructure, not memory, but a blank answer is
# indistinguishable from a wrong one, so it would score as a miss.
TURN_RETRIES = 2
RETRY_BACKOFF_SECONDS = 3.0


@dataclass
class Fact:
    id: str
    kind: str
    turn: str
    probe: str | None
    expect_any: list[list[str]] | None
    why: str

    @property
    def is_planted(self) -> bool:
        """Memory-worthy: expected to be written, never counted as noise.

        Includes ``pressure`` turns, which exist only to fill the char budget
        and force consolidation. They are legitimately save-worthy, so writing
        them is not a precision failure.
        """
        return self.kind != "filler"

    @property
    def is_scored(self) -> bool:
        """Counted in the capture/recall rates: only facts with a probe."""
        return self.is_planted and bool(self.probe) and bool(self.expect_any)


@dataclass
class TrialResult:
    captured: dict[str, bool] = field(default_factory=dict)
    recalled: dict[str, bool] = field(default_factory=dict)
    answers: dict[str, str] = field(default_factory=dict)
    memory_md: str = ""
    user_md: str = ""
    new_entries: list[str] = field(default_factory=list)
    curated_chars: int = 0
    noise_entries: list[str] = field(default_factory=list)
    nudge_reviews: int = 0
    nudge_failures: int = 0
    errors: list[str] = field(default_factory=list)


def load_facts(path: Path) -> list[Fact]:
    facts: list[Fact] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            facts.append(Fact(**json.loads(line)))
    return facts


def _matches(text: str, expect_any: list[list[str]]) -> bool:
    """Every group must be satisfied by at least one of its alternatives.

    Groups are ANDed, alternatives inside a group are ORed, so a fact with two
    parts ("Fridays", "I own it") only counts when both parts survive.

    An alternative must begin at a word boundary but may carry a suffix, so
    `mock` matches "mocks" and `friday` matches "Fridays" while `go` no longer
    matches "Django".

    Both halves of that are load-bearing and each was wrong once. Plain
    substring matching scored `go` against "Django" and `no ` against almost
    any sentence, inflating every rate it touched. Anchoring both ends instead
    swung it the other way: an entry reading "never suggest mocks in tests"
    stopped matching `mock` and a correctly-captured fact scored zero, which
    read as a 40-point regression that had not happened.
    """
    low = text.lower()
    return all(
        any(re.search(rf"(?<!\w){re.escape(alt.lower())}", low) for alt in group)
        for group in expect_any
    )


def _entries(text: str) -> list[str]:
    return [e.strip() for e in text.split(ENTRY_DELIMITER) if e.strip()]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _seeded_text(workspace: Path) -> str:
    """Raw curated text before any turn runs, i.e. the shipped template.

    Compared as raw text rather than as a set of entries on purpose: the
    seeded template carries no ``§`` delimiter, so it snapshots as one blob,
    but the curated store re-serializes it into many delimited entries on its
    first write. Matching entry-by-entry would therefore mark every template
    line as agent-written noise.
    """
    return f"{_read(workspace / 'MEMORY.md')}\n{_read(workspace / 'USER.md')}"


def build_config(
    home: Path,
    model: str,
    *,
    isolate_curated: bool,
    memory_char_limit: int,
    user_char_limit: int,
) -> Any:
    from agentos.gateway.config import GatewayConfig

    workspace = home / "workspace"
    state = home / "state"
    workspace.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    return GatewayConfig(
        workspace_dir=str(workspace),
        state_dir=str(state),
        llm={"provider": "openrouter", "model": model, "api_key_env": "OPENROUTER_API_KEY"},
        memory={
            "source": "workspace",
            "nudge": {"enabled": True, "interval": NUDGE_INTERVAL},
            "curated_memory_char_limit": memory_char_limit,
            "curated_user_char_limit": user_char_limit,
            # Turn capture indexes every turn and the retriever feeds matches
            # back into the prompt, so a fact can be "recalled" without ever
            # reaching MEMORY.md. Disabling it leaves the curated block as the
            # only path from a planted fact to a later session, which is what
            # `recall` is supposed to be measuring.
            **({"auto_capture_enabled": False} if isolate_curated else {}),
        },
    )


class _NudgeWatch:
    """Count nudge reviews and their failures from the structlog stream.

    A review that dies is the difference between measuring the nudge and
    measuring only what the agent saved unprompted, so the run reports it
    rather than letting a healthy-looking capture rate hide it.
    """

    def __init__(self) -> None:
        self.reviews = 0
        self.failures = 0

    def __call__(self, _logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event = str(event_dict.get("event", ""))
        if event.startswith("memory_nudge.review"):
            self.reviews += 1
            if "failed" in event or "timeout" in event:
                self.failures += 1
        elif event == "turn_runner.failed":
            provenance = event_dict.get("input_provenance") or {}
            if isinstance(provenance, dict) and provenance.get("kind") == "memory_nudge":
                self.failures += 1
        return event_dict


class Driver:
    """Holds one set of services open across every turn of a trial."""

    def __init__(self, config: Any, db: Path) -> None:
        self._config = config
        self._db = db
        self._svc: Any = None
        self._runner: Any = None

    async def __aenter__(self) -> Driver:
        from agentos.gateway import build_services, build_turn_runner_from_services

        self._svc = await build_services(config=self._config, session_db_path=str(self._db))
        self._runner = build_turn_runner_from_services(self._svc)
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        # Let any in-flight background review finish against live storage.
        await asyncio.sleep(NUDGE_SETTLE_SECONDS)
        if self._svc is not None:
            await self._svc.close()

    async def turn(self, message: str, session_key: str, *, timeout: float) -> str:
        last: Exception | None = None
        for attempt in range(TURN_RETRIES + 1):
            try:
                return await self._turn_once(message, session_key, timeout=timeout)
            except Exception as exc:  # noqa: BLE001 - retry transport-level flakiness
                last = exc
                if attempt < TURN_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS)
        raise last if last else RuntimeError("turn failed")

    async def _turn_once(self, message: str, session_key: str, *, timeout: float) -> str:
        from agentos.engine.types import DoneEvent, ErrorEvent, TextDeltaEvent
        from agentos.gateway.routing import build_cli_route_envelope, tool_context_from_envelope
        from agentos.session.keys import canonicalize_session_key
        from agentos.tools.types import InteractionMode

        key = canonicalize_session_key(session_key)
        await self._svc.session_manager.get_or_create(key, agent_id="main")
        await self._svc.session_manager.append_message(key, role="user", content=message)

        envelope = build_cli_route_envelope(
            session_key=key,
            agent_id="main",
            channel_id="cli:membench",
            sender_id="membench",
            source_name="memory_bench",
            interaction_mode=InteractionMode.UNATTENDED,
        )
        tool_ctx = tool_context_from_envelope(
            envelope,
            workspace_dir=str(getattr(self._config, "workspace_dir", "")),
        )

        parts: list[str] = []
        errors: list[str] = []
        async for event in self._runner.run(
            message,
            key,
            tool_context=tool_ctx,
            agent_id="main",
            timeout=timeout,
            history_has_persisted_user=True,
        ):
            if isinstance(event, TextDeltaEvent):
                parts.append(event.text)
            elif isinstance(event, ErrorEvent):
                errors.append(event.message)
            elif isinstance(event, DoneEvent) and event.text:
                parts = [event.text]
        if errors:
            raise RuntimeError("; ".join(errors[:2]))
        return "".join(parts).strip()


async def run_trial(
    facts: list[Fact],
    *,
    model: str,
    timeout: float,
    keep: bool,
    verbose: bool,
    isolate_curated: bool,
    memory_char_limit: int,
    user_char_limit: int,
) -> TrialResult:
    import structlog

    home = Path(tempfile.mkdtemp(prefix="agentos-membench-"))
    prev_home = os.environ.get("AGENTOS_HOME")
    os.environ["AGENTOS_HOME"] = str(home)

    watch = _NudgeWatch()
    prev_config = structlog.get_config()
    structlog.configure(processors=[watch, *prev_config["processors"]])

    result = TrialResult()
    try:
        config = build_config(
            home,
            model,
            isolate_curated=isolate_curated,
            memory_char_limit=memory_char_limit,
            user_char_limit=user_char_limit,
        )
        workspace = home / "workspace"
        memory_md, user_md = workspace / "MEMORY.md", workspace / "USER.md"

        async with Driver(config, home / "state" / "sessions.db") as driver:
            # Snapshot the seeded template so its boilerplate is never scored
            # as agent-written noise. The store writes the template lazily on
            # its first load, not at build_services, so force that here --
            # otherwise the snapshot is empty and every template line lands in
            # the noise count.
            seeded = _seeded_text(workspace)

            # -- phase 1: plant ------------------------------------------
            # One session, so the nudge review sees the conversation it reviews.
            for fact in facts:
                try:
                    reply = await driver.turn(
                        fact.turn, "agent:main:bench-plant", timeout=timeout
                    )
                    if verbose:
                        print(f"    plant[{fact.id}] -> {reply[:70]}")
                except Exception as exc:  # noqa: BLE001 - one bad turn must not kill the run
                    result.errors.append(f"plant/{fact.id}: {exc}")

            await asyncio.sleep(NUDGE_SETTLE_SECONDS)

            # -- phase 2: what was written -------------------------------
            result.memory_md = _read(memory_md)
            result.user_md = _read(user_md)
            written = f"{result.memory_md}\n{result.user_md}"
            result.curated_chars = len(result.memory_md)
            result.new_entries = [
                e
                for e in _entries(result.memory_md) + _entries(result.user_md)
                if e not in seeded
            ]

            for fact in facts:
                if fact.is_scored and fact.expect_any:
                    result.captured[fact.id] = _matches(written, fact.expect_any)

            result.noise_entries = [
                e[:140]
                for e in result.new_entries
                if not any(
                    f.expect_any and _matches(e, f.expect_any) for f in facts if f.is_planted
                )
            ]

            # -- phase 3: can a fresh session reach it? ------------------
            # New session key, same workspace: the only path from the planted
            # facts to this turn is the curated block in the system prompt.
            for fact in facts:
                if not fact.is_scored or fact.expect_any is None:
                    continue
                try:
                    answer = await driver.turn(
                        RECALL_PREFIX + fact.probe,
                        f"agent:main:bench-recall-{fact.id}",
                        timeout=timeout,
                    )
                except Exception as exc:  # noqa: BLE001
                    result.errors.append(f"recall/{fact.id}: {exc}")
                    answer = ""
                result.answers[fact.id] = answer
                result.recalled[fact.id] = _matches(answer, fact.expect_any)
                if verbose:
                    mark = "OK  " if result.recalled[fact.id] else "MISS"
                    print(f"    {mark} {fact.id}: {answer[:70]}")

        result.nudge_reviews = watch.reviews
        result.nudge_failures = watch.failures
        return result
    finally:
        structlog.configure(processors=prev_config["processors"])
        if prev_home is None:
            os.environ.pop("AGENTOS_HOME", None)
        else:
            os.environ["AGENTOS_HOME"] = prev_home
        if keep:
            print(f"  kept workspace: {home}")
        else:
            shutil.rmtree(home, ignore_errors=True)


def _rate(flags: list[bool]) -> float:
    return (sum(flags) / len(flags)) if flags else 0.0


def summarize(
    trials: list[TrialResult],
    facts: list[Fact],
    *,
    mode: str,
    memory_char_limit: int,
) -> dict[str, Any]:
    planted = [f for f in facts if f.is_scored]
    per_fact = {
        fact.id: {
            "capture": _rate([t.captured.get(fact.id, False) for t in trials]),
            "recall": _rate([t.recalled.get(fact.id, False) for t in trials]),
        }
        for fact in planted
    }
    cap = [_rate([t.captured.get(f.id, False) for f in planted]) for t in trials]
    rec = [_rate([t.recalled.get(f.id, False) for f in planted]) for t in trials]
    return {
        "trials": len(trials),
        "facts": len(planted),
        "mode": mode,
        "memory_char_limit": memory_char_limit,
        "capture_rate": statistics.mean(cap) if cap else 0.0,
        "recall_rate": statistics.mean(rec) if rec else 0.0,
        "entries_written_mean": statistics.mean([len(t.new_entries) for t in trials]),
        "memory_chars_mean": statistics.mean([t.curated_chars for t in trials]),
        "noise_entries_mean": statistics.mean([len(t.noise_entries) for t in trials]),
        "nudge_reviews_total": sum(t.nudge_reviews for t in trials),
        "nudge_failures_total": sum(t.nudge_failures for t in trials),
        "empty_memory_trials": sum(1 for t in trials if not t.new_entries),
        "per_fact": per_fact,
        "answers": [t.answers for t in trials],
        "noise_samples": [e for t in trials for e in t.noise_entries][:10],
        "errors": [e for t in trials for e in t.errors],
    }


def render(summary: dict[str, Any], facts: list[Fact]) -> str:
    by_id = {f.id: f for f in facts}

    def pct(value: float) -> str:
        return f"{value * 100:.0f}%"

    lines = [
        "# Curated memory baseline",
        "",
        f"- trials: **{summary['trials']}**   planted facts: **{summary['facts']}**",
        f"- mode: **{summary['mode']}**",
        f"- capture (reached MEMORY.md/USER.md): **{pct(summary['capture_rate'])}**",
        f"- recall (fresh session, no tools): **{pct(summary['recall_rate'])}**",
        f"- entries written per trial: **{summary['entries_written_mean']:.1f}**"
        f" (noise: {summary['noise_entries_mean']:.1f})",
        f"- MEMORY.md chars at end: **{summary['memory_chars_mean']:.0f}**"
        f" / {summary['memory_char_limit']}",
        f"- nudge reviews: **{summary['nudge_reviews_total']}**"
        f" (failed: {summary['nudge_failures_total']})",
        f"- trials that wrote nothing: **{summary['empty_memory_trials']}**",
        "",
        "| fact | capture | recall | what it tests |",
        "| --- | --- | --- | --- |",
    ]
    for fid, row in summary["per_fact"].items():
        lines.append(
            f"| `{fid}` | {pct(row['capture'])} | {pct(row['recall'])} | {by_id[fid].why} |"
        )
    if summary["nudge_failures_total"]:
        lines += [
            "",
            "> Nudge reviews failed. Capture below reflects only what the agent",
            "> saved unprompted, not the review path.",
        ]
    if summary["noise_samples"]:
        lines += ["", "## Noise written", ""]
        lines += [f"- {e}" for e in summary["noise_samples"]]
    if summary["errors"]:
        lines += ["", "## Errors", ""]
        lines += [f"- {e}" for e in summary["errors"][:12]]
    lines += [
        "",
        "Capture and recall are separate on purpose: a fact can be written and",
        "still be unreachable, which a file diff alone would score as a pass.",
    ]
    return "\n".join(lines)


async def main_async(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="z-ai/glm-5.2", help="provider model id")
    ap.add_argument("--trials", type=int, default=1, help="repeat count (model is stochastic)")
    ap.add_argument("--facts", type=Path, default=DEFAULT_FACTS)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--out", type=Path, help="write the JSON summary here")
    ap.add_argument(
        "--isolate-curated",
        action="store_true",
        help="disable turn capture so recall can only come from MEMORY.md/USER.md",
    )
    ap.add_argument(
        "--memory-char-limit",
        type=int,
        default=4000,
        help="MEMORY.md budget; shrink it to reach consolidation without a 100-turn run",
    )
    ap.add_argument("--user-char-limit", type=int, default=2000, help="USER.md budget")
    ap.add_argument("--keep", action="store_true", help="keep temp workspaces for inspection")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    if not os.environ.get("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY is not set; this benchmark makes real provider calls.")
        return 2

    facts = load_facts(args.facts)
    mode = "curated-only" if args.isolate_curated else "default (capture+retrieval on)"
    print(
        f"memory baseline: {args.trials} trial(s), model={args.model}, "
        f"facts={len(facts)}, mode={mode}"
    )

    trials: list[TrialResult] = []
    for n in range(args.trials):
        print(f"  trial {n + 1}/{args.trials}")
        trials.append(
            await run_trial(
                facts,
                model=args.model,
                timeout=args.timeout,
                keep=args.keep,
                verbose=args.verbose,
                isolate_curated=args.isolate_curated,
                memory_char_limit=args.memory_char_limit,
                user_char_limit=args.user_char_limit,
            )
        )

    summary = summarize(
        trials, facts, mode=mode, memory_char_limit=args.memory_char_limit
    )
    print()
    print(render(summary, facts))
    if args.out:
        args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(argv))


if __name__ == "__main__":
    raise SystemExit(main())
