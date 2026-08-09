"""Engine tests for the translate task-type ceiling.

Every assertion runs through the FULL ``apply_agentos_router`` step, never
``_apply_task_type_ceiling`` directly, so the guard is proven in the position
it actually occupies: after the history guards, before the large-context
floor. The Pilot strategy is injected through the step's ``_get_strategy``
seam with a fixed encoder, so the routed tier depends on the injected argmax
rather than on the message text — which lets each test vary only the thing it
is about.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from agentos.agentos_router.pilot import PilotStrategy
from agentos.agentos_router.pilot.features import EMBED_DIM
from agentos.engine.pipeline import TurnContext
from agentos.engine.steps import agentos_router as agentos_router_step
from agentos.engine.steps.agentos_router import apply_agentos_router
from agentos.gateway.config import GatewayConfig

FIXTURE_DIR = Path(__file__).parent.parent / "test_agentos_router" / "data" / "pilot_fixture"

TRANSLATE_MESSAGE = "Dịch đoạn văn dưới đây sang tiếng Anh giúp tôi."
PLAIN_MESSAGE = "Rà soát lại kiến trúc dịch vụ thanh toán và chỉ ra điểm nghẽn."


class _ProbEncoder:
    """Deterministic ``PilotEncoder`` returning a fixed raw embedding."""

    def __init__(self, vector: np.ndarray) -> None:
        self._vector = vector

    def encode_sync(self, texts: list[str]) -> np.ndarray:
        return np.asarray([self._vector for _ in texts], dtype=np.float32)

    def count_tokens_pretrunc(self, text: str) -> int:
        return len(text.split())


def _seed_vector_for_argmax(target_argmax: int) -> np.ndarray:
    from agentos.agentos_router.pilot.features import build_features
    from agentos.agentos_router.pilot.model import PilotModel

    model = PilotModel(FIXTURE_DIR)
    assert model.available
    for seed in range(400):
        rng = np.random.default_rng(seed)
        vector = rng.standard_normal(EMBED_DIM).astype(np.float32)
        feats = build_features(
            "probe message",
            encoder=_ProbEncoder(vector),
            token_count_pretrunc_8k=3,
        )
        if int(np.argmax(model.predict_proba(feats.reshape(1, -1))[0])) == target_argmax:
            return vector
    raise AssertionError(f"no seed produced argmax {target_argmax}")


@pytest.fixture(autouse=True)
def reset_agentos_router_state(monkeypatch: pytest.MonkeyPatch) -> None:
    agentos_router_step._history_store.clear()
    agentos_router_step._strategy = None
    agentos_router_step._strategy_key = None
    yield
    agentos_router_step._history_store.clear()
    agentos_router_step._strategy = None
    agentos_router_step._strategy_key = None
    monkeypatch.undo()


def _make_context(message: str, *, session_key: str = "task-type-session") -> TurnContext:
    config = GatewayConfig()
    config.agentos_router.rollout_phase = "full"
    # Keep the confidence gate inert so the injected c2 route reaches the
    # ceiling unmodified; the gate has its own coverage elsewhere.
    config.agentos_router.confidence_threshold = 0.0
    return TurnContext(
        message=message,
        session_key=session_key,
        config=config,
        provider=None,
        model=config.llm.model,
        tool_defs=[],
        system_prompt="system",
    )


def _inject_pilot(monkeypatch: pytest.MonkeyPatch, *, argmax: int = 2) -> PilotStrategy:
    strategy = PilotStrategy(
        artifact_dir=FIXTURE_DIR,
        encoder=_ProbEncoder(_seed_vector_for_argmax(argmax)),
        safety_net_threshold=1.0,
        confidence_threshold=0.0,
    )
    monkeypatch.setattr(
        agentos_router_step, "_get_strategy", lambda _config, _llm_cfg=None: strategy
    )
    return strategy


@pytest.mark.asyncio
async def test_translate_turn_is_capped_to_the_ceiling_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A c2 route for a translation request is capped to c0."""
    _inject_pilot(monkeypatch)
    ctx = _make_context(TRANSLATE_MESSAGE)

    routed = await apply_agentos_router(ctx)
    extra = routed.metadata["routing_extra"]

    assert routed.metadata["routed_tier"] == "c0"
    assert routed.metadata["routing_source"] == "task_type_ceiling"
    assert extra["task_type"] == "translate"
    assert extra["task_type_language"] == "vi"
    assert extra["task_type_ceiling_applied"] is True
    assert extra["task_type_ceiling_from_tier"] == "c2"
    assert extra["final_tier"] == "c0"
    assert extra["final_route_class"] == "R0"
    # The classifier's own opinion stays visible next to the override.
    assert extra["base_tier"] == "c2"
    assert extra["route_class"] == "R2"


@pytest.mark.asyncio
async def test_non_translate_turn_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """An overloaded Vietnamese verb ('dịch vụ') must not trigger the cap."""
    _inject_pilot(monkeypatch)
    ctx = _make_context(PLAIN_MESSAGE)

    routed = await apply_agentos_router(ctx)
    extra = routed.metadata["routing_extra"]

    assert routed.metadata["routed_tier"] == "c2"
    assert routed.metadata["routing_source"] == "pilot_v1"
    assert "task_type_ceiling_applied" not in extra


@pytest.mark.asyncio
async def test_code_port_is_recorded_without_capping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A port phrased as a translation keeps its tier and says why."""
    _inject_pilot(monkeypatch)
    ctx = _make_context("Dịch đoạn code này sang Rust giúp tôi.")

    routed = await apply_agentos_router(ctx)
    extra = routed.metadata["routing_extra"]

    assert routed.metadata["routed_tier"] == "c2"
    assert extra["task_type_blocked_by"] == "programming_language_target"
    assert "task_type_ceiling_applied" not in extra


@pytest.mark.asyncio
async def test_translation_asking_for_commentary_is_still_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Policy: translation as such is capped, extras and all."""
    _inject_pilot(monkeypatch)
    ctx = _make_context("Dịch đoạn này sang tiếng Anh và phân tích giọng văn.")

    routed = await apply_agentos_router(ctx)

    assert routed.metadata["routed_tier"] == "c0"
    assert routed.metadata["routing_extra"]["task_type_ceiling_applied"] is True


@pytest.mark.asyncio
async def test_complaint_upgrade_wins_over_the_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asking for a better answer must not be capped in the same turn."""
    _inject_pilot(monkeypatch)
    ctx = _make_context("Sai rồi, dịch lại câu này sang tiếng Anh giúp tôi.")

    routed = await apply_agentos_router(ctx)
    extra = routed.metadata["routing_extra"]

    assert extra["complaint_upgrade_applied"] is True
    assert routed.metadata["routed_tier"] == "c3"
    assert "task_type_ceiling_applied" not in extra


@pytest.mark.asyncio
async def test_large_context_floor_wins_over_the_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A document too large for the cheap tier is floored back up after the cap."""
    _inject_pilot(monkeypatch)
    body = "word " * 30_000  # ~150k chars -> ~37k estimated tokens, over the c2 floor
    ctx = _make_context(f"Dịch tài liệu sau sang tiếng Việt:\n\n{body}")

    routed = await apply_agentos_router(ctx)
    extra = routed.metadata["routing_extra"]

    assert routed.metadata["routed_tier"] == "c2"
    assert routed.metadata["routing_source"] == "large_context_floor"
    # The cap did fire first; the floor then lifted it back.
    assert extra["task_type_ceiling_applied"] is True
    assert extra["large_context_floor_applied"] is True
    assert extra["large_context_floor_from_tier"] == "c0"
    assert extra["final_tier"] == "c2"


@pytest.mark.asyncio
async def test_ceiling_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _inject_pilot(monkeypatch)
    ctx = _make_context(TRANSLATE_MESSAGE)
    ctx.config.agentos_router.translate_ceiling_enabled = False

    routed = await apply_agentos_router(ctx)

    assert routed.metadata["routed_tier"] == "c2"
    assert "task_type_ceiling_applied" not in routed.metadata["routing_extra"]


@pytest.mark.asyncio
async def test_ceiling_tier_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    _inject_pilot(monkeypatch)
    ctx = _make_context(TRANSLATE_MESSAGE)
    ctx.config.agentos_router.translate_ceiling_tier = "c1"

    routed = await apply_agentos_router(ctx)
    extra = routed.metadata["routing_extra"]

    assert routed.metadata["routed_tier"] == "c1"
    assert extra["task_type_ceiling_tier"] == "c1"


@pytest.mark.asyncio
@pytest.mark.parametrize("ceiling", ["c2", "c3"])
async def test_route_at_or_below_the_ceiling_is_untouched(
    monkeypatch: pytest.MonkeyPatch, ceiling: str
) -> None:
    """The guard is a ceiling, never a floor: it must not lift a cheaper route.

    ``c2`` exercises the equality case and ``c3`` the strictly-below case, both
    against the same injected c2 route.
    """
    _inject_pilot(monkeypatch)
    ctx = _make_context(TRANSLATE_MESSAGE)
    ctx.config.agentos_router.translate_ceiling_tier = ceiling

    routed = await apply_agentos_router(ctx)

    assert routed.metadata["routed_tier"] == "c2"
    assert routed.metadata["routing_source"] == "pilot_v1"
    assert "task_type_ceiling_applied" not in routed.metadata["routing_extra"]


def test_ceiling_tier_rejects_an_unknown_value() -> None:
    config = GatewayConfig()
    with pytest.raises(ValueError, match="translate_ceiling_tier"):
        config.agentos_router.__class__(translate_ceiling_tier="c9")


def test_ceiling_tier_accepts_the_legacy_alias() -> None:
    cfg = GatewayConfig().agentos_router.__class__(translate_ceiling_tier="t0")
    assert cfg.translate_ceiling_tier == "c0"
