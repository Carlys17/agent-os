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
