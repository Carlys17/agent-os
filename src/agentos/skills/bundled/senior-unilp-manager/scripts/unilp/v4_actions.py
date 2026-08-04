"""Uniswap V4 PositionManager action encoding — port of ``v4-actions.mjs``.

``modifyLiquidities(bytes unlockData, uint256 deadline)`` where
``unlockData = abi.encode(bytes actions, bytes[] params)``. ``actions`` is one byte per
action; ``params`` is the matching abi.encode'd argument blob.

See ``assets/v4-reference.md`` for the parameter layouts and the settle/take pairing rules.
"""

from __future__ import annotations

from .abi_codec import encode
from .abi_defs import POOL_KEY_TUPLE_PARAM
from .hexutil import checksum_address, concat_hex, to_hex
from .v4_pool import NATIVE

ACTIONS = {
    "INCREASE_LIQUIDITY": 0x00,
    "DECREASE_LIQUIDITY": 0x01,
    "MINT_POSITION": 0x02,
    "BURN_POSITION": 0x03,
    "SETTLE": 0x0B,
    "SETTLE_ALL": 0x0C,
    "SETTLE_PAIR": 0x0D,
    "TAKE": 0x0E,
    "TAKE_ALL": 0x0F,
    "TAKE_PORTION": 0x10,
    "TAKE_PAIR": 0x11,
    "CLOSE_CURRENCY": 0x12,
    "CLEAR_OR_TAKE": 0x13,
    "SWEEP": 0x14,
}

ACTION_NAMES = {value: name for name, value in ACTIONS.items()}


def pool_key_tuple(pool_key: dict) -> list:
    return [
        checksum_address(pool_key["currency0"]),
        checksum_address(pool_key["currency1"]),
        int(pool_key["fee"]),
        int(pool_key["tickSpacing"]),
        checksum_address(pool_key["hooks"]),
    ]


def encode_mint_position(pool_key: dict, tick_lower: int, tick_upper: int, liquidity: int,
                         amount0_max: int, amount1_max: int, recipient: str,
                         hook_data: str = "0x") -> str:
    return encode(
        [POOL_KEY_TUPLE_PARAM, {"type": "int24"}, {"type": "int24"}, {"type": "uint256"},
         {"type": "uint128"}, {"type": "uint128"}, {"type": "address"}, {"type": "bytes"}],
        [pool_key_tuple(pool_key), int(tick_lower), int(tick_upper), int(liquidity),
         int(amount0_max), int(amount1_max), checksum_address(recipient), hook_data],
    )


def encode_increase_liquidity(token_id: int, liquidity: int, amount0_max: int,
                              amount1_max: int, hook_data: str = "0x") -> str:
    return encode(
        [{"type": "uint256"}, {"type": "uint256"}, {"type": "uint128"},
         {"type": "uint128"}, {"type": "bytes"}],
        [int(token_id), int(liquidity), int(amount0_max), int(amount1_max), hook_data],
    )


def encode_decrease_liquidity(token_id: int, liquidity: int, amount0_min: int,
                              amount1_min: int, hook_data: str = "0x") -> str:
    return encode(
        [{"type": "uint256"}, {"type": "uint256"}, {"type": "uint128"},
         {"type": "uint128"}, {"type": "bytes"}],
        [int(token_id), int(liquidity), int(amount0_min), int(amount1_min), hook_data],
    )


def encode_burn_position(token_id: int, amount0_min: int, amount1_min: int,
                         hook_data: str = "0x") -> str:
    return encode(
        [{"type": "uint256"}, {"type": "uint128"}, {"type": "uint128"}, {"type": "bytes"}],
        [int(token_id), int(amount0_min), int(amount1_min), hook_data],
    )


def encode_settle_pair(currency0: str, currency1: str) -> str:
    return encode([{"type": "address"}, {"type": "address"}],
                  [checksum_address(currency0), checksum_address(currency1)])


def encode_take_pair(currency0: str, currency1: str, recipient: str) -> str:
    return encode(
        [{"type": "address"}, {"type": "address"}, {"type": "address"}],
        [checksum_address(currency0), checksum_address(currency1), checksum_address(recipient)],
    )


def encode_sweep(currency: str, recipient: str) -> str:
    return encode([{"type": "address"}, {"type": "address"}],
                  [checksum_address(currency), checksum_address(recipient)])


def encode_unlock_data(actions: list[int], params: list[str]) -> str:
    """``actions[]`` + ``params[]`` -> the ``unlockData`` blob for modifyLiquidities."""
    if len(actions) != len(params):
        raise ValueError(f"actions/params length mismatch: {len(actions)} vs {len(params)}")
    action_bytes = concat_hex([to_hex(a, size=1) for a in actions])
    return encode([{"type": "bytes"}, {"type": "bytes[]"}], [action_bytes, params])


def describe_actions(actions: list[int]) -> str:
    return " → ".join(ACTION_NAMES.get(a, f"0x{a:x}") for a in actions)


def is_native_currency(currency: str | None) -> bool:
    return (currency or "").lower() == NATIVE


# ---------------------------------------------------------------------------
# Ready-made action sequences
# ---------------------------------------------------------------------------


def build_mint_plan(pool_key: dict, tick_lower: int, tick_upper: int, liquidity: int,
                    amount0_max: int, amount1_max: int, recipient: str,
                    hook_data: str = "0x") -> dict:
    """Adding liquidity always ends with SETTLE_PAIR — we owe both currencies.

    When currency0 is native ETH we send ``value = amount0Max`` and must append SWEEP, or
    the unspent remainder is left sitting in the PositionManager for anyone to take.
    """
    actions = [ACTIONS["MINT_POSITION"], ACTIONS["SETTLE_PAIR"]]
    params = [
        encode_mint_position(pool_key, tick_lower, tick_upper, liquidity,
                             amount0_max, amount1_max, recipient, hook_data),
        encode_settle_pair(pool_key["currency0"], pool_key["currency1"]),
    ]
    native = is_native_currency(pool_key["currency0"])
    if native:
        actions.append(ACTIONS["SWEEP"])
        params.append(encode_sweep(pool_key["currency0"], recipient))
    return {"actions": actions, "params": params, "value": int(amount0_max) if native else 0}


def build_increase_plan(pool_key: dict, token_id: int, liquidity: int, amount0_max: int,
                        amount1_max: int, recipient: str, hook_data: str = "0x") -> dict:
    actions = [ACTIONS["INCREASE_LIQUIDITY"], ACTIONS["SETTLE_PAIR"]]
    params = [
        encode_increase_liquidity(token_id, liquidity, amount0_max, amount1_max, hook_data),
        encode_settle_pair(pool_key["currency0"], pool_key["currency1"]),
    ]
    native = is_native_currency(pool_key["currency0"])
    if native:
        actions.append(ACTIONS["SWEEP"])
        params.append(encode_sweep(pool_key["currency0"], recipient))
    return {"actions": actions, "params": params, "value": int(amount0_max) if native else 0}


def build_decrease_plan(pool_key: dict, token_id: int, liquidity: int, amount0_min: int,
                        amount1_min: int, recipient: str, hook_data: str = "0x") -> dict:
    """Removing liquidity ends with TAKE_PAIR — principal and accrued fees come out together."""
    return {
        "actions": [ACTIONS["DECREASE_LIQUIDITY"], ACTIONS["TAKE_PAIR"]],
        "params": [
            encode_decrease_liquidity(token_id, liquidity, amount0_min, amount1_min, hook_data),
            encode_take_pair(pool_key["currency0"], pool_key["currency1"], recipient),
        ],
        "value": 0,
    }


def build_collect_plan(pool_key: dict, token_id: int, recipient: str,
                       hook_data: str = "0x") -> dict:
    """Collecting fees in v4 is a zero-liquidity decrease followed by a take."""
    return build_decrease_plan(pool_key, token_id, 0, 0, 0, recipient, hook_data)


def build_burn_plan(pool_key: dict, token_id: int, liquidity: int, amount0_min: int,
                    amount1_min: int, recipient: str, hook_data: str = "0x") -> dict:
    """BURN_POSITION reverts unless the position is already empty.

    So a full exit is DECREASE(all) + BURN + TAKE_PAIR in a single modifyLiquidities call.
    """
    actions: list[int] = []
    params: list[str] = []
    if int(liquidity) > 0:
        actions.append(ACTIONS["DECREASE_LIQUIDITY"])
        params.append(
            encode_decrease_liquidity(token_id, liquidity, amount0_min, amount1_min, hook_data)
        )
    actions.append(ACTIONS["BURN_POSITION"])
    params.append(encode_burn_position(token_id, 0, 0, hook_data))
    actions.append(ACTIONS["TAKE_PAIR"])
    params.append(encode_take_pair(pool_key["currency0"], pool_key["currency1"], recipient))
    return {"actions": actions, "params": params, "value": 0}


def build_ratchet_plan(pool_key: dict, token_id: int, liquidity: int, amount0_min: int,
                       amount1_min: int, recipient: str, remint: dict | None = None,
                       hook_data: str = "0x") -> dict:
    """Exit a one-sided position and redeploy its unconverted remainder, in ONE unlock.

    ``DECREASE(all) → BURN → [MINT] → TAKE_PAIR``. The mint is omitted on the final
    milestone, where nothing is left to redeploy; then this is exactly ``build_burn_plan``.

    **There is deliberately no SETTLE leg.** Deltas accumulate per currency across the whole
    unlock, and the mint always redeploys strictly less of the principal than the decrease
    just credited (and zero of the other currency, because the new range is one-sided). Both
    net deltas are therefore still positive when TAKE_PAIR runs, so nothing is owed and
    nothing is pulled from the wallet.

    Two consequences worth stating, because they are the reason this shape was chosen over
    two separate transactions:

    * Permit2 never enters the picture. An allowance that lapsed mid-mandate cannot strand
      the position, because no allowance is used.
    * There is no window in which the tokens are loose in the wallet with no position. The
      fire either happened or it did not, and the burned NFT proves which.

    ``remint`` is ``{"tickLower", "tickUpper", "liquidity", "amount0Max", "amount1Max"}``.
    For a one-sided redeploy exactly one of the two maxima is non-zero; passing both is
    accepted here but rejected upstream, where the side is known.
    """
    actions: list[int] = []
    params: list[str] = []

    if int(liquidity) > 0:
        actions.append(ACTIONS["DECREASE_LIQUIDITY"])
        params.append(
            encode_decrease_liquidity(token_id, liquidity, amount0_min, amount1_min, hook_data)
        )
    actions.append(ACTIONS["BURN_POSITION"])
    params.append(encode_burn_position(token_id, 0, 0, hook_data))

    if remint is not None:
        if int(remint["liquidity"]) <= 0:
            raise ValueError("build_ratchet_plan: remint liquidity must be > 0")
        actions.append(ACTIONS["MINT_POSITION"])
        params.append(encode_mint_position(
            pool_key, remint["tickLower"], remint["tickUpper"], remint["liquidity"],
            remint["amount0Max"], remint["amount1Max"], recipient, hook_data,
        ))

    actions.append(ACTIONS["TAKE_PAIR"])
    params.append(encode_take_pair(pool_key["currency0"], pool_key["currency1"], recipient))

    # msg.value stays 0 even when currency0 is native ETH: the mint is funded from the
    # in-flight delta, not from the wallet, so there is nothing to send and nothing for a
    # SWEEP to refund. build_mint_plan's native branch would be actively wrong here.
    return {"actions": actions, "params": params, "value": 0}
