"""``{job_id}`` in a cron job's script path.

A job that owns a directory named after itself cannot name that directory at
creation time: the id does not exist until the job does. The placeholder closes
that gap, so one ``add`` replaces the stage-add-move-repoint sequence that left
a live job pointing at a staging path for as long as the sequence took.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentos.scheduler.ops import SchedulerOps
from agentos.scheduler.payloads import (
    make_agent_turn_payload,
    make_script_payload,
    payload_script,
)
from agentos.scheduler.persistence import JobStore
from agentos.scheduler.scripts import (
    JOB_ID_PLACEHOLDER,
    ScriptPathError,
    resolve_script_path,
    substitute_job_id,
    validate_script_path,
)
from agentos.scheduler.types import ScheduleKind, SessionTarget


@pytest.fixture
def agentos_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_STATE_DIR", str(tmp_path))
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    return tmp_path


async def _open_ops(tmp_path: Path) -> tuple[JobStore, SchedulerOps]:
    store = JobStore(str(tmp_path / "cron.db"))
    await store.open()
    return store, SchedulerOps(store)


def test_the_placeholder_is_replaced_with_the_job_id() -> None:
    assert substitute_job_id("unilp/{job_id}/tick.sh", "abc-123") == "unilp/abc-123/tick.sh"


def test_a_path_without_the_placeholder_is_returned_unchanged() -> None:
    assert substitute_job_id("watch.sh", "abc-123") == "watch.sh"


def test_every_occurrence_is_replaced() -> None:
    """A helper directory and the file under it can both name the job."""
    assert substitute_job_id("{job_id}/{job_id}.sh", "j1") == "j1/j1.sh"


@pytest.mark.parametrize("job_id", ["../escape", "a/b", "", "  ", "with space"])
def test_a_job_id_that_could_reshape_the_path_is_refused(job_id: str) -> None:
    """The id becomes a path segment, so only an id-shaped string may land in it.

    Real ids are uuid4, but the substitution is the one place a caller-supplied
    value is spliced into a path, and a backstop there costs nothing.
    """
    with pytest.raises(ScriptPathError):
        substitute_job_id("unilp/{job_id}/tick.sh", job_id)


def test_a_path_holding_the_placeholder_passes_validation(agentos_home) -> None:
    """It has to survive the add-time gate to ever reach substitution."""
    assert validate_script_path("unilp/{job_id}/tick.sh") is None


def test_the_placeholder_cannot_be_used_to_escape_the_scripts_dir(agentos_home) -> None:
    assert validate_script_path("../{job_id}/tick.sh") is not None


def test_an_unresolved_placeholder_never_resolves_to_a_path(agentos_home) -> None:
    """The backstop: a stored path that kept the placeholder must not run.

    Resolving it literally would create a directory called ``{job_id}`` and
    report a missing file, which reads as a typo rather than as the bug it is.
    """
    with pytest.raises(ScriptPathError) as excinfo:
        resolve_script_path(f"unilp/{JOB_ID_PLACEHOLDER}/tick.sh")

    assert "{job_id}" in str(excinfo.value)


async def test_add_resolves_the_placeholder_before_the_job_is_persisted(
    tmp_path: Path, agentos_home
) -> None:
    """No window: what reaches the store already names the job."""
    store, ops = await _open_ops(tmp_path)
    try:
        job = await ops.add(
            name="monitor",
            handler_key="script_run",
            payload=make_script_payload("unilp/{job_id}/tick.sh"),
            session_target=SessionTarget.ISOLATED,
            schedule_kind=ScheduleKind.EVERY,
            schedule_value="600",
        )

        assert payload_script(job.payload) == f"unilp/{job.id}/tick.sh"
        reloaded = await store.get(job.id)
        assert reloaded is not None
        assert payload_script(reloaded.payload) == f"unilp/{job.id}/tick.sh"
    finally:
        await store.close()


async def test_add_resolves_the_placeholder_in_a_pre_run_script(
    tmp_path: Path, agentos_home
) -> None:
    """An agent_turn job's pre-run script takes the same field."""
    store, ops = await _open_ops(tmp_path)
    try:
        job = await ops.add(
            name="briefing",
            handler_key="agent_run",
            payload=make_agent_turn_payload("report it", "main", "unilp/{job_id}/probe.py"),
            session_target=SessionTarget.ISOLATED,
            schedule_kind=ScheduleKind.EVERY,
            schedule_value="600",
        )

        assert payload_script(job.payload) == f"unilp/{job.id}/probe.py"
    finally:
        await store.close()


async def test_update_resolves_the_placeholder_against_the_existing_id(
    tmp_path: Path, agentos_home
) -> None:
    store, ops = await _open_ops(tmp_path)
    try:
        job = await ops.add(
            name="monitor",
            handler_key="script_run",
            payload=make_script_payload("staging/tick.sh"),
            session_target=SessionTarget.ISOLATED,
            schedule_kind=ScheduleKind.EVERY,
            schedule_value="600",
        )

        updated = await ops.update(job.id, payload=make_script_payload("unilp/{job_id}/tick.sh"))

        assert updated is not None
        assert payload_script(updated.payload) == f"unilp/{job.id}/tick.sh"
    finally:
        await store.close()
