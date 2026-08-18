"""Normalization for user-supplied session names.

``SessionNode.display_name`` is the one field a user can freely set to label a
session (``/rename``, ``agentos sessions rename``, the Web UI title editor).
Every write path funnels through :func:`normalize_session_name` so the stored
value stays single-line, trimmed, and short enough for list rows and the CLI
toolbar chip.
"""

from __future__ import annotations

import re

#: Longest name we persist. The column is ``TEXT`` so this is a display
#: budget, not a storage one — long enough for a sentence-ish label, short
#: enough that a ``sessions list`` row stays readable.
MAX_SESSION_NAME_LENGTH = 120

_WHITESPACE = re.compile(r"\s+")


def normalize_session_name(value: object) -> str | None:
    """Return a storable session name, or ``None`` when the name is cleared.

    Control characters are dropped, all whitespace runs (including newlines
    pasted in from a terminal) collapse to single spaces, and the result is
    trimmed to :data:`MAX_SESSION_NAME_LENGTH`. An empty or whitespace-only
    input normalizes to ``None``, which callers treat as "clear the name and
    fall back to the derived title".
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("session name must be a string")

    cleaned = "".join(ch for ch in value if ch.isprintable() or ch.isspace())
    collapsed = _WHITESPACE.sub(" ", cleaned).strip()
    if not collapsed:
        return None
    return collapsed[:MAX_SESSION_NAME_LENGTH].strip()
