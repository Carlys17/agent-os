"""Ratchet math — how far a one-sided position has filled, and the price that fills it more.

A one-sided v4 position is a limit order that fills gradually. This module answers the two
questions the ratchet runner needs:

* **How much of the principal is left?** — the runtime source of truth, recomputed from
  ``getSlot0`` every tick.
* **At what price will only ``A`` be left?** — the closed-form inverse, used at ``arm`` time
  to show a human the exact tick each milestone will fire at.

Because the second is a closed form, the ratchet never needs a price history, a sampler, or
a scheduler that remembers anything: one ``getSlot0`` per tick is the whole data requirement.

## The two directions, and why they are named after a currency

In v4, price ``P = currency1 / currency0``. A range entirely **above** the current price
holds 100% ``currency0``; entirely **below**, 100% ``currency1``. Which one is a "limit sell"
depends on whether the token being sold sorted low or high, which the user does not control:

    intent       token is      principal    range vs price   fills as tick
    limit sell   currency0     currency0    above            rises
    limit sell   currency1     currency1    below            falls
    limit buy    currency0     currency1    below            falls
    limit buy    currency1     currency0    above            rises

So "sell" and "buy" are labels, not code paths. Everything here keys off **which currency is
the principal**, which the geometry fixes completely — see :func:`principal_for_range`. That
collapses four user-visible cases into two branches and makes the token0/token1 asymmetry
impossible to get wrong by forgetting a case.
"""

from __future__ import annotations

from .v4_math import (
    Q96,
    get_amounts_for_liquidity_at_ticks,
    get_sqrt_ratio_at_tick,
    get_tick_at_sqrt_ratio,
    pull_off_current_tick,
    range_status,
)

CURRENCY0 = "currency0"
CURRENCY1 = "currency1"


class RangeExhaustedError(RuntimeError):
    """The band between the current price and the far edge cannot hold a range any more.

    Not an error condition for the ratchet: it is exactly how the final milestone announces
    itself. The caller exits the position without re-arming.
    """


# ---------------------------------------------------------------------------
# Which side are we on
# ---------------------------------------------------------------------------


def principal_for_range(tick: int, tick_lower: int, tick_upper: int) -> str:
    """The currency a one-sided range holds, derived from geometry alone.

    Mind the vocabulary clash: ``range_status`` reports where the **current tick** sits
    relative to the range, so ``"below"`` means the tick is below the range — i.e. the range
    is *above* the price — i.e. the principal is ``currency0``. That inversion is the single
    most reliable way to get this backwards, so it is resolved here, once.
    """
    status = range_status(int(tick), int(tick_lower), int(tick_upper))
    if status == "below":
        return CURRENCY0
    if status == "above":
        return CURRENCY1
    raise RuntimeError(
        f"range {tick_lower} → {tick_upper} straddles the current tick {tick}, so it is "
        "two-sided and cannot be ratcheted. Arm a range that is entirely above or entirely "
        "below the current price."
    )


def far_edge_tick(tick_lower: int, tick_upper: int, principal: str) -> int:
    """The end of the range the price is travelling towards — the edge that never moves."""
    return int(tick_upper) if principal == CURRENCY0 else int(tick_lower)


def fills_as_tick_rises(principal: str) -> bool:
    return principal == CURRENCY0


# ---------------------------------------------------------------------------
# Fill progress
# ---------------------------------------------------------------------------


def remaining_principal(
    sqrt_price_x96: int, tick_lower: int, tick_upper: int, liquidity: int, principal: str
) -> int:
    """How much of the principal currency the position still holds at this price.

    Rounds down (``get_amounts_for_liquidity`` default), which is correct here: this is what
    would be RECEIVED, not what must be paid.
    """
    amounts = get_amounts_for_liquidity_at_ticks(
        int(sqrt_price_x96), int(tick_lower), int(tick_upper), int(liquidity)
    )
    return amounts["amount0"] if principal == CURRENCY0 else amounts["amount1"]


def sqrt_price_for_remaining(
    tick_lower: int, tick_upper: int, liquidity: int, target: int, principal: str
) -> int:
    """Inverse of :func:`remaining_principal`: the sqrt price at which ``target`` is left.

    currency0 — ``A = L·Q96·(sb − s)/(s·sb)``  ⟹  ``s = L·Q96·sb / (A·sb + L·Q96)``
    currency1 — ``A = L·(s − sa)/Q96``          ⟹  ``s = sa + A·Q96/L``

    Both are exact rearrangements of ``get_amount{0,1}_delta``. Integer division truncates,
    so the result can sit one wei of sqrt price early; that is irrelevant because triggering
    is decided on the recomputed amount, never on this value. It exists to be shown to a
    human at ``arm`` time.
    """
    sqrt_lower = get_sqrt_ratio_at_tick(int(tick_lower))
    sqrt_upper = get_sqrt_ratio_at_tick(int(tick_upper))
    amount = int(target)
    liq = int(liquidity)
    if liq <= 0:
        raise ValueError("sqrt_price_for_remaining: liquidity must be > 0")
    if amount < 0:
        raise ValueError("sqrt_price_for_remaining: target must be >= 0")

    if principal == CURRENCY0:
        numerator = liq * Q96 * sqrt_upper
        denominator = amount * sqrt_upper + liq * Q96
        result = numerator // denominator
    else:
        result = sqrt_lower + (amount * Q96) // liq
    return min(max(result, sqrt_lower), sqrt_upper)


def tick_for_remaining(
    tick_lower: int, tick_upper: int, liquidity: int, target: int, principal: str
) -> int:
    """:func:`sqrt_price_for_remaining` as a tick, for the ``arm`` approval table."""
    return get_tick_at_sqrt_ratio(
        sqrt_price_for_remaining(tick_lower, tick_upper, liquidity, target, principal)
    )


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------


def parse_steps(raw: str | None) -> list[int]:
    """``"30,60,100"`` -> ``[3000, 6000, 10000]`` basis points, sorted and deduplicated."""
    text = (raw or "30,60,100").strip()
    steps: list[int] = []
    for chunk in text.split(","):
        piece = chunk.strip()
        if not piece:
            continue
        value = float(piece)
        if not 0 < value <= 100:
            raise RuntimeError(f"--steps entries must be in (0, 100], got {piece}")
        bps = int(round(value * 100))
        if bps not in steps:
            steps.append(bps)
    if not steps:
        raise RuntimeError("--steps is empty")
    steps.sort()
    return steps


def milestone_thresholds(original_principal: int, steps_bps: list[int]) -> list[int]:
    """Absolute "principal still held" levels, measured against the ORIGINAL principal.

    100k with steps 30/60/100 gives 70k / 40k / 0 — fixed numbers that do not move when a
    fire re-arms the remainder. Rebasing onto the remainder instead would never converge to
    zero and would need a separate stop condition.
    """
    original = int(original_principal)
    return [original * (10_000 - int(bps)) // 10_000 for bps in steps_bps]


def due_milestone(thresholds: list[int], fired: int, remaining: int) -> int | None:
    """Index of the DEEPEST milestone now due, or ``None``.

    ``fired`` is how many milestones have already gone off, so indices below it are history.
    Returning the deepest — rather than the next — is what stops a price gap that clears two
    levels at once from running two burn/mint cycles back to back. Every level it skipped is
    already satisfied by the same reading, so the caller marks them fired together.
    """
    due: int | None = None
    for index in range(int(fired), len(thresholds)):
        if int(remaining) <= thresholds[index]:
            due = index
    return due


# ---------------------------------------------------------------------------
# Re-arming
# ---------------------------------------------------------------------------


def rearm_range(
    current_tick: int, far_edge: int, tick_spacing: int, principal: str
) -> tuple[int, int]:
    """The range the unconverted remainder is redeployed into: current price → far edge.

    Delegates the edge handling to :func:`pull_off_current_tick` with the side forced, so
    the one-tick asymmetry between the two directions is decided in exactly one place:
    ``currency0`` needs ``current < tickLower`` (strict), ``currency1`` needs
    ``current >= tickUpper`` (not strict).

    Raises :class:`RangeExhaustedError` when the price has reached or passed the far edge, which
    is the final milestone.
    """
    current = int(current_tick)
    edge = int(far_edge)
    spacing = int(tick_spacing)

    if principal == CURRENCY0:
        if current >= edge:
            raise RangeExhaustedError(
                f"price is at tick {current}, at or past the far edge {edge} — the position "
                "is fully converted, nothing left to re-arm"
            )
        band = (current, edge)
    else:
        if edge > current:
            raise RangeExhaustedError(
                f"price is at tick {current}, at or past the far edge {edge} — the position "
                "is fully converted, nothing left to re-arm"
            )
        # pull_off_current_tick only acts on a band that straddles `current`, and for this
        # direction it only ever moves the UPPER edge down to snap_down(current). So
        # `current + 1` is a placeholder that satisfies the straddle test and can never
        # appear in the result.
        band = (edge, current + 1)

    try:
        return pull_off_current_tick(current, band[0], band[1], spacing, principal)
    except RuntimeError as exc:  # no room for one tickSpacing on the side we must use
        raise RangeExhaustedError(str(exc)) from exc
