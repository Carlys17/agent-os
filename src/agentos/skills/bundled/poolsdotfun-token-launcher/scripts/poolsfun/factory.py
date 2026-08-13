"""PartyFactory / PartyLocker surface: ABIs, errors, salt mining, curve math.

Everything here was derived from the verified source at
``0x626C3d09B65bF5d1D40E0D5F25e19fa49783B3D4`` on Robinhood Chain and checked
against the reference launch, tx ``0x0978ee72…`` ("Pools Fun" / POOL).

Three facts drive the whole module and are worth stating before the code:

1. **The salt has to be mined.** ``launch`` reverts ``TokenNotToken0()`` unless the
   CREATE2 token address sorts *below* the paired asset, because the factory mints
   single-sided liquidity and requires the launched token to be ``token0``. Against
   WETH (``0x0Bd7…``) roughly 4.6% of salts qualify, so a launch simply cannot be
   assembled without a search. See :func:`mine_salt`.

2. **The launch price is not an input.** ``expectedStartTick`` looks like a knob but
   is a race guard: the factory reads its own tick from ``startTickFor`` and reverts
   ``StartTickChanged()`` on any mismatch. The tick tracks ``initialFdvUsd``, which
   is ``onlyOwner``. Callers pick identity and dev buy; never pricing.

3. **``launch`` is exactly simulatable.** ``eth_call`` with ``devBuyMinOut = 0``
   returns the true ``(token, pool, devBuyOut)`` because the dev buy is the pool's
   first swap inside the same transaction, so nothing can front-run it. This is what
   makes simulate-then-send meaningful rather than advisory.
"""

from __future__ import annotations

from typing import Any

from .abi_codec import decode, encode_function_data
from .keccak import event_topic

# ── protocol constants (immutable in the deployed factory) ──────────────────
TOTAL_SUPPLY = 1_000_000_000 * 10**18
FEE = 10000  # 1%
TICK_SPACING = 200
MAX_TICK = 887272
MAX_USABLE_TICK = (MAX_TICK // TICK_SPACING) * TICK_SPACING  # 887200
DEAD = "0x000000000000000000000000000000000000dEaD"

PARTY_FACTORY_ABI: list[dict] = [
    {
        "type": "function", "name": "launch", "stateMutability": "payable",
        "inputs": [
            {"name": "name", "type": "string"},
            {"name": "symbol", "type": "string"},
            {"name": "metadataUri", "type": "string"},
            {"name": "salt", "type": "bytes32"},
            {"name": "pairedAsset", "type": "address"},
            {"name": "expectedStartTick", "type": "int24"},
            {"name": "deadline", "type": "uint256"},
            {"name": "creator", "type": "address"},
            {"name": "feeRecipient", "type": "address"},
            {"name": "devBuyAmountIn", "type": "uint256"},
            {"name": "devBuyMinOut", "type": "uint256"},
        ],
        "outputs": [
            {"name": "token", "type": "address"},
            {"name": "pool", "type": "address"},
            {"name": "devBuyOut", "type": "uint256"},
        ],
    },
    {
        "type": "function", "name": "computeTokenAddress", "stateMutability": "view",
        "inputs": [
            {"name": "deployer", "type": "address"},
            {"name": "salt", "type": "bytes32"},
            {"name": "name", "type": "string"},
            {"name": "symbol", "type": "string"},
            {"name": "metadataUri", "type": "string"},
        ],
        "outputs": [{"name": "", "type": "address"}],
    },
    {
        "type": "function", "name": "startTickFor", "stateMutability": "view",
        "inputs": [{"name": "pairedAsset", "type": "address"}],
        "outputs": [{"name": "tick", "type": "int24"}, {"name": "live", "type": "bool"}],
    },
    {
        "type": "function", "name": "allowedPairedAsset", "stateMutability": "view",
        "inputs": [{"name": "asset", "type": "address"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function", "name": "getPairedAssetCurve", "stateMutability": "view",
        "inputs": [{"name": "asset", "type": "address"}],
        "outputs": [{"name": "", "type": "tuple", "components": [
            {"name": "feed", "type": "address"},
            {"name": "maxPriceAge", "type": "uint32"},
            {"name": "fallbackTick", "type": "int24"},
            {"name": "set", "type": "bool"},
        ]}],
    },
    {"type": "function", "name": "paused", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "bool"}]},
    {"type": "function", "name": "locker", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "address"}]},
    {"type": "function", "name": "initialFdvUsd", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "owner", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "address"}]},
    {"type": "function", "name": "weth", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "address"}]},
    {"type": "function", "name": "usdg", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "address"}]},
    {"type": "function", "name": "sequencerUptimeFeed", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "address"}]},
    {
        "type": "event", "name": "TokenLaunched",
        "inputs": [
            {"name": "token", "type": "address", "indexed": True},
            {"name": "pool", "type": "address", "indexed": True},
            {"name": "pairedAsset", "type": "address", "indexed": False},
            {"name": "creator", "type": "address", "indexed": True},
            {"name": "deployer", "type": "address", "indexed": False},
            {"name": "feeRecipient", "type": "address", "indexed": False},
            {"name": "startTick", "type": "int24", "indexed": False},
            {"name": "metadataUri", "type": "string", "indexed": False},
            {"name": "devBuyAmountOut", "type": "uint256", "indexed": False},
        ],
    },
]

PARTY_LOCKER_ABI: list[dict] = [
    {
        "type": "function", "name": "getPoolInfo", "stateMutability": "view",
        "inputs": [{"name": "token", "type": "address"}],
        "outputs": [
            {"name": "pairedAsset", "type": "address"},
            {"name": "pool", "type": "address"},
            {"name": "creator", "type": "address"},
            {"name": "feeRecipient", "type": "address"},
            {"name": "tokenIds", "type": "uint256[]"},
        ],
    },
    {
        "type": "function", "name": "getPoolSplits", "stateMutability": "view",
        "inputs": [{"name": "token", "type": "address"}],
        "outputs": [
            {"name": "pc", "type": "uint16"}, {"name": "pp", "type": "uint16"},
            {"name": "pb", "type": "uint16"}, {"name": "pcm", "type": "uint16"},
            {"name": "tc", "type": "uint16"}, {"name": "tprot", "type": "uint16"},
        ],
    },
    {"type": "function", "name": "collect", "stateMutability": "nonpayable",
     "inputs": [{"name": "token", "type": "address"}], "outputs": []},
    {"type": "function", "name": "claim", "stateMutability": "nonpayable",
     "inputs": [{"name": "token", "type": "address"}], "outputs": []},
    {"type": "function", "name": "collectAndClaim", "stateMutability": "nonpayable",
     "inputs": [{"name": "token", "type": "address"}], "outputs": []},
    {"type": "function", "name": "setFeeRecipient", "stateMutability": "nonpayable",
     "inputs": [{"name": "token", "type": "address"},
                {"name": "recipient", "type": "address"}], "outputs": []},
]

ERC20_ABI: list[dict] = [
    {"type": "function", "name": "name", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "string"}]},
    {"type": "function", "name": "symbol", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "string"}]},
    {"type": "function", "name": "decimals", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "uint8"}]},
    {"type": "function", "name": "totalSupply", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "balanceOf", "stateMutability": "view",
     "inputs": [{"name": "account", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "allowance", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"},
                {"name": "spender", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "approve", "stateMutability": "nonpayable",
     "inputs": [{"name": "spender", "type": "address"},
                {"name": "amount", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"type": "function", "name": "metadataUri", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "string"}]},
]

V3_POOL_ABI: list[dict] = [
    {"type": "function", "name": "slot0", "stateMutability": "view", "inputs": [], "outputs": [
        {"name": "sqrtPriceX96", "type": "uint160"},
        {"name": "tick", "type": "int24"},
        {"name": "observationIndex", "type": "uint16"},
        {"name": "observationCardinality", "type": "uint16"},
        {"name": "observationCardinalityNext", "type": "uint16"},
        {"name": "feeProtocol", "type": "uint8"},
        {"name": "unlocked", "type": "bool"},
    ]},
]

# ── revert decoding ─────────────────────────────────────────────────────────
# Custom errors carry no strings on the wire, so a bare "execution reverted" is
# all an RPC returns. Mapping the 4-byte selector to an explanation is the
# difference between a usable error and a dead end. Each message says what to do,
# not just what happened.
ERROR_MESSAGES: dict[str, str] = {
    "0xb4f54111": (
        "DeployFailed: a token already exists at this salt's address. "
        "Change the name/symbol/metadata, or pick a different --salt."
    ),
    "0x0f5ddbb1": (
        "StartTickChanged: the protocol's launch tick moved between planning and "
        "execution (the ETH price feed updated). Re-run the command to re-plan."
    ),
    "0xd79cce06": (
        "TokenNotToken0: the salt no longer produces an address below the paired "
        "asset. Re-run without --salt to mine a fresh one."
    ),
    "0x203d82d8": "Expired: the deadline passed before the tx landed. Re-run to re-plan.",
    "0x7607bc0d": (
        "CreatorNotCaller: `creator` must equal the sending wallet. Remove --creator "
        "or set it to the signer address."
    ),
    "0x6e4e2579": (
        "AmbiguousDevBuy: native ETH and an ERC20 dev buy were both supplied. "
        "Use either --dev-buy or --dev-buy-asset, never both."
    ),
    "0xb6dc33e4": (
        "DevBuyWethOnly: a native-ETH dev buy only works on WETH pairs. For a USDG "
        "pair use --dev-buy-asset (after `approve`)."
    ),
    "0xedaf7b53": (
        "DevBuyTooLittle: the fill came in under devBuyMinOut. Raise --slippage-bps "
        "or re-plan."
    ),
    "0x5a9b44ca": (
        "PairedAssetNotAllowed: that asset is not on the factory allowlist. "
        "Run `pools_read.py assets` to see what is launchable."
    ),
    "0x9e87fac8": "Paused: the factory is paused. Nothing to do but wait.",
    "0x7983c051": (
        "PoolAlreadyInitialized: a pool for this pair already exists and is "
        "initialized. Change the token identity so its address differs."
    ),
    "0xd92e233d": "ZeroAddress: an address argument was zero.",
    "0x2c5211c6": "InvalidAmount / InvalidTick: an argument failed a range check.",
    "0x1f2a2005": "DevBuyTooLarge: the dev buy amount exceeds the safe int256 bound.",
    "0x8e4a23d6": "LockerUnset: the factory has no locker configured.",
}

# Solidity's Error(string) selector, used for require() reverts from dependencies.
_ERROR_STRING_SELECTOR = "0x08c379a0"
_PANIC_SELECTOR = "0x4e487b71"


def explain_revert(data: Any) -> str | None:
    """Turn revert bytes into a sentence, or None when they mean nothing to us."""
    if not isinstance(data, str) or not data.startswith("0x") or len(data) < 10:
        return None
    selector = data[:10].lower()
    if selector in ERROR_MESSAGES:
        return ERROR_MESSAGES[selector]
    if selector == _ERROR_STRING_SELECTOR:
        try:
            return "reverted: " + str(decode([{"type": "string"}], "0x" + data[10:])[0])
        except Exception:
            return None
    if selector == _PANIC_SELECTOR:
        try:
            code = int(decode([{"type": "uint256"}], "0x" + data[10:])[0])
            return f"Panic(0x{code:02x}) — an assertion inside the contract failed"
        except Exception:
            return None
    return None


# ── calldata builders ───────────────────────────────────────────────────────
def encode_launch(name: str, symbol: str, metadata_uri: str, salt: str,
                  paired_asset: str, expected_start_tick: int, deadline: int,
                  creator: str, fee_recipient: str, dev_buy_amount_in: int,
                  dev_buy_min_out: int) -> str:
    return encode_function_data(PARTY_FACTORY_ABI, "launch", [
        name, symbol, metadata_uri, salt, paired_asset, expected_start_tick,
        deadline, creator, fee_recipient, dev_buy_amount_in, dev_buy_min_out,
    ])


def encode_compute_token_address(deployer: str, salt: str, name: str, symbol: str,
                                 metadata_uri: str) -> str:
    return encode_function_data(PARTY_FACTORY_ABI, "computeTokenAddress",
                                [deployer, salt, name, symbol, metadata_uri])


def salt_hex(value: int) -> str:
    """A uint as a bytes32 salt. Salts are searched as plain integers from 0 up."""
    if value < 0 or value >= 2**256:
        raise ValueError("salt out of range")
    return "0x" + format(value, "064x")


# ── salt mining ─────────────────────────────────────────────────────────────
def sorts_below(token: str, paired_asset: str) -> bool:
    """Whether ``token`` would be ``token0`` of the pair. The launch invariant."""
    return int(token, 16) < int(paired_asset, 16)


def salt_hit_rate(paired_asset: str) -> float:
    """Fraction of random addresses that sort below the paired asset.

    Purely informational — it turns "mining" from an opaque wait into a number
    the user can sanity-check ("~4.6% for WETH, so expect a couple dozen tries").
    """
    return int(paired_asset, 16) / float(2**160)


# The public endpoint answers a 50-call batch comfortably (~0.6 s) and 429s on
# 100. 40 leaves headroom for the rate limiter to also be seeing other traffic,
# and still resolves a WETH salt in one round trip about 85% of the time.
SALT_BATCH_SIZE = 40


def mine_salt(client: Any, factory: str, deployer: str, name: str, symbol: str,
              metadata_uri: str, paired_asset: str, *, start: int = 0,
              max_attempts: int = 5000, batch_size: int = SALT_BATCH_SIZE,
              on_progress: Any = None) -> tuple[str, str, int]:
    """Search for a salt whose CREATE2 address sorts below the paired asset.

    Returns ``(salt_hex, token_address, attempts)``.

    The search runs on-chain via batched ``computeTokenAddress`` ``eth_call``s
    rather than reproducing CREATE2 locally. That costs round trips, but computing
    it here would mean embedding a copy of PartyToken's creation bytecode in the
    skill — a constant that silently goes wrong the day the factory is redeployed,
    producing addresses that look plausible and revert on launch. Asking the
    factory cannot drift. At ~4.6% hit rate against WETH a batch of 100 almost
    always resolves on the first round trip.
    """
    attempts = 0
    candidate = start
    while attempts < max_attempts:
        window = min(batch_size, max_attempts - attempts)
        salts = [salt_hex(candidate + i) for i in range(window)]
        calls = [
            {
                "method": "eth_call",
                "params": [
                    {"to": factory,
                     "data": encode_compute_token_address(
                         deployer, s, name, symbol, metadata_uri)},
                    "latest",
                ],
            }
            for s in salts
        ]
        results = client.batch(calls, chunk_size=window)
        for offset, result in enumerate(results):
            attempts += 1
            if isinstance(result, dict) and "error" in result:
                continue
            token = decode([{"type": "address"}], result)[0]
            if sorts_below(token, paired_asset):
                return salts[offset], token, attempts
        candidate += window
        if on_progress:
            on_progress(attempts)

    raise RuntimeError(
        f"no qualifying salt in {max_attempts} attempts. The token address must sort "
        f"below {paired_asset} (~{salt_hit_rate(paired_asset) * 100:.1f}% of salts "
        f"qualify). Raise --max-salt-attempts, or change the name/symbol."
    )


# ── curve math ──────────────────────────────────────────────────────────────
def price_from_tick(tick: int) -> float:
    """Paired-asset units per token. token is always token0, so price = 1.0001^tick."""
    return 1.0001**tick


def fdv_usd(tick: int, paired_usd: float, supply: int = TOTAL_SUPPLY,
            token_decimals: int = 18) -> float:
    """Fully-diluted valuation in USD at a given tick.

    Reported rather than chosen: the factory pins this to ``initialFdvUsd``
    (currently $10,000) and there is no caller input that moves it.
    """
    return price_from_tick(tick) * paired_usd * (supply / 10**token_decimals)


def validate_start_tick(tick: int) -> None:
    """The factory's own tick bounds, mirrored so we fail before spending gas."""
    if tick % TICK_SPACING != 0:
        raise ValueError(f"start tick {tick} is not a multiple of {TICK_SPACING}")
    if tick < -MAX_USABLE_TICK or tick >= MAX_USABLE_TICK:
        raise ValueError(f"start tick {tick} outside ±{MAX_USABLE_TICK}")


# ── event decoding ──────────────────────────────────────────────────────────
TOPIC_TOKEN_LAUNCHED = event_topic(
    "TokenLaunched(address,address,address,address,address,address,int24,string,uint256)"
)


def decode_token_launched(logs: list[dict], factory: str) -> dict | None:
    """Pull the launch result out of a receipt. None when the event is absent."""
    for log in logs:
        if log.get("address", "").lower() != factory.lower():
            continue
        topics = log.get("topics") or []
        if not topics or topics[0].lower() != TOPIC_TOKEN_LAUNCHED:
            continue
        fields = decode(
            [
                {"type": "address"}, {"type": "address"}, {"type": "address"},
                {"type": "int24"}, {"type": "string"}, {"type": "uint256"},
            ],
            log["data"],
        )
        return {
            "token": "0x" + topics[1][-40:],
            "pool": "0x" + topics[2][-40:],
            "creator": "0x" + topics[3][-40:],
            "pairedAsset": fields[0],
            "deployer": fields[1],
            "feeRecipient": fields[2],
            "startTick": int(fields[3]),
            "metadataUri": fields[4],
            "devBuyAmountOut": int(fields[5]),
        }
    return None
