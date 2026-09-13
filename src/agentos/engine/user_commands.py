"""User-defined slash commands loaded from ``~/.agentos/commands/*.md``.

Each file is a Markdown file with YAML frontmatter declaring the command's
name, surfaces, and description, and a Markdown body that becomes the
prompt template. ``{{ args }}`` and ``{{ args_or_default }}`` placeholders
are rendered at dispatch time against the user-typed text after the
command name.

Example ``~/.agentos/commands/review.md``:

    ---
    name: /review
    description: Review the current diff.
    surfaces: [cli, channel, web]
    argument_hint: "[scope]"
    ---

    Please review the {{ args_or_default }} changes. Be concise.

When a user types ``/review src/api`` the rendered prompt is
``"Please review the src/api changes. Be concise."`` and is submitted as
a normal user turn through the channel/web/cli dispatch path.

The directory is optional — if it does not exist the loader returns an
empty tuple. Errors in a single file are logged and skipped so one bad
user command does not break the rest of the registry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
import yaml

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class UserCommand:
    """A single user-defined slash command loaded from disk."""

    name: str  # always starts with "/", e.g. "/review"
    description: str
    body: str  # prompt template (rendered with args at dispatch)
    surfaces: frozenset[str]  # subset of {"cli", "channel", "web"}
    source_path: Path
    argument_hint: str = ""

    def render(self, args: str) -> str:
        """Render the body with the given args substituted.

        ``{{ args }}`` is replaced verbatim (empty string if no args).
        ``{{ args_or_default }}`` is replaced by ``args`` when non-empty,
        otherwise by the word "changes" — a pragmatic fallback for
        review-style commands. Processing happens in two passes so that the
        "changes" fallback itself does not get picked up by a second
        ``{{ args }}`` placeholder.
        """
        text = self.body
        # Pass 1: replace args_or_default stub with a sentinel, remembering
        # whether args were non-empty
        if "{{ args_or_default }}" in text:
            sentinel = f"\x00ARGS_OR_DEFAULT\x00{args if args else 'changes'}\x00"
            text = text.replace("{{ args_or_default }}", sentinel)
            # Pass 2: args placeholder — replaces sentinel leftover too if args
            # happens to equal "changes"
            text = text.replace("{{ args }}", args)
            text = text.replace(sentinel, args if args else "changes")
        else:
            # No args_or_default in template — simple one-pass replacement
            text = text.replace("{{ args }}", args)
        return text.strip()


# Regex to split YAML frontmatter from the markdown body.
# The opening fence is "---" at the very start of the file.
_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\n(?P<front>.*?)\n---[ \t]*\n?(?P<body>.*)\Z",
    re.DOTALL,
)

# Default surfaces a user command is exposed on when not specified.
_DEFAULT_SURFACES = frozenset({"cli", "channel", "web"})


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a Markdown file into (frontmatter_dict, body_text).

    Returns ``({}, text)`` when the file has no leading ``---`` fence, so
    plain Markdown bodies without metadata still work.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw = match.group("front")
    body = match.group("body")
    try:
        loaded = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return {}, body
    if not isinstance(loaded, dict):
        return {}, body
    return loaded, body


def _validate_name(raw: Any, source: Path) -> str | None:
    """Return a canonical ``/name`` or None if the candidate is invalid.

    The validation is intentionally tight: lowercase, alnum + hyphen, must
    start with a letter, 1-32 chars. The leading slash is added if missing.
    """
    if not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    if not candidate.startswith("/"):
        candidate = "/" + candidate
    slug = candidate[1:]
    if not slug:
        return None
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", slug):
        return None
    return candidate


def _coerce_surfaces(raw: Any) -> frozenset[str]:
    if not isinstance(raw, list):
        return _DEFAULT_SURFACES
    valid = {"cli", "channel", "web"}
    chosen = {str(s).strip().lower() for s in raw if isinstance(s, str)}
    chosen &= valid
    return frozenset(chosen) if chosen else _DEFAULT_SURFACES


def _parse_command_file(path: Path) -> UserCommand | None:
    """Parse one user command file. Returns None on any failure."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("user_command.read_failed", path=str(path), error=str(exc))
        return None
    meta, body = _parse_frontmatter(text)
    name = _validate_name(meta.get("name"), path)
    if name is None:
        log.warning("user_command.invalid_name", path=str(path), name=meta.get("name"))
        return None
    description = str(meta.get("description", "")).strip() or "User-defined command."
    body_text = body.strip()
    if not body_text:
        log.warning("user_command.empty_body", path=str(path), name=name)
        return None
    surfaces = _coerce_surfaces(meta.get("surfaces"))
    argument_hint = str(meta.get("argument_hint", "")).strip()
    return UserCommand(
        name=name,
        description=description,
        body=body_text,
        surfaces=surfaces,
        source_path=path,
        argument_hint=argument_hint,
    )


def load_user_commands(commands_dir: Path) -> tuple[UserCommand, ...]:
    """Load all user-defined commands from ``commands_dir`` (``*.md``).

    Files are sorted by name for stable output (snapshot tests rely on
    ordering). Failures are logged and skipped; a single broken file does
    not abort the loader. Returns ``()`` when the directory does not
    exist or is not a directory.
    """
    if not commands_dir.exists() or not commands_dir.is_dir():
        return ()
    parsed: list[UserCommand] = []
    for path in sorted(commands_dir.glob("*.md")):
        cmd = _parse_command_file(path)
        if cmd is not None:
            parsed.append(cmd)
    return tuple(parsed)


def user_command_help_lines(commands: tuple[UserCommand, ...]) -> list[str]:
    """Return ``["/name — description", ...]`` for display in ``/help``."""
    return [f"{c.name} — {c.description}" for c in sorted(commands, key=lambda c: c.name)]


__all__ = [
    "UserCommand",
    "load_user_commands",
    "user_command_help_lines",
]
