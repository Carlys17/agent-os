"""`MemoryManager.degraded` must not grow once per failed metric.

`status()` records up to five degradations per call and serializes the whole
list into its response. Under a health poller against a broken store that
means the list -- and every status payload -- grows without bound, and the
operator ends up reading thousands of copies of one error instead of "this
component is down".
"""

from __future__ import annotations

from agentos.memory.manager import MemoryDegradation, MemoryManager


def _manager() -> MemoryManager:
    """A manager with only the fields the degradation path touches."""
    manager = object.__new__(MemoryManager)
    object.__setattr__(manager, "agent_id", "main")
    object.__setattr__(manager, "degraded", [])
    return manager


def _record(
    manager: MemoryManager, *, component="store", operation="file_count", error="db locked"
):
    manager._record_degradation(component=component, operation=operation, error=RuntimeError(error))


def test_a_single_failure_is_recorded():
    m = _manager()
    _record(m)
    assert len(m.degraded) == 1
    assert m.degraded[0].as_dict() == {
        "component": "store",
        "operation": "file_count",
        "error": "db locked",
    }


def test_repeats_collapse_instead_of_appending():
    """The regression this file exists for."""
    m = _manager()
    for _ in range(500):
        _record(m)
    assert len(m.degraded) == 1


def test_a_repeat_reports_how_many_times_it_happened():
    """Collapsing must not hide that the failure is ongoing."""
    m = _manager()
    for _ in range(7):
        _record(m)
    assert m.degraded[0].as_dict()["count"] == 7


def test_a_one_off_failure_carries_no_count():
    """Unchanged shape for the common case, so existing readers still work."""
    m = _manager()
    _record(m)
    assert "count" not in m.degraded[0].as_dict()


def test_distinct_failures_stay_distinct():
    """Collapsing must not merge unrelated problems into one entry."""
    m = _manager()
    _record(m, component="store", operation="file_count")
    _record(m, component="store", operation="chunk_count")
    _record(m, component="curated", operation="status")
    assert len(m.degraded) == 3


def test_the_same_operation_failing_differently_stays_distinct():
    """A changed error message is new information, not a repeat."""
    m = _manager()
    _record(m, error="db locked")
    _record(m, error="disk full")
    assert len(m.degraded) == 2


def test_a_full_status_poll_cycle_stays_bounded():
    """Five metrics per poll is the real shape of the growth."""
    m = _manager()
    metrics = [
        ("store", "file_count"),
        ("store", "chunk_count"),
        ("store", "total_size"),
        ("store", "source_counts"),
        ("curated", "status"),
    ]
    for _ in range(2880):  # a day of 30s polls
        for component, operation in metrics:
            _record(m, component=component, operation=operation)

    assert len(m.degraded) == len(metrics)
    assert all(d.as_dict()["count"] == 2880 for d in m.degraded)


def test_degradation_equality_ignores_nothing_unexpected():
    """count participates in the dataclass, so replace() produces a new value."""
    a = MemoryDegradation(component="store", operation="x", error="e")
    assert a.count == 1
    assert a.as_dict() == {"component": "store", "operation": "x", "error": "e"}
