"""Uniswap V4 pool primitives — port of ``v4-pool.mjs``.

poolId derivation, PoolKey/PositionInfo codecs, log scans, reserve aggregation,
and hook permission decoding.
"""

from __future__ import annotations

from typing import Any

from .abi_codec import decode_event_log, encode
from .abi_defs import (
    POOL_KEY_COMPONENTS,
    POOL_MANAGER_EVENTS_ABI,
    STATE_VIEW_ABI,
    TOPIC_INITIALIZE,
    TOPIC_MODIFY_LIQUIDITY,
)
from .hexutil import as_int_n, as_uint_n, checksum_address, pad, to_hex
from .keccak import keccak256
from .v4_math import (
    get_amounts_for_liquidity_at_ticks,
    max_usable_tick,
    min_usable_tick,
    range_status,
)

NATIVE = "0x0000000000000000000000000000000000000000"
DYNAMIC_FEE_FLAG = 0x800000

# ---------------------------------------------------------------------------
# PoolKey / poolId
# ---------------------------------------------------------------------------


def compute_pool_id(pool_key: dict) -> str:
    """poolId = keccak256(abi.encode(currency0, currency1, fee, tickSpacing, hooks))

    ``fee`` must be the value from the Initialize event / getPoolAndPositionInfo — for
    a dynamic-fee pool that is 0x800000, NOT the live lpFee from slot0. Using the live
    fee produces a valid-looking id for a pool that does not exist.
    """
    return keccak256(
        encode(
            POOL_KEY_COMPONENTS,
            [
                checksum_address(pool_key["currency0"]),
                checksum_address(pool_key["currency1"]),
                int(pool_key["fee"]),
                int(pool_key["tickSpacing"]),
                checksum_address(pool_key["hooks"]),
            ],
        )
    )


def normalize_pool_key(pool_key: dict) -> dict:
    return {
        "currency0": checksum_address(pool_key["currency0"]),
        "currency1": checksum_address(pool_key["currency1"]),
        "fee": int(pool_key["fee"]),
        "tickSpacing": int(pool_key["tickSpacing"]),
        "hooks": checksum_address(pool_key["hooks"]),
    }


def is_dynamic_fee(fee: int) -> bool:
    return (int(fee) & DYNAMIC_FEE_FLAG) != 0


def format_fee(fee: int, lp_fee: int | None = None) -> str:
    if is_dynamic_fee(fee):
        if lp_fee is None:
            return "dynamic (0x800000)"
        return f"dynamic (live {int(lp_fee) / 10000:.4f}%)"
    return f"{int(fee) / 10000:.4f}%"


def sort_currencies(a: str, b: str) -> tuple[str, str]:
    """Order two currencies the way a PoolKey must."""
    if a.lower() < b.lower():
        return checksum_address(a), checksum_address(b)
    return checksum_address(b), checksum_address(a)


# The (fee, tickSpacing) pairs a hook-less pool is conventionally opened with — the
# tiers v4 inherited from v3. v4 itself permits any combination, so this is a search
# space, not a rule: every candidate is confirmed against slot0 before it is reported,
# and --fee-tiers widens it when a pool used something unusual.
VANILLA_FEE_TIERS: tuple[tuple[int, int], ...] = (
    (100, 1), (500, 10), (3000, 60), (10000, 200),
)


def derive_vanilla_candidates(chain: dict, token: str, quotes: list[str] | None = None,
                              fee_tiers: tuple[tuple[int, int], ...] | None = None
                              ) -> list[dict]:
    """Candidate poolIds for hook-less pools holding ``token``.

    A poolId is a keccak hash and cannot be inverted, but with ``hooks`` pinned to the
    zero address and the pair fixed, only ``fee`` and ``tickSpacing`` are free — so the
    whole plausible space is a few dozen hashes and no RPC at all. The caller confirms
    which ids are real with one getSlot0 multicall.

    This is the counterpart to ``launchers.derive_pool_candidates``, which needs a hook
    from a launchpad registry and returns nothing without one.
    """
    if quotes is None:
        quotes = list(chain.get("knownQuotes") or {})
    tiers = fee_tiers or VANILLA_FEE_TIERS

    out: list[dict] = []
    seen: set[str] = set()
    for quote in quotes:
        # A pool cannot pair a currency with itself, and NATIVE doubles as the ETH
        # marker here, so a native-quoted token would otherwise collide.
        if quote.lower() == token.lower():
            continue
        currency0, currency1 = sort_currencies(token, quote)
        for fee, tick_spacing in tiers:
            pool_key = normalize_pool_key({
                "currency0": currency0, "currency1": currency1, "fee": fee,
                "tickSpacing": tick_spacing, "hooks": NATIVE,
            })
            pool_id = compute_pool_id(pool_key)
            if pool_id in seen:
                continue
            seen.add(pool_id)
            out.append({"poolId": pool_id, "poolKey": pool_key})
    return out


# ---------------------------------------------------------------------------
# PositionInfo (packed uint256 returned by getPoolAndPositionInfo)
#
#   bits  0..7    hasSubscriber
#   bits  8..31   tickLower (int24)
#   bits 32..55   tickUpper (int24)
#   bits 56..255  poolId, TRUNCATED to its upper 25 bytes
# ---------------------------------------------------------------------------


def decode_position_info(info: int) -> dict:
    raw = int(info)
    return {
        "hasSubscriber": (raw & 0xFF) != 0,
        "tickLower": as_int_n(24, raw >> 8),
        "tickUpper": as_int_n(24, (raw >> 32) & 0xFFFFFF),
        "truncatedPoolId": to_hex((raw >> 56) & ((1 << 200) - 1), size=25),
    }


def pool_id_matches_truncated(pool_id: str, truncated: str) -> bool:
    """True when a full poolId matches the 25-byte id packed into a PositionInfo."""
    return pool_id[:52].lower() == truncated.lower()


# ---------------------------------------------------------------------------
# Hook permissions — the low 14 bits of the hook address
# ---------------------------------------------------------------------------

HOOK_FLAGS = (
    "AFTER_REMOVE_LIQUIDITY_RETURNS_DELTA",
    "AFTER_ADD_LIQUIDITY_RETURNS_DELTA",
    "AFTER_SWAP_RETURNS_DELTA",
    "BEFORE_SWAP_RETURNS_DELTA",
    "AFTER_DONATE",
    "BEFORE_DONATE",
    "AFTER_SWAP",
    "BEFORE_SWAP",
    "AFTER_REMOVE_LIQUIDITY",
    "BEFORE_REMOVE_LIQUIDITY",
    "AFTER_ADD_LIQUIDITY",
    "BEFORE_ADD_LIQUIDITY",
    "AFTER_INITIALIZE",
    "BEFORE_INITIALIZE",
)


def decode_hook_flags(hook_address: str | None) -> dict:
    addr = (hook_address or NATIVE).lower()
    if addr == NATIVE:
        return {"hasHook": False, "bits": 0, "flags": []}
    bits = int(addr, 16) & 0x3FFF
    flags = [name for i, name in enumerate(HOOK_FLAGS) if (bits >> i) & 1]
    return {"hasHook": True, "bits": bits, "flags": flags}


def format_hook_flags(hook_address: str | None) -> str:
    decoded = decode_hook_flags(hook_address)
    if not decoded["hasHook"]:
        return "none"
    joined = ", ".join(decoded["flags"]) or "no callbacks"
    return f"0x{decoded['bits']:04x} [{joined}]"


# ---------------------------------------------------------------------------
# Log scanning
# ---------------------------------------------------------------------------


def get_logs_chunked(client, chain: dict, address: str, topics: list,
                     from_block: int | None = None) -> list:
    """eth_getLogs with automatic chunking.

    Robinhood's endpoint serves the full range in one shot; anything that refuses
    falls back to fixed-size windows.
    """
    latest = client.block_number()
    log_scan = chain.get("logScan", {})
    start = from_block if from_block is not None else log_scan.get("fromBlock", 0)

    if log_scan.get("supportsFullRange"):
        try:
            return client.get_logs({
                "address": address,
                "topics": topics,
                "fromBlock": to_hex(start),
                "toBlock": "latest",
            })
        except Exception:  # noqa: BLE001
            pass  # Provider changed its mind about range limits — chunk instead.

    step = log_scan.get("chunkBlocks", 9_000)
    out: list = []
    from_ = start
    while from_ <= latest:
        to = min(from_ + step - 1, latest)
        out.extend(client.get_logs({
            "address": address,
            "topics": topics,
            "fromBlock": to_hex(from_),
            "toBlock": to_hex(to),
        }))
        from_ += step
    return out


def decode_initialize_log(log: dict) -> dict:
    args = decode_event_log(POOL_MANAGER_EVENTS_ABI, log["topics"], log["data"])["args"]
    return {
        "poolId": log["topics"][1],
        "poolKey": normalize_pool_key({
            "currency0": args["currency0"],
            "currency1": args["currency1"],
            "fee": args["fee"],
            "tickSpacing": args["tickSpacing"],
            "hooks": args["hooks"],
        }),
        "initSqrtPriceX96": int(args["sqrtPriceX96"]),
        "initTick": int(args["tick"]),
        "blockNumber": int(log["blockNumber"], 16)
        if isinstance(log["blockNumber"], str) else int(log["blockNumber"]),
        "transactionHash": log.get("transactionHash"),
    }


def find_pools_for_token(client, chain: dict, token: str) -> list:
    """Every v4 pool that has ``token`` on either side."""
    padded = pad(checksum_address(token).lower(), size=32)
    as_currency0 = get_logs_chunked(
        client, chain, chain["poolManager"], [TOPIC_INITIALIZE, None, padded]
    )
    as_currency1 = get_logs_chunked(
        client, chain, chain["poolManager"], [TOPIC_INITIALIZE, None, None, padded]
    )

    seen: dict[str, dict] = {}
    for log in [*as_currency0, *as_currency1]:
        decoded = decode_initialize_log(log)
        seen.setdefault(decoded["poolId"], decoded)
    return sorted(seen.values(), key=lambda d: d["blockNumber"])


def get_pool_init(client, chain: dict, pool_id: str) -> dict | None:
    """The Initialize record for one poolId (gives the authoritative PoolKey)."""
    logs = get_logs_chunked(client, chain, chain["poolManager"], [TOPIC_INITIALIZE, pool_id])
    if not logs:
        return None
    return decode_initialize_log(logs[0])


# ---------------------------------------------------------------------------
# Reserves
# ---------------------------------------------------------------------------


def get_pool_ranges(client, chain: dict, pool_id: str, pool: dict,
                    mode: str | None = None) -> dict:
    """Aggregate a pool's live ranges and value them at the current price.

    The returned ``check`` compares the liquidity summed over ranges straddling the
    current tick against StateView.getLiquidity. They must match exactly; a mismatch
    means the log decode or the tick math is wrong, so it is surfaced rather than
    swallowed.
    """
    chosen = mode or chain.get("rangeMode") or "logs"
    if chosen == "ticks":
        return walk_tick_ranges(client, chain, pool_id, pool)

    logs = get_logs_chunked(
        client, chain, chain["poolManager"], [TOPIC_MODIFY_LIQUIDITY, pool_id]
    )
    return aggregate_ranges(logs, pool)


def aggregate_ranges(logs: list, pool: dict) -> dict:
    """The pure half of get_pool_ranges, so a batched multi-pool sweep can reuse it."""
    sqrt_price_x96 = int(pool["sqrtPriceX96"])
    tick = int(pool["tick"])
    active_liquidity = pool.get("activeLiquidity")

    net: dict[str, dict] = {}
    for log in logs:
        args = decode_event_log(
            POOL_MANAGER_EVENTS_ABI, log["topics"], log["data"]
        )["args"]
        tick_lower = int(args["tickLower"])
        tick_upper = int(args["tickUpper"])
        # The decoder already sign-extends int256, but be explicit: a removal read as
        # unsigned would silently inflate every reserve on the pool.
        delta = as_int_n(256, int(args["liquidityDelta"]))
        key = f"{log['topics'][2]}:{args['salt']}:{tick_lower}:{tick_upper}"
        entry = net.get(key)
        if entry:
            entry["liquidity"] += delta
        else:
            net[key] = {
                "tickLower": tick_lower,
                "tickUpper": tick_upper,
                "salt": args["salt"],
                "owner": checksum_address("0x" + log["topics"][2][26:]),
                "liquidity": delta,
            }

    ranges = []
    amount0 = 0
    amount1 = 0
    active_sum = 0

    for entry in net.values():
        if entry["liquidity"] <= 0:
            continue
        amounts = get_amounts_for_liquidity_at_ticks(
            sqrt_price_x96, entry["tickLower"], entry["tickUpper"], entry["liquidity"]
        )
        status = range_status(tick, entry["tickLower"], entry["tickUpper"])
        if status == "in-range":
            active_sum += entry["liquidity"]
        amount0 += amounts["amount0"]
        amount1 += amounts["amount1"]
        ranges.append({**entry, **amounts, "status": status})

    ranges.sort(key=lambda r: r["liquidity"], reverse=True)

    on_chain = None if active_liquidity is None else int(active_liquidity)
    return {
        "ranges": ranges,
        "amount0": amount0,
        "amount1": amount1,
        "eventCount": len(logs),
        "mode": "logs",
        "truncated": None,
        "check": {
            "activeSum": active_sum,
            "onChain": on_chain,
            "ok": None if on_chain is None else active_sum == on_chain,
        },
    }


# ---------------------------------------------------------------------------
# Reserves without logs — tick bitmap walk
# ---------------------------------------------------------------------------


def _word_pos_of(compressed_tick: int) -> int:
    """Floor-division by 256 that stays correct for negative ticks."""
    return compressed_tick // 256


def walk_tick_ranges(client, chain: dict, pool_id: str, pool: dict,
                     max_words: int = 600) -> dict:
    """Reconstruct a pool's liquidity distribution from the tick bitmap.

    On Base a full ModifyLiquidity scan is thousands of chunked eth_getLogs calls,
    which the RPC will not serve. The bitmap gives the same reserves in ~40 view
    calls: read every word of the bitmap, pull liquidityNet for each initialized
    tick, then integrate upward.

    The tradeoff is attribution: this returns contiguous liquidity *segments*, not
    per-owner positions, because the bitmap does not record who added what.
    ``owner`` is therefore None on every range, and the caller should say so. The
    amount totals and the activeLiquidity self-check are exact either way.
    """
    spacing = int(pool["poolKey"]["tickSpacing"])
    sqrt_price_x96 = int(pool["sqrtPriceX96"])
    tick = int(pool["tick"])
    active_liquidity = pool.get("activeLiquidity")

    lo_word = _word_pos_of(min_usable_tick(spacing) // spacing)
    hi_word = _word_pos_of(max_usable_tick(spacing) // spacing)

    # A tickSpacing of 1 spans ~6,900 words. Rather than issue that many calls, centre
    # a window on the current price and tell the caller what was left out.
    truncated = None
    if hi_word - lo_word + 1 > max_words:
        centre = _word_pos_of(tick // spacing)
        half = max_words // 2
        from_word = max(lo_word, centre - half)
        to_word = min(hi_word, from_word + max_words - 1)
        truncated = {
            "fullWords": hi_word - lo_word + 1,
            "scannedWords": to_word - from_word + 1,
            "fromWord": from_word,
            "toWord": to_word,
        }
        lo_word, hi_word = from_word, to_word

    words = list(range(lo_word, hi_word + 1))
    bitmaps = client.multicall([
        {"address": chain["stateView"], "abi": STATE_VIEW_ABI,
         "functionName": "getTickBitmap", "args": [pool_id, w]}
        for w in words
    ])

    initialized: list[int] = []
    for word, entry in zip(words, bitmaps):
        if entry["status"] != "success":
            continue
        bits = int(entry["result"])
        # Walk set bits directly: 256 iterations per word would be 150k rounds of
        # Python for a spacing-1 pool, and almost every word is zero.
        while bits:
            lowest = bits & -bits
            initialized.append((word * 256 + lowest.bit_length() - 1) * spacing)
            bits ^= lowest
    initialized.sort()

    on_chain = None if active_liquidity is None else int(active_liquidity)

    if not initialized:
        return {
            "ranges": [], "amount0": 0, "amount1": 0, "eventCount": None,
            "mode": "ticks", "truncated": truncated,
            "check": {
                "activeSum": 0,
                "onChain": on_chain,
                "ok": None if on_chain is None else on_chain == 0,
            },
        }

    nets = client.multicall([
        {"address": chain["stateView"], "abi": STATE_VIEW_ABI,
         "functionName": "getTickLiquidity", "args": [pool_id, t]}
        for t in initialized
    ])

    ranges = []
    amount0 = 0
    amount1 = 0
    active_sum = 0
    running = 0

    for i, tick_lower in enumerate(initialized):
        # Skipping a failed read would silently corrupt every range above it, since
        # the walk is a running sum. Fail loudly and let the caller retry or fall
        # back to logs.
        if nets[i]["status"] != "success":
            raise RuntimeError(
                f"getTickLiquidity failed at tick {tick_lower} for pool {pool_id} "
                "— cannot integrate liquidity"
            )
        running += as_int_n(128, int(nets[i]["result"][1]))
        if i + 1 >= len(initialized) or running <= 0:
            continue
        tick_upper = initialized[i + 1]

        amounts = get_amounts_for_liquidity_at_ticks(
            sqrt_price_x96, tick_lower, tick_upper, running
        )
        status = range_status(tick, tick_lower, tick_upper)
        if status == "in-range":
            active_sum += running
        amount0 += amounts["amount0"]
        amount1 += amounts["amount1"]
        ranges.append({
            "tickLower": tick_lower, "tickUpper": tick_upper, "salt": None,
            "owner": None, "liquidity": running, **amounts, "status": status,
        })

    ranges.sort(key=lambda r: r["liquidity"], reverse=True)

    return {
        "ranges": ranges,
        "amount0": amount0,
        "amount1": amount1,
        "eventCount": None,
        "mode": "ticks",
        "truncated": truncated,
        "check": {
            "activeSum": active_sum,
            "onChain": on_chain,
            "ok": None if on_chain is None else active_sum == on_chain,
        },
    }


# ---------------------------------------------------------------------------
# Fees owed on a position (view-only)
# ---------------------------------------------------------------------------


def get_fees_owed(client, chain: dict, pool_id: str, tick_lower: int, tick_upper: int,
                  token_id: int) -> dict[str, Any]:
    """Uncollected fees for a PositionManager-held position.

    Fee-growth counters are allowed to underflow in Uniswap, so the subtraction must
    wrap with ``as_uint_n(256, …)``. A signed subtraction here yields a negative
    number and a garbage fee.
    """
    salt = pad(to_hex(int(token_id)), size=32)
    results = client.multicall([
        {"address": chain["stateView"], "abi": STATE_VIEW_ABI,
         "functionName": "getPositionInfo",
         "args": [pool_id, checksum_address(chain["positionManager"]),
                  tick_lower, tick_upper, salt]},
        {"address": chain["stateView"], "abi": STATE_VIEW_ABI,
         "functionName": "getFeeGrowthInside",
         "args": [pool_id, tick_lower, tick_upper]},
    ], allow_failure=False)

    liquidity, last0, last1 = results[0]["result"]
    current0, current1 = results[1]["result"]
    q128 = 1 << 128
    return {
        "liquidity": int(liquidity),
        "fees0": (int(liquidity) * as_uint_n(256, int(current0) - int(last0))) // q128,
        "fees1": (int(liquidity) * as_uint_n(256, int(current1) - int(last1))) // q128,
    }
