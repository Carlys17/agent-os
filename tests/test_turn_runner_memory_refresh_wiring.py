"""Tests for _turn_runner_ref population in gateway boot services."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from agentos.gateway.boot import build_turn_runner_from_services


class DummyTurnRunner:
    def __init__(self, **kwargs: Any) -> None:
        self.refreshed_agents: list[str] = []

    def refresh_memory_snapshot(self, agent_id: str) -> None:
        self.refreshed_agents.append(agent_id)


def test_build_turn_runner_from_services_populates_ref(monkeypatch):
    monkeypatch.setattr("agentos.engine.runtime.TurnRunner", DummyTurnRunner)

    ref: list[Any] = []
    svc = SimpleNamespace(
        provider_selector=None,
        tool_registry=None,
        session_manager=None,
        skill_loader=None,
        usage_tracker=None,
        config=SimpleNamespace(),
        _turn_runner_ref=ref,
    )

    def _on_memory_write(agent_id: str) -> None:
        if ref:
            ref[0].refresh_memory_snapshot(agent_id)

    runner = build_turn_runner_from_services(svc)

    assert len(ref) == 1
    assert ref[0] is runner

    _on_memory_write("agent_1")
    assert runner.refreshed_agents == ["agent_1"]
