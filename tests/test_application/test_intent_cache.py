"""Regression tests for IntentApprovalCache compound-command bypass fix.

PR #546 fixes P1 security issue #512: when ``rm A; rm -rf /`` is checked
against a cache that only approved ``rm A``, the second ``rm`` must be
rejected. The fix uses ``re.finditer`` + shell-separator-aware tokenization
instead of ``re.search``, so each ``rm`` invocation is parsed independently.

PR for #849: recursive/force dimension.  A non-recursive approval
(``rm /tmp/x``) must NOT satisfy a recursive check (``rm -rf /tmp/x``).
A recursive approval (``rm -rf`` / ``shutil.rmtree``) MAY satisfy a
non-recursive check (superset principle).  Semantic paraphrase normalization
is preserved for same-level operations.

See https://github.com/use-agent-os/agent-os/pull/546
"""

from __future__ import annotations

from pathlib import Path

from agentos.application.intent_cache import IntentApprovalCache


class TestCompoundCommandSeparatorBypass:
    """Every shell separator must be caught by the permission cache.

    A single approved ``rm /a`` followed by a second ``rm /b`` via any of the
    six shell separators (``;``, ``&&``, ``||``, ``|``, ``&``, ``\\n``) must
    return ``False`` — the untargeted path was never approved.
    """

    def _check_separator(self, separator: str) -> None:
        cache = IntentApprovalCache()
        cache.record("rm /a")
        assert cache.check("rm /a") is True
        assert cache.check(f"rm /a{separator} rm /b") is False, (
            f"check('rm /a{separator} rm /b') should be False"
        )

    def test_semicolon(self) -> None:
        self._check_separator(";")

    def test_and_and(self) -> None:
        self._check_separator(" && ")

    def test_or_or(self) -> None:
        self._check_separator(" || ")

    def test_pipe(self) -> None:
        self._check_separator(" | ")

    def test_ampersand(self) -> None:
        self._check_separator(" & ")

    def test_newline(self) -> None:
        self._check_separator("\n")


class TestMultiTargetApproval:
    """Multi-target commands must require approval for all targets."""

    def test_all_targets_approved_passes(self) -> None:
        """rm /a /b recorded -> check('rm /a /b') is True."""
        cache = IntentApprovalCache()
        cache.record("rm /a /b")
        assert cache.check("rm /a /b") is True

    def test_extra_target_not_approved_fails(self) -> None:
        """rm /a /b recorded -> check('rm /a /b /c') is False — /c not approved."""
        cache = IntentApprovalCache()
        cache.record("rm /a /b")
        assert cache.check("rm /a /b /c") is False


class TestRecordAndCheck:
    """Basic record/check lifecycle."""

    def test_empty_command_returns_false(self) -> None:
        cache = IntentApprovalCache()
        assert cache.check("") is False

    def test_non_rm_command_returns_false(self) -> None:
        cache = IntentApprovalCache()
        cache.record("rm /a")
        assert cache.check("echo hello") is False

    def test_record_always_survives_clear_scope(self) -> None:
        cache = IntentApprovalCache()
        cache.record_always("rm /a")
        cache.clear_scope("once")
        assert cache.check("rm /a") is True

    def test_forget_removes_entry(self) -> None:
        cache = IntentApprovalCache()
        cache.record("rm /a")
        assert cache.check("rm /a") is True
        cache.forget("rm /a")
        assert cache.check("rm /a") is False

    def test_clear_drops_all(self) -> None:
        cache = IntentApprovalCache()
        cache.record("rm /a")
        cache.record("rm /b")
        cache.clear()
        assert cache.check("rm /a") is False
        assert cache.check("rm /b") is False


class TestRecursiveForceDimension:
    """Regression tests for GitHub issue #849 — recursive/force flag replay.

    Design: the cache key is ``(kind, target, recursive)`` internally.
    Non-recursive approvals (rm /path) do NOT satisfy recursive checks
    (rm -rf /path).  Recursive approvals MAY satisfy non-recursive checks
    (superset principle).
    """

    # --- A: escalation blocked ---
    def test_non_recursive_approval_does_not_satisfy_recursive_check(self) -> None:
        """record('rm /tmp/a'); check('rm -rf /tmp/a') -> False."""
        cache = IntentApprovalCache()
        cache.record("rm /tmp/a")
        assert cache.check("rm -rf /tmp/a") is False

    def test_non_recursive_approval_does_not_satisfy_r_flag(self) -> None:
        """record('rm /tmp/a'); check('rm -r /tmp/a') -> False."""
        cache = IntentApprovalCache()
        cache.record("rm /tmp/a")
        assert cache.check("rm -r /tmp/a") is False

    def test_non_recursive_approval_does_not_satisfy_capital_r_flag(self) -> None:
        """record('rm /tmp/a'); check('rm -R /tmp/a') -> False."""
        cache = IntentApprovalCache()
        cache.record("rm /tmp/a")
        assert cache.check("rm -R /tmp/a") is False

    def test_non_recursive_approval_does_not_satisfy_shutil_rmtree(self) -> None:
        """record('rm /tmp/a'); check('shutil.rmtree("/tmp/a")') -> False."""
        cache = IntentApprovalCache()
        cache.record("rm /tmp/a")
        assert cache.check('shutil.rmtree("/tmp/a")') is False

    # --- B: recursive approval covers recursive variant ---
    def test_recursive_approval_satisfies_recursive_rm(self) -> None:
        """record('rm -rf /tmp/a'); check('rm -rf /tmp/a') -> True."""
        cache = IntentApprovalCache()
        cache.record("rm -rf /tmp/a")
        assert cache.check("rm -rf /tmp/a") is True

    def test_recursive_approval_covers_recursive_rm_variants(self) -> None:
        """record('rm -rf /tmp/a'); check('rm -r /tmp/a') -> True."""
        cache = IntentApprovalCache()
        cache.record("rm -rf /tmp/a")
        assert cache.check("rm -r /tmp/a") is True

    def test_recursive_approval_satisfies_shutil_rmtree(self) -> None:
        """record('rm -rf /tmp/a'); check('shutil.rmtree("/tmp/a")') -> True."""
        cache = IntentApprovalCache()
        cache.record("rm -rf /tmp/a")
        assert cache.check('shutil.rmtree("/tmp/a")') is True

    def test_shutil_rmtree_approval_covers_recursive_rm(self) -> None:
        """record('shutil.rmtree("/tmp/a")'); check('rm -rf /tmp/a') -> True."""
        cache = IntentApprovalCache()
        cache.record('shutil.rmtree("/tmp/a")')
        assert cache.check("rm -rf /tmp/a") is True

    def test_shutil_rmtree_approval_covers_non_recursive_rm(self) -> None:
        """record('shutil.rmtree("/tmp/a")'); check('rm /tmp/a') -> True (superset)."""
        cache = IntentApprovalCache()
        cache.record('shutil.rmtree("/tmp/a")')
        assert cache.check("rm /tmp/a") is True

    def test_path_rmdir_approval_is_recursive(self) -> None:
        """record('Path("/tmp/a").rmdir()'); check('rm -rf /tmp/a') -> True."""
        cache = IntentApprovalCache()
        cache.record('Path("/tmp/a").rmdir()')
        assert cache.check("rm -rf /tmp/a") is True

    # --- C: non-recursive paraphrase still cached (same-level equivalence) ---
    def test_non_recursive_approval_satisfies_os_remove(self) -> None:
        """record('rm /tmp/a'); check('os.remove(\"/tmp/a\")') -> True."""
        cache = IntentApprovalCache()
        cache.record("rm /tmp/a")
        assert cache.check('os.remove("/tmp/a")') is True

    def test_non_recursive_approval_satisfies_path_unlink(self) -> None:
        """record('rm /tmp/a'); check('Path("/tmp/a").unlink()') -> True."""
        cache = IntentApprovalCache()
        cache.record("rm /tmp/a")
        assert cache.check('Path("/tmp/a").unlink()') is True

    def test_os_remove_approval_satisfies_rm(self) -> None:
        """record('os.remove(\"/tmp/a\")'); check('rm /tmp/a') -> True."""
        cache = IntentApprovalCache()
        cache.record('os.remove("/tmp/a")')
        assert cache.check("rm /tmp/a") is True

    def test_recursive_approval_satisfies_non_recursive_rm(self) -> None:
        """record('rm -rf /tmp/a'); check('rm /tmp/a') -> True (superset)."""
        cache = IntentApprovalCache()
        cache.record("rm -rf /tmp/a")
        assert cache.check("rm /tmp/a") is True

    # --- D: multi-target + recursive interactions ---
    def test_multi_target_with_mixed_flags(self) -> None:
        """record('rm /a /b'); check('rm -rf /a; rm /b') blocked because /b non-rec
        does not satisfy /a recursive entry (but /b non-rec entry is present)."""
        cache = IntentApprovalCache()
        cache.record("rm /a /b")
        # /a: non-rec approval -> no match for recursive check
        # /b: present as non-rec
        # Overall: fails because /a check finds no entry
        assert cache.check("rm -rf /a; rm /b") is False

    def test_forget_removes_recursive_entry(self) -> None:
        """forget removes the exact (kind, target, recursive) entry."""
        cache = IntentApprovalCache()
        cache.record("rm -rf /tmp/a")
        assert cache.check("rm -rf /tmp/a") is True
        cache.forget("rm -rf /tmp/a")
        assert cache.check("rm -rf /tmp/a") is False

    def test_forget_removes_non_recursive_entry(self) -> None:
        """forget removes the non-recursive entry but not a recursive one."""
        cache = IntentApprovalCache()
        cache.record("rm /tmp/a")
        assert cache.check("rm /tmp/a") is True
        cache.forget("rm /tmp/a")
        assert cache.check("rm /tmp/a") is False

    def test_record_returns_kind_target_only(self) -> None:
        """record() return value is unchanged: list[(kind, target)]."""
        cache = IntentApprovalCache()
        result = cache.record("rm -rf /tmp/a")
        assert len(result) == 1
        kind, target = result[0]
        assert kind == "delete"
        # Path normalization is platform-dependent (absolute Windows form vs
        # /tmp/a on POSIX) — assert on the basename, not the absolute form.
        assert Path(target).name == "a"

    def test_record_always_persists_recursive(self) -> None:
        """record_always + clear_scope('once') leaves recursive entry."""
        cache = IntentApprovalCache()
        cache.record_always("rm -rf /tmp/a")
        cache.clear_scope("once")
        assert cache.check("rm -rf /tmp/a") is True

    def test_superset_dedup_from_single_command(self) -> None:
        """rm /a; rm -rf /a in one command stores only the recursive entry."""
        cache = IntentApprovalCache()
        cache.record("rm /a; rm -rf /a")
        assert cache.check("rm /a") is True
        assert cache.check("rm -rf /a") is True
