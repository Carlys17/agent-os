"""Session-scoped cache of approved action intents.

The per-approval queue treats every tool invocation as a fresh request. That
means approving ``rm /tmp/x`` does nothing for a subsequent
``os.remove("/tmp/x")`` or ``Path("/tmp/x").unlink()`` — the model can paraphrase
its way past approval prompts and the user has to press y repeatedly. This
module normalizes destructive actions to a semantic key (intent kind + target)
and remembers approvals for a short window, so paraphrased retries of the same
intent proceed without another prompt.

Recursive/Force Dimension (fixes #849)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The cache key carries a *recursive/force* dimension (``bool``).  A non-
recursive approval (``rm /tmp/x``) must **not** satisfy a recursive check
(``rm -rf /tmp/x``) — that is the flag-replay vulnerability.  Conversely,
a recursive approval (``rm -rf /tmp/x`` or ``shutil.rmtree("/tmp/x")``) MAY
satisfy a non-recursive check because the superset operation was already
approved.  The public ``_extract_intents`` helper intentionally returns only
``(kind, target)`` so that callers like :mod:`sensitive_paths` are not
affected; the recursive dimension lives only inside ``IntentApprovalCache``.

Scope: only *delete* intents for now, since that is the bulk of user-observed
pain.  Extend ``_extract_intents`` if other classes (write-outside-workspace,
network egress) need intent-level memory.
"""

from __future__ import annotations

import os
import re
import shlex
import threading
import time
from pathlib import Path

_DEFAULT_TTL_SECONDS = 30 * 60
_ALWAYS_TTL_SECONDS = 365 * 24 * 3600  # effectively never expires within a session


def _norm_path(raw: str, *, base_dir: str | Path | None = None) -> str:
    """Best-effort absolute-path normalization.

    Leaves non-path tokens alone (so ``*`` or variable references don't get
    expanded into something wrong).
    """
    if not raw or raw.startswith(("$", "`")) or raw in {"*", "-"}:
        return raw
    try:
        path = Path(raw).expanduser()
        if base_dir is not None and not path.is_absolute():
            path = Path(base_dir).expanduser() / path
        return str(path.resolve(strict=False))
    except (OSError, ValueError):
        return raw


# Regex-based extractors for Python-flavoured deletes.  Each (pattern, recursive)
# tuple uses ``finditer`` so ``shutil.rmtree("a"); os.remove("b")`` yields both
# paths.  ``recursive`` is True when the call can delete non-empty directory trees.
_PY_DELETE_PATTERNS: tuple[tuple[re.Pattern[str], bool], ...] = (
    # os.remove / os.unlink / os.rmdir / os.removedirs — not recursive
    (
        re.compile(r"\bos\.(?:remove|unlink|rmdir|removedirs)\s*\(\s*[\"']([^\"']+)[\"']"),
        False,
    ),
    # shutil.rmtree — recursive
    (
        re.compile(r"\bshutil\.rmtree\s*\(\s*[\"']([^\"']+)[\"']"),
        True,
    ),
    # Path(...).unlink() — not recursive
    (
        re.compile(r"\b(?:pathlib\.)?Path\s*\(\s*[\"']([^\"']+)[\"']\s*\)\s*\.unlink\s*\("),
        False,
    ),
    # Path(...).rmdir() — recursive (full directory tree, per maintainer prescription)
    (
        re.compile(r"\b(?:pathlib\.)?Path\s*\(\s*[\"']([^\"']+)[\"']\s*\)\s*\.rmdir\s*\("),
        True,
    ),
)

# Shell command separators that terminate a single ``rm`` invocation.
_SHELL_SEPARATORS = (";", "&&", "||", "|", "&")


def _rm_tokens_recursive(tokens: list[str]) -> bool:
    """Return True when any flag token implies recursive/recursive-tree delete.

    Covers: -r, -R, -rf / -fr, --recursive, and any -X...r... long/short combo.
    Does not cover -f alone (force without recursion).
    """
    for tok in tokens:
        if not tok.startswith("-"):
            continue
        stripped = tok.lstrip("-")
        if stripped.startswith("-"):  # --long form
            if "recursive" in stripped.lower():
                return True
            continue
        if "r" in stripped.lower():
            return True
    return False


def _extract_rm_targets(command: str) -> list[tuple[str, bool]]:
    """Pull every non-flag argument + its recursive flag from each ``rm`` invocation.

    Handles ``rm a b c``, ``rm -rf /a /b``, quoted paths, and stops at shell
    separators.  Uses ``finditer`` so ``rm foo; rm -rf /bar`` yields targets
    from both invocations independently.  Returns ``list[(target, recursive)]``.
    Does not try to be a full shell parser — falls back to whitespace split
    on shlex errors (unbalanced quotes).
    """
    pattern = re.compile(r"\brm\b([^;\n&|]*)")
    matches = list(pattern.finditer(command))
    if not matches:
        return []

    # ``seen`` maps normalized-path -> (max_recursive bool) to handle dedup
    # with superset-safe fallback when the same target appears both as
    # non-recursive and recursive within one command.
    seen: dict[str, bool] = {}

    for match in matches:
        tail = match.group(1).strip()
        if not tail:
            continue

        token_sets: list[list[str]] = []
        try:
            token_sets.append(shlex.split(tail))
        except ValueError:
            token_sets.append(tail.split())
        if "\\" in tail and (os.name == "nt" or re.search(r"(?:^|\s)\\[^\s]", tail)):
            try:
                token_sets.append(shlex.split(tail, posix=False))
            except ValueError:
                token_sets.append(tail.split())

        for tokens in token_sets:
            recursive = _rm_tokens_recursive(tokens)
            for token in tokens:
                if not token or token.startswith("-"):
                    continue
                existing = seen.get(token)
                if existing is None:
                    seen[token] = recursive
                else:
                    # Keep the superset (True) to avoid under-approving.
                    seen[token] = existing or recursive

    return [(t, r) for t, r in seen.items()]


def _extract_intents_with_flags(
    command: str,
    *,
    base_dir: str | Path | None = None,
) -> list[tuple[str, str, bool]]:
    """Return every recognized destructive intent with its recursive flag.

    ``rm /a /b /c`` -> three ``(kind, target, recursive)`` tuples;
    ``shutil.rmtree('a'); os.remove('b')`` -> two tuples;
    ``rm /a; rm -rf /a`` -> one ``(kind, target, True)`` (superset over both).
    A plain ``echo`` returns an empty list.
    """
    if not command:
        return []

    raw_targets: list[tuple[str, bool]] = []
    raw_targets.extend(_extract_rm_targets(command))

    for pattern, recursive in _PY_DELETE_PATTERNS:
        for m in pattern.finditer(command):
            raw_targets.append((m.group(1), recursive))

    # Dedupe by normalized target, keeping OR of recursive flags (superset-safe).
    seen: dict[str, bool] = {}
    for raw_path, recursive in raw_targets:
        norm = _norm_path(raw_path, base_dir=base_dir)
        existing = seen.get(norm)
        if existing is None:
            seen[norm] = recursive
        else:
            seen[norm] = existing or recursive

    return [("delete", t, r) for t, r in seen.items()]


def _extract_intents(
    command: str,
    *,
    base_dir: str | Path | None = None,
) -> list[tuple[str, str]]:
    """Return every recognized destructive intent, deduped and normalized.

    ``rm /a /b /c`` -> three tuples; ``shutil.rmtree('a'); os.remove('b')`` ->
    two tuples; a plain echo returns an empty list.

    This public helper deliberately strips the recursive dimension so that
    callers like :mod:`sensitive_paths` receive the same ``(kind, target)``
    shape as before the #849 fix.
    """
    return [
        (kind, target)
        for kind, target, _recursive in _extract_intents_with_flags(command, base_dir=base_dir)
    ]


def _extract_intent(command: str) -> tuple[str, str] | None:
    """First extracted intent, or None. Convenience for single-target callers."""
    intents = _extract_intents(command)
    return intents[0] if intents else None


class IntentApprovalCache:
    """In-memory cache keyed by ``(kind, target, recursive)`` with scope-aware expiry.

    Two scopes exist so the approval prompt's ``once`` and ``always`` mean
    what they say:

    * ``once``  — covers only paraphrased retries within the same user turn
                  (rm → os.remove within one model response). Cleared at the
                  start of every new user message via :meth:`clear_scope`.
    * ``always`` — persists for the full session TTL; re-prompts won't appear
                  for the same intent until the process restarts.

    The **recursive dimension** (bool) encodes whether the approved operation
    can delete non-empty directory trees:

    * ``False`` — ``rm`` without ``-r``, ``os.remove``, ``Path.unlink``;
      a non-recursive approval does NOT satisfy a recursive check.
    * ``True``  — ``rm -r`` / ``rm -rf``, ``shutil.rmtree``, ``Path.rmdir``;
      a recursive approval satisfies both recursive AND non-recursive checks
      (superset principle).

    Matching rule: check ``(kind, target, cr)`` finds a match if there exists
    an entry ``(kind, target, rr)`` where ``rr >= cr`` (True ≥ False; False ≥ False).
    """

    def __init__(self, default_ttl: float = _DEFAULT_TTL_SECONDS) -> None:
        self._default_ttl = default_ttl
        # (kind, target, recursive) -> (expires_monotonic, scope)
        self._entries: dict[tuple[str, str, bool], tuple[float, str]] = {}
        self._lock = threading.Lock()

    def record(
        self, command: str, ttl: float | None = None, *, scope: str = "once"
    ) -> list[tuple[str, str]]:
        """Mark every intent extracted from *command* as approved.

        Handles multi-target commands like ``rm a b c`` — each path becomes its
        own cache entry. Returns the list of recorded intents as
        ``(kind, target)`` (the recursive flag is stored internally).
        """
        intents_with_flags = _extract_intents_with_flags(command)
        if not intents_with_flags:
            return []
        expires = time.monotonic() + (ttl if ttl is not None else self._default_ttl)
        with self._lock:
            for kind, target, recursive in intents_with_flags:
                self._entries[(kind, target, recursive)] = (expires, scope)
        return [(kind, target) for kind, target, _ in intents_with_flags]

    def record_always(self, command: str) -> list[tuple[str, str]]:
        """Remember every intent in *command* for the session lifetime."""
        return self.record(command, ttl=_ALWAYS_TTL_SECONDS, scope="always")

    def _find_entry(
        self,
        kind: str,
        target: str,
        check_recursive: bool,
        now: float,
    ) -> tuple[float, str] | None:
        """Find a matching cache entry for (kind, target, check_recursive).

        Matches when an entry ``(kind, target, rr)`` has ``rr >= check_recursive``.
        Expired entries are removed before returning.
        """
        # Candidate entry keys: the superset-first order makes the common case
        # (recursive approval satisfying non-recursive check) fast.
        candidates = (
            [(kind, target, True), (kind, target, False)]
            if not check_recursive
            else [(kind, target, True)]
        )
        for key in candidates:
            entry = self._entries.get(key)
            if entry is None:
                continue
            expires, scope = entry
            if expires < now:
                self._entries.pop(key, None)
                continue
            return entry
        return None

    def check(self, command: str) -> bool:
        """Return True only when **every** extracted intent is still approved.

        Multi-target commands must have approval for *all* targets — one
        missing path means the whole command needs fresh approval.
        """
        intents_with_flags = _extract_intents_with_flags(command)
        if not intents_with_flags:
            return False
        now = time.monotonic()
        with self._lock:
            for kind, target, check_recursive in intents_with_flags:
                entry = self._find_entry(kind, target, check_recursive, now)
                if entry is None:
                    return False
        return True

    def forget(self, command: str) -> None:
        """Remove every cache entry whose (kind, target, recursive) matches
        the intents extracted from *command*."""
        intents_with_flags = _extract_intents_with_flags(command)
        if not intents_with_flags:
            return
        with self._lock:
            for kind, target, recursive in intents_with_flags:
                self._entries.pop((kind, target, recursive), None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def clear_scope(self, scope: str) -> None:
        """Drop every entry whose scope matches, leaving other scopes intact."""
        with self._lock:
            self._entries = {
                intent: data for intent, data in self._entries.items() if data[1] != scope
            }


_cache: IntentApprovalCache | None = None


def get_intent_cache() -> IntentApprovalCache:
    global _cache
    if _cache is None:
        _cache = IntentApprovalCache()
    return _cache


def reset_intent_cache() -> None:
    """Test hook — drop the singleton."""
    global _cache
    _cache = None
