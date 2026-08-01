"""Which developer tools actually exist on this machine.

An agent asked to run the tests reaches for `pytest`; asked to install
something, for `npm`. When the tool is not installed it finds out by running it
and reading a shell error, which costs a turn and often sends it down a repair
path for a problem that was never the task.

Telling it up front is one short line, and unlike most prompt content it is
constant for the life of the process — so it belongs in the cached part of the
system prompt, paid for once.

Only names are emitted, never paths. `shutil.which` answers with an absolute
path that on most machines contains the operator's home directory, and the
system prompt is not a place to put it.
"""

from __future__ import annotations

import shutil
from functools import lru_cache

# Grouped by what an agent is usually trying to do. Order is stable so the
# rendered line — and therefore the prompt cache — does not churn.
_PROBED_TOOLS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("vcs", ("git", "gh")),
    ("python", ("python3", "uv", "pip", "ruff", "mypy", "pytest")),
    ("node", ("node", "npm", "pnpm", "yarn", "bun", "deno")),
    ("languages", ("go", "cargo", "rustc", "java")),
    ("build", ("make", "cmake")),
    ("search", ("rg", "fd", "jq")),
    ("net", ("curl", "wget")),
    ("containers", ("docker", "kubectl")),
    ("data", ("sqlite3", "psql")),
)

_MAX_RENDERED_CHARS = 400


@lru_cache(maxsize=1)
def available_tools() -> tuple[str, ...]:
    """Names of the probed tools present on PATH.

    Cached for the process: a toolchain does not change under a running agent,
    and re-probing would rewrite a cached prompt prefix for no reason.
    """

    found: list[str] = []
    for _group, names in _PROBED_TOOLS:
        for name in names:
            try:
                if shutil.which(name):
                    found.append(name)
            except OSError:
                # A PATH entry that cannot be read is not worth a failed turn.
                continue
    return tuple(found)


def render_environment_block(tools: tuple[str, ...] | None = None) -> str:
    """Render the prompt block, or "" when there is nothing worth saying."""

    names = available_tools() if tools is None else tools
    if not names:
        return ""
    listed = ", ".join(names)
    if len(listed) > _MAX_RENDERED_CHARS:
        listed = listed[:_MAX_RENDERED_CHARS].rsplit(", ", 1)[0] + ", …"
    return (
        "## Local Toolchain\n\n"
        f"Present on PATH: {listed}.\n"
        "Anything not listed is probably not installed — check before assuming, "
        "and prefer a listed equivalent over installing something."
    )
