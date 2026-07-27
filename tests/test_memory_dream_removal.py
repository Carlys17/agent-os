"""Removing Dream must not break installs that were using it.

Two things outlive the code: the `[memory.dream]` block in a user's
agentos.toml, and `memory_dream:*` rows in the scheduler database. `MemoryConfig`
forbids extra keys, so the first would fail validation at boot; the second would
fire forever against a handler that no longer exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentos.gateway.boot import _pause_orphaned_dream_crons
from agentos.gateway.config import GatewayConfig

# -- config -------------------------------------------------------------------


def test_an_existing_config_with_a_dream_block_still_loads(tmp_path: Path):
    """The decisive case: MemoryConfig forbids extras, so this would 500 at boot."""
    config_path = tmp_path / "agentos.toml"
    config_path.write_text(
        "[memory]\n"
        "inject_limit = 6400\n"
        "\n"
        "[memory.dream]\n"
        "enabled = true\n"
        "interval_h = 12\n"
        "preview_mode = false\n",
        encoding="utf-8",
    )

    config = GatewayConfig.load(config_path)

    assert config.memory.inject_limit == 6400
    assert not hasattr(config.memory, "dream")


def test_the_dropped_block_is_reported_not_silently_eaten():
    from agentos.gateway.config_migration import DEPRECATED_MEMORY_FIELDS

    assert "memory.dream" in DEPRECATED_MEMORY_FIELDS


def test_a_config_without_dream_is_unaffected(tmp_path: Path):
    config_path = tmp_path / "agentos.toml"
    config_path.write_text("[memory]\ninject_limit = 5000\n", encoding="utf-8")

    assert GatewayConfig.load(config_path).memory.inject_limit == 5000


def test_the_fingerprint_no_longer_carries_dream_keys():
    fingerprint = GatewayConfig().memory_mode_fingerprint()
    assert not [key for key in fingerprint if "dream" in key]


# -- scheduler ----------------------------------------------------------------


class _Job:
    def __init__(self, job_id: str, name: str, status: str = "active") -> None:
        self.id = job_id
        self.name = name
        self.status = status


class _Scheduler:
    def __init__(self, jobs: list[_Job]) -> None:
        self._jobs = jobs
        self.paused: list[str] = []

    async def list_jobs(self) -> list[_Job]:
        return self._jobs

    async def pause_job(self, job_id: str) -> None:
        self.paused.append(job_id)


async def test_leftover_dream_crons_are_paused():
    """Without this they keep firing against a handler that no longer exists."""
    scheduler = _Scheduler(
        [
            _Job("1", "memory_dream:main"),
            _Job("2", "memory_dream:ops"),
        ]
    )

    await _pause_orphaned_dream_crons(scheduler=scheduler, agent_ids=["main", "ops"])

    assert sorted(scheduler.paused) == ["1", "2"]


async def test_unrelated_crons_are_left_alone():
    """Pausing must not reach beyond the jobs Dream owned."""
    scheduler = _Scheduler(
        [
            _Job("1", "memory_dream:main"),
            _Job("2", "agent_run:nightly"),
            _Job("3", "static_message:standup"),
        ]
    )

    await _pause_orphaned_dream_crons(scheduler=scheduler, agent_ids=["main"])

    assert scheduler.paused == ["1"]


async def test_already_paused_jobs_are_not_touched_again():
    scheduler = _Scheduler([_Job("1", "memory_dream:main", status="paused")])

    await _pause_orphaned_dream_crons(scheduler=scheduler, agent_ids=["main"])

    assert scheduler.paused == []


async def test_a_scheduler_without_dream_jobs_is_a_no_op():
    scheduler = _Scheduler([_Job("1", "agent_run:nightly")])

    await _pause_orphaned_dream_crons(scheduler=scheduler, agent_ids=["main"])

    assert scheduler.paused == []


async def test_a_failing_scheduler_does_not_break_boot():
    """Cleanup is best-effort: boot must not die because a pause failed."""

    class _Broken(_Scheduler):
        async def pause_job(self, job_id: str) -> None:
            raise RuntimeError("scheduler unavailable")

    scheduler = _Broken([_Job("1", "memory_dream:main")])

    await _pause_orphaned_dream_crons(scheduler=scheduler, agent_ids=["main"])


# -- the code is actually gone ------------------------------------------------


@pytest.mark.parametrize(
    "module",
    [
        "agentos.memory.dream",
        "agentos.memory.dream_factory",
        "agentos.scheduler.dream_handler",
        "agentos.memory.flush_status",
    ],
)
def test_removed_modules_are_gone(module: str):
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_the_memory_package_still_imports():
    """The removals must not have taken a live export with them."""
    import agentos.memory  # noqa: F401
    import agentos.memory.manager  # noqa: F401
    import agentos.memory.retention  # noqa: F401  -- live, used by sync_manager
