"""Tests for the destructive-intent approval cache.

The cache short-circuits the human approval prompt for paraphrased retries of
a previously-approved intent. It MUST NOT let a compound command smuggle an
extra destructive target past an approval for a different target.
"""
from __future__ import annotations

from agentos.application.intent_cache import IntentApprovalCache


def test_compound_command_with_second_rm_is_not_cached() -> None:
    cache = IntentApprovalCache()
    cache.record("rm /data/project-a/tmp-cache")
    assert cache.check("rm /data/project-a/tmp-cache")
    # A second rm smuggled in via a shell separator must not pass.
    for sep in (";", "&&", "||", "|", "&", "\n"):
        cmd = f"rm /data/project-a/tmp-cache{sep}rm -rf /data/project-b"
        assert not cache.check(cmd), f"compound rm via {sep!r} slipped past the cache"


def test_compound_command_requires_approval_of_every_target() -> None:
    cache = IntentApprovalCache()
    cache.record("rm /a /b")
    # Both targets approved -> ok.
    assert cache.check("rm /a /b")
    # Adding a third target -> must re-prompt.
    assert not cache.check("rm /a /b /c")


def test_paraphrased_python_delete_still_cached() -> None:
    cache = IntentApprovalCache()
    cache.record("rm /data/project-a/tmp-cache")
    # The cache is designed to allow os.remove() paraphrases.
    assert cache.check('os.remove("/data/project-a/tmp-cache")')


def test_unrelated_delete_not_cached() -> None:
    cache = IntentApprovalCache()
    cache.record("rm /data/project-a/tmp-cache")
    assert not cache.check("rm -rf /data/project-b")
