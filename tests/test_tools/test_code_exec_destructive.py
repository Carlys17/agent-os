"""Regression tests for _check_code_destructive.

These tests pin the behaviour of the destructive‑pattern detector in
``agentos.tools.builtin.code_exec``.  The detector is intentionally shallow —
its only job is to force the approval prompt when an agent is about to do
something destructive.  It does NOT prove safety.

The tests cover:
- Direct calls that must be flagged (os.remove, shutil.rmtree, …)
- Indirect calls that must be flagged (getattr, __import__, eval/exec, …)
- Non‑destructive calls that must NOT be flagged (list.remove, eval(1+1), …)
"""
from __future__ import annotations

from agentos.tools.builtin import code_exec


# ---------------------------------------------------------------------------
# Direct calls — must be flagged
# ---------------------------------------------------------------------------
def test_direct_os_remove() -> None:
    assert code_exec._check_code_destructive('os.remove("/tmp/x")') is not None


def test_direct_os_unlink() -> None:
    assert code_exec._check_code_destructive('os.unlink("/tmp/x")') is not None


def test_direct_os_rmdir() -> None:
    assert code_exec._check_code_destructive('os.rmdir("/tmp/x")') is not None


def test_direct_os_removedirs() -> None:
    assert code_exec._check_code_destructive('os.removedirs("/tmp/x")') is not None


def test_direct_shutil_rmtree() -> None:
    assert code_exec._check_code_destructive('shutil.rmtree("/tmp/x")') is not None


def test_direct_path_unlink() -> None:
    assert code_exec._check_code_destructive('Path("/tmp/x").unlink()') is not None


def test_direct_path_rmdir() -> None:
    assert code_exec._check_code_destructive('Path("/tmp/x").rmdir()') is not None


def test_direct_os_system_with_rm() -> None:
    assert code_exec._check_code_destructive('os.system("rm -rf /tmp/x")') is not None


def test_direct_subprocess_rm() -> None:
    assert code_exec._check_code_destructive(
        'subprocess.run(["rm", "-rf", "/tmp/x"])'
    ) is not None


# ---------------------------------------------------------------------------
# Indirect calls — must be flagged (the bypass we are closing)
# ---------------------------------------------------------------------------
def test_getattr_concat_bypass() -> None:
    """getattr(os, "rem" + "ove") — the original regex misses this."""
    assert code_exec._check_code_destructive(
        'getattr(os, "rem" + "ove")("/tmp/x")'
    ) is not None


def test_getattr_plain() -> None:
    assert code_exec._check_code_destructive(
        'getattr(os, "remove")("/tmp/x")'
    ) is not None


def test_getattr_unlink() -> None:
    assert code_exec._check_code_destructive(
        'getattr(os, "unlink")("/tmp/x")'
    ) is not None


def test_getattr_rmdir() -> None:
    assert code_exec._check_code_destructive(
        'getattr(os, "rmdir")("/tmp/x")'
    ) is not None


def test_getattr_rmtree() -> None:
    assert code_exec._check_code_destructive(
        'getattr(shutil, "rmtree")("/tmp/x")'
    ) is not None


def test_dunder_import_remove() -> None:
    assert code_exec._check_code_destructive(
        '__import__("os").remove("/tmp/x")'
    ) is not None


def test_dunder_import_system_rm() -> None:
    assert code_exec._check_code_destructive(
        '__import__("os").system("rm -rf /tmp/x")'
    ) is not None


def test_importlib_remove() -> None:
    assert code_exec._check_code_destructive(
        'importlib.import_module("os").remove("/tmp/x")'
    ) is not None


def test_eval_of_destructive_string() -> None:
    assert code_exec._check_code_destructive(
        "eval(\"os.remove('/tmp/x')\")"
    ) is not None


def test_exec_of_destructive_string() -> None:
    assert code_exec._check_code_destructive(
        "exec(\"os.remove('/tmp/x')\")"
    ) is not None


def test_eval_of_destructive_concat() -> None:
    """eval of a string built via concatenation."""
    assert code_exec._check_code_destructive(
        "eval(\"os.\" + \"remove\" + \"('/tmp/x')\")"
    ) is not None


def test_exec_of_destructive_concat() -> None:
    assert code_exec._check_code_destructive(
        "exec(\"os.\" + \"remove\" + \"('/tmp/x')\")"
    ) is not None


# ---------------------------------------------------------------------------
# Non‑destructive calls — must NOT be flagged (false‑positive guard)
# ---------------------------------------------------------------------------
def test_print_is_clean() -> None:
    assert code_exec._check_code_destructive('print("hello world")') is None


def test_list_remove_is_clean() -> None:
    """x.remove(1) is list.remove, NOT os.remove — must not flag."""
    assert code_exec._check_code_destructive('x = [1,2,3]; x.remove(1)') is None


def test_dict_pop_is_clean() -> None:
    assert code_exec._check_code_destructive('d = {"a":1}; d.pop("a")') is None


def test_os_getcwd_is_clean() -> None:
    assert code_exec._check_code_destructive('import os; os.getcwd()') is None


def test_shutil_copy_is_clean() -> None:
    assert code_exec._check_code_destructive('shutil.copy("/a", "/b")') is None


def test_eval_arithmetic_is_clean() -> None:
    assert code_exec._check_code_destructive('result = eval("1+1")') is None


def test_exec_arithmetic_is_clean() -> None:
    assert code_exec._check_code_destructive('exec("x = 1")') is None


def test_string_with_remove_in_comment() -> None:
    """A comment mentioning os.remove must not trigger."""
    assert code_exec._check_code_destructive(
        '# This code does NOT call os.remove, it is safe\nprint("ok")'
    ) is None


def test_multiline_destructive() -> None:
    """Multi‑line code with a destructive call on the second line."""
    assert code_exec._check_code_destructive(
        'import os\nos.remove("/tmp/x")'
    ) is not None


# ---------------------------------------------------------------------------
# Sabotage run — prove the regression test fails without the fix
# ---------------------------------------------------------------------------
def test_sabotage_run_fails_without_fix(monkeypatch) -> None:
    """Temporarily restore the old regex‑only behaviour and confirm the test fails.

    This is the sabotage run required by the contribution skill: a regression
    test that passes with AND without the fix proves nothing.
    """
    import re

    def old_check(code: str) -> str | None:
        for pattern, label in code_exec._DESTRUCTIVE_PY_PATTERNS:
            if re.search(pattern, code):
                return f"destructive Python operation detected: {label}"
        return None

    monkeypatch.setattr(code_exec, "_check_code_destructive", old_check)
    # The bypass payloads must NOT be caught by the old regex.
    assert old_check('getattr(os, "rem" + "ove")("/tmp/x")') is None
    assert old_check('__import__("os").remove("/tmp/x")') is None
    assert old_check('eval("os.remove(\'/tmp/x\')")') is None
