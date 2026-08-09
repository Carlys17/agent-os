"""Behavior-neutrality gate for the model-registry refactor (issue #140).

``tests/golden/model_registry_pre_refactor_lookups.json`` was generated from the
tree *before* any registry code existed. It records what every known model id --
plus suffixed probes of it -- resolved to, for both the static price table and
the catalog's window fallbacks.

The suffixed probes are the point. Both tables fail open, and the pricing table
is an ordered ``startswith`` scan, so an exact-id-only snapshot would not notice
a reordering regression: ``glm-5.2-air`` matching ``glm-5`` instead of
``glm-5.2`` is exactly the class of silent wrong number issue #140 is about.

Never regenerate the golden file to make this pass. A diff here is a behavior
change and belongs in a pull request description.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agentos.engine import pricing
from agentos.provider.model_catalog import ModelCatalog

GOLDEN_PATH = (
    Path(__file__).resolve().parents[1] / "golden" / "model_registry_pre_refactor_lookups.json"
)


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _offline_pricing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compare static tables, never a live provider catalog."""
    monkeypatch.setenv("AGENTOS_OPENROUTER_LIVE_PRICING", "0")
    monkeypatch.setenv("AGENTOS_OPENCAP_LIVE_PRICING", "0")


def test_static_price_lookup_is_unchanged_for_every_known_id(golden: dict[str, Any]) -> None:
    expected: dict[str, list[float | None]] = golden["prices"]

    actual = {}
    for model_id in expected:
        entry = pricing._lookup_static_price(model_id)
        actual[model_id] = [entry.input_per_m, entry.output_per_m, entry.cached_input_per_m]

    drifted = {k: (expected[k], actual[k]) for k in expected if expected[k] != actual[k]}
    assert not drifted, f"static price lookup changed for: {sorted(drifted)}"


def test_catalog_windows_are_unchanged_for_every_known_id(golden: dict[str, Any]) -> None:
    """Probed per provider: ``_PROVIDER_STATIC_FALLBACK`` deliberately serves
    different windows for the same bare id on the Bankr/OpenCAP gateways."""
    expected: dict[str, dict[str, list[int]]] = golden["windows"]
    catalog = ModelCatalog()

    drifted: dict[tuple[str, str], tuple[list[int], list[int]]] = {}
    for model_id, per_provider in expected.items():
        for provider, want in per_provider.items():
            got = [
                catalog.resolve_max_tokens(model_id, provider_name=provider),
                catalog.resolve_context_window(model_id, provider_name=provider),
            ]
            if got != want:
                drifted[(model_id, provider)] = (want, got)

    assert not drifted, f"catalog windows changed for: {sorted(drifted)}"
