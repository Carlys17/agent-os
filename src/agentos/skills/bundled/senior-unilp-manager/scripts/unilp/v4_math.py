"""Exact integer TickMath and LiquidityAmounts for Uniswap V3/V4, plus mcap conversion.

Port of ``v4-math.mjs``. Everything in the value path is exact integer arithmetic;
floats appear only in the display helpers at the bottom and never feed back into an
amount that gets signed.

Python's arbitrary-precision ``int`` is a direct stand-in for JS ``BigInt``, with one
caveat that matters: ``BigInt`` division truncates toward zero while Python ``//``
floors. Every division here goes through :func:`~unilp.hexutil.div_trunc` even where
both operands are provably non-negative, so the behaviour cannot drift if a caller
later passes a negative.
"""

from __future__ import annotations

import math

from .hexutil import div_trunc, js_round

Q96 = 1 << 96
Q128 = 1 << 128
MAX_UINT256 = (1 << 256) - 1

MIN_TICK = -887272
MAX_TICK = 887272
MIN_SQRT_RATIO = 4295128739
MAX_SQRT_RATIO = 1461446703485210103287273052203988822378723970342

# Magic constants for bits 0x2 .. 0x80000; bit 0x1 is the seed inside the function.
_RATIO_CONSTANTS = (
    0xFFF97272373D413259A46990580E213A,
    0xFFF2E50F5F656932EF12357CF3C7FDCC,
    0xFFE5CACA7E10E4E61C3624EAA0941CD0,
    0xFFCB9843D60F6159C9DB58835C926644,
    0xFF973B41FA98C081472E6896DFB254C0,
    0xFF2EA16466C96A3843EC78B326B52861,
    0xFE5DEE046A99A2A811C461F1969C3053,
    0xFCBE86C7900A88AEDCFFC83B479AA3A4,
    0xF987A7253AC413176F2B074CF7815E54,
    0xF3392B0822B70005940C7A398E4B70F3,
    0xE7159475A2C29B7443B29C7FA6E889D9,
    0xD097F3BDFD2022B8845AD8F792AA5825,
    0xA9F746462D870FDF8A65DC1F90E061E5,
    0x70D869A156D2A1B890BB3DF62BAF32F7,
    0x31BE135F97D08FD981231505542FCFA6,
    0x9AA508B5B7A84E1C677DE54F3E99BC9,
    0x5D6AF8DEDB81196699C329225EE604,
    0x2216E584F5FA1EA926041BEDFE98,
    0x48A170391F7DC42444E8FA2,
)


def get_sqrt_ratio_at_tick(tick: int) -> int:
    """``sqrt(1.0001**tick) * 2**96``, exact. Port of Uniswap ``TickMath``."""
    t = int(tick)
    if t != tick:
        raise ValueError(f"tick must be an integer, got {tick!r}")
    if t < MIN_TICK or t > MAX_TICK:
        raise ValueError(f"tick {t} out of range")

    magnitude = -t if t < 0 else t
    ratio = 0xFFFCB933BD6FAD37AA2D162D1A594001 if magnitude & 0x1 else 1 << 128
    for i, constant in enumerate(_RATIO_CONSTANTS):
        if magnitude & (0x2 << i):
            # Solidity's mul wraps; mask to keep this in lockstep with uint256.
            ratio = ((ratio * constant) & MAX_UINT256) >> 128
    if t > 0:
        ratio = div_trunc(MAX_UINT256, ratio)

    # X128 -> X96, rounding up, matching the reference implementation.
    return (ratio >> 32) + (0 if (ratio & 0xFFFFFFFF) == 0 else 1)


def get_tick_at_sqrt_ratio(sqrt_price_x96: int) -> int:
    """Largest tick whose sqrt ratio is <= ``sqrt_price_x96``.

    A binary search over the forward function rather than a port of the log2/msb
    constant table: it inverts something already trusted, so it is exact by
    construction and introduces no second set of magic numbers. 21 iterations.
    """
    target = int(sqrt_price_x96)
    if target < MIN_SQRT_RATIO or target > MAX_SQRT_RATIO:
        raise ValueError(f"sqrtPriceX96 {target} out of range")
    low, high = MIN_TICK, MAX_TICK
    while low < high:
        # Ceiling division; +1 before floor-dividing is correct for negatives too.
        mid = (low + high + 1) // 2
        if get_sqrt_ratio_at_tick(mid) <= target:
            low = mid
        else:
            high = mid - 1
    return low


# ---------------------------------------------------------------------------
# mulDiv helpers with explicit rounding
# ---------------------------------------------------------------------------

def _mul_div(a: int, b: int, denominator: int) -> int:
    if denominator == 0:
        raise ZeroDivisionError("mulDiv: division by zero")
    return div_trunc(a * b, denominator)


def _mul_div_rounding_up(a: int, b: int, denominator: int) -> int:
    if denominator == 0:
        raise ZeroDivisionError("mulDiv: division by zero")
    product = a * b
    quotient = div_trunc(product, denominator)
    return quotient if product - quotient * denominator == 0 else quotient + 1


def _div_rounding_up(a: int, denominator: int) -> int:
    quotient = div_trunc(a, denominator)
    return quotient if a - quotient * denominator == 0 else quotient + 1


def _sort_sqrt(a: int, b: int) -> tuple[int, int]:
    return (b, a) if a > b else (a, b)


# ---------------------------------------------------------------------------
# LiquidityAmounts
# ---------------------------------------------------------------------------

def get_amount0_delta(sqrt_a: int, sqrt_b: int, liquidity: int, round_up: bool = False) -> int:
    lower, upper = _sort_sqrt(int(sqrt_a), int(sqrt_b))
    if lower <= 0:
        raise ValueError("get_amount0_delta: sqrt price must be > 0")
    numerator1 = int(liquidity) << 96
    numerator2 = upper - lower
    if round_up:
        return _div_rounding_up(_mul_div_rounding_up(numerator1, numerator2, upper), lower)
    return div_trunc(_mul_div(numerator1, numerator2, upper), lower)


def get_amount1_delta(sqrt_a: int, sqrt_b: int, liquidity: int, round_up: bool = False) -> int:
    lower, upper = _sort_sqrt(int(sqrt_a), int(sqrt_b))
    if round_up:
        return _mul_div_rounding_up(int(liquidity), upper - lower, Q96)
    return _mul_div(int(liquidity), upper - lower, Q96)


def get_liquidity_for_amount0(sqrt_a: int, sqrt_b: int, amount0: int) -> int:
    lower, upper = _sort_sqrt(int(sqrt_a), int(sqrt_b))
    intermediate = _mul_div(lower, upper, Q96)
    return _mul_div(int(amount0), intermediate, upper - lower)


def get_liquidity_for_amount1(sqrt_a: int, sqrt_b: int, amount1: int) -> int:
    lower, upper = _sort_sqrt(int(sqrt_a), int(sqrt_b))
    return _mul_div(int(amount1), Q96, upper - lower)


def get_liquidity_for_amounts(
    sqrt_p: int, sqrt_a: int, sqrt_b: int, amount0: int, amount1: int
) -> int:
    """Liquidity obtainable from both amounts at the current price — binding side wins."""
    price = int(sqrt_p)
    lower, upper = _sort_sqrt(int(sqrt_a), int(sqrt_b))
    if price <= lower:
        return get_liquidity_for_amount0(lower, upper, amount0)
    if price < upper:
        return min(
            get_liquidity_for_amount0(price, upper, amount0),
            get_liquidity_for_amount1(lower, price, amount1),
        )
    return get_liquidity_for_amount1(lower, upper, amount1)


def get_amounts_for_liquidity(
    sqrt_p: int, sqrt_a: int, sqrt_b: int, liquidity: int, round_up: bool = False
) -> dict:
    """Token amounts a position of ``liquidity`` holds at ``sqrt_p``.

    ``round_up=True`` is what you want when computing what must be PAID (mint,
    increase); ``False`` when computing what a position currently holds or what
    will be RECEIVED.
    """
    price = int(sqrt_p)
    lower, upper = _sort_sqrt(int(sqrt_a), int(sqrt_b))
    amount = int(liquidity)
    if amount == 0:
        return {"amount0": 0, "amount1": 0}
    if price <= lower:
        return {"amount0": get_amount0_delta(lower, upper, amount, round_up), "amount1": 0}
    if price < upper:
        return {
            "amount0": get_amount0_delta(price, upper, amount, round_up),
            "amount1": get_amount1_delta(lower, price, amount, round_up),
        }
    return {"amount0": 0, "amount1": get_amount1_delta(lower, upper, amount, round_up)}


def get_amounts_for_liquidity_at_ticks(
    sqrt_p: int, tick_lower: int, tick_upper: int, liquidity: int, round_up: bool = False
) -> dict:
    return get_amounts_for_liquidity(
        sqrt_p,
        get_sqrt_ratio_at_tick(tick_lower),
        get_sqrt_ratio_at_tick(tick_upper),
        liquidity,
        round_up,
    )


def range_status(tick: int, tick_lower: int, tick_upper: int) -> str:
    if tick < tick_lower:
        return "below"
    if tick >= tick_upper:
        return "above"
    return "in-range"


# ---------------------------------------------------------------------------
# Tick spacing
# ---------------------------------------------------------------------------

def min_usable_tick(tick_spacing: int) -> int:
    return math.ceil(MIN_TICK / int(tick_spacing)) * int(tick_spacing)


def max_usable_tick(tick_spacing: int) -> int:
    return math.floor(MAX_TICK / int(tick_spacing)) * int(tick_spacing)


def snap_tick(tick: int, tick_spacing: int, mode: str = "nearest") -> int:
    """Snap a tick onto the pool's spacing, clamped to the usable range.

    ``mode='nearest'`` uses JS ``Math.round`` semantics, not Python's banker's
    rounding — otherwise a tick exactly halfway between two spacings snaps the
    wrong way.
    """
    spacing = int(tick_spacing)
    value = int(tick)
    if mode == "down":
        snapped = math.floor(value / spacing) * spacing
    elif mode == "up":
        snapped = math.ceil(value / spacing) * spacing
    else:
        snapped = js_round(value / spacing) * spacing
    return min(max(snapped, min_usable_tick(spacing)), max_usable_tick(spacing))


def pull_off_current_tick(
    current: int, tick_lower: int, tick_upper: int, spacing: int,
    force_principal: str | None = None,
) -> tuple[int, int]:
    """Move a range that straddles ``current`` fully onto one side of it.

    A band with one end at "where it trades right now" is the normal way to ask for a
    single-sided add, but snapping outward pushes that end across the current tick and the
    range comes back two-sided — the caller then has to guess a tick by hand. Keep whichever
    side holds more of the band they asked for and pull the near edge past ``current``.

    A range is single-sided below the current price when ``tickUpper <= current``, and above
    it when ``tickLower > current``; that is the same boundary ``range_status`` uses.

    ``force_principal`` names the currency the resulting range must take, and is how the
    ratchet asks for a specific side instead of the "bigger half" heuristic:

    * ``"currency0"`` — the range must sit entirely ABOVE the current price. Note this edge
      is **strict** (``range_status`` needs ``current < tickLower``), which is why the near
      edge is ``snap_down(current) + spacing`` and never ``current`` itself.
    * ``"currency1"`` — entirely BELOW. That edge is **non-strict** (``current >=
      tickUpper``), so landing exactly on ``current`` is fine.

    Naming the side by its currency rather than by "above"/"below" is deliberate: this
    module already uses "below" for *the current tick relative to the range*, which is the
    opposite of "the range below the price", and mixing the two is how the sell/buy
    directions get silently swapped.

    Raises when the side that was asked for cannot hold a range at least one spacing wide.
    A forced side never falls back to the other one — for the ratchet that situation means
    "this is the final milestone", and quietly flipping sides would re-arm backwards.
    """
    if force_principal not in (None, "currency0", "currency1"):
        raise ValueError(f'force_principal must be "currency0", "currency1" or None, '
                         f"got {force_principal!r}")
    if not (tick_lower <= current < tick_upper):
        return tick_lower, tick_upper  # already one-sided, leave it alone

    below = snap_tick(current, spacing, "down")
    above = below + spacing

    if force_principal == "currency0":
        if above < tick_upper:
            return above, tick_upper
        raise RuntimeError(
            f"no room for a currency0-only range above the current tick {current}: the band "
            f"ends at {tick_upper}, less than one tickSpacing ({spacing}) away"
        )
    if force_principal == "currency1":
        if below > tick_lower:
            return tick_lower, below
        raise RuntimeError(
            f"no room for a currency1-only range below the current tick {current}: the band "
            f"starts at {tick_lower}, less than one tickSpacing ({spacing}) away"
        )

    keep_below = (current - tick_lower) >= (tick_upper - current)
    if keep_below and below > tick_lower:
        return tick_lower, below
    if not keep_below and above < tick_upper:
        return above, tick_upper
    # The band is thinner than one spacing on the side we wanted, so that side cannot hold a
    # range at all. Fall back to the other one rather than returning a straddle.
    if below > tick_lower:
        return tick_lower, below
    if above < tick_upper:
        return above, tick_upper
    raise RuntimeError(
        f"the band is narrower than one tickSpacing ({spacing}) either side of the current "
        f"tick {current} — widen it, or give --tick-lower/--tick-upper directly"
    )


# ---------------------------------------------------------------------------
# Price / market cap — the display path, floats allowed from here down
# ---------------------------------------------------------------------------

def raw_price_at_tick(tick: int) -> float:
    """Units of currency1 per unit of currency0, both undecimalled.

    Uses the exact sqrt ratio then squares in float. The result is only displayed
    or turned into a USD figure; it never becomes an amount that gets signed.
    """
    ratio = get_sqrt_ratio_at_tick(tick) / Q96
    return ratio * ratio


def token_price_in_quote_at_tick(
    tick: int, token_is_currency1: bool, decimals0: int, decimals1: int
) -> float:
    """Price of the token in the pool's other currency, decimals-adjusted."""
    raw = raw_price_at_tick(tick)
    if token_is_currency1:
        return (1 / raw) * 10 ** (int(decimals1) - int(decimals0))
    return raw * 10 ** (int(decimals0) - int(decimals1))


def mcap_at_tick(
    tick: int,
    token_is_currency1: bool,
    decimals0: int,
    decimals1: int,
    total_supply: int,
    token_decimals: int,
    quote_usd: float | None,
) -> float | None:
    """Fully diluted market cap of the token at ``tick``; ``None`` if no quote price."""
    if quote_usd is None:
        return None
    price = token_price_in_quote_at_tick(tick, token_is_currency1, decimals0, decimals1)
    supply = int(total_supply) / 10 ** int(token_decimals)
    return supply * price * float(quote_usd)


def mcap_band_for_range(
    tick_lower: int,
    tick_upper: int,
    token_is_currency1: bool,
    decimals0: int,
    decimals1: int,
    total_supply: int,
    token_decimals: int,
    quote_usd: float | None,
    tick_spacing: int = 1,
) -> dict:
    """The market-cap band a position spans, ascending.

    A higher tick means a higher currency1-per-currency0 price, i.e. currency1 is
    *cheaper*. So when the token is currency1 the band is inverted relative to tick
    order. That inversion is derived from ``token_is_currency1``, never hardcoded —
    getting it backwards silently reports a range at the wrong end of the curve.

    Either bound may be ``None`` (quote price unknown) or ``inf`` (the tick sits at
    the edge of the usable range).
    """
    at_min = tick_lower <= min_usable_tick(tick_spacing)
    at_max = tick_upper >= max_usable_tick(tick_spacing)
    args = (token_is_currency1, decimals0, decimals1, total_supply, token_decimals, quote_usd)
    lower_mcap = mcap_at_tick(tick_lower, *args)
    upper_mcap = mcap_at_tick(tick_upper, *args)

    if token_is_currency1:
        return {
            "from": 0 if at_max else upper_mcap,
            "to": math.inf if at_min else lower_mcap,
        }
    return {
        "from": 0 if at_min else lower_mcap,
        "to": math.inf if at_max else upper_mcap,
    }


def tick_at_price(price_1_per_0: float, decimals0: int, decimals1: int) -> int:
    """The tick at which one whole currency0 costs ``price_1_per_0`` whole currency1.

    Inverse of ``token_price_in_quote_at_tick(tick, False, ...)``. Only used to turn a
    human-typed ``--price`` into a candidate tick, which the caller then snaps to the
    pool's tickSpacing and shows back before anything is signed — the exact
    :func:`get_sqrt_ratio_at_tick` of that snapped tick is what reaches the calldata,
    so this float never lands in a transaction.
    """
    price = float(price_1_per_0)
    if not price > 0:
        raise ValueError("tick_at_price: price must be positive")
    raw = price * 10 ** (int(decimals1) - int(decimals0))
    tick = math.log(raw) / math.log(1.0001)
    if not math.isfinite(tick):
        raise ValueError(f"tick_at_price: non-finite tick for price {price_1_per_0}")
    if tick < MIN_TICK or tick > MAX_TICK:
        raise ValueError(
            f"tick_at_price: price {price_1_per_0} is outside the representable range "
            f"(tick {js_round(tick)}, limits {MIN_TICK}..{MAX_TICK})"
        )
    return js_round(tick)


def tick_at_mcap(
    mcap_usd: float,
    token_is_currency1: bool,
    decimals0: int,
    decimals1: int,
    total_supply: int,
    token_decimals: int,
    quote_usd: float | None,
) -> int:
    """Inverse of :func:`mcap_at_tick`: the tick at which the token has that mcap."""
    if quote_usd is None or not mcap_usd > 0:
        raise ValueError("tick_at_mcap: need a positive mcap and a quote price")
    supply = int(total_supply) / 10 ** int(token_decimals)
    price_in_quote = float(mcap_usd) / supply / float(quote_usd)

    if token_is_currency1:
        raw = 1 / (price_in_quote / 10 ** (int(decimals1) - int(decimals0)))
    else:
        raw = price_in_quote / 10 ** (int(decimals0) - int(decimals1))
    tick = math.log(raw) / math.log(1.0001)
    if not math.isfinite(tick):
        raise ValueError(f"tick_at_mcap: non-finite tick for mcap {mcap_usd}")
    return max(MIN_TICK, min(MAX_TICK, js_round(tick)))
