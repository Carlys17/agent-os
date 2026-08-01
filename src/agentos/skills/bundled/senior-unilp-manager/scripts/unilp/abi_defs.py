"""Hand-written ABI fragments — a direct port of ``abi.mjs``.

Deliberately independent of any build artifact: these are the only contract shapes
the skill touches, and writing them out means the skill has no dependency on a
compiled ``out/`` tree that may not exist where it runs.
"""

from __future__ import annotations

POOL_KEY_COMPONENTS = [
    {"name": "currency0", "type": "address"},
    {"name": "currency1", "type": "address"},
    {"name": "fee", "type": "uint24"},
    {"name": "tickSpacing", "type": "int24"},
    {"name": "hooks", "type": "address"},
]

POOL_KEY_TUPLE_PARAM = {"type": "tuple", "components": POOL_KEY_COMPONENTS}

ERC20_ABI = [
    {"type": "function", "name": "name", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "string"}]},
    {"type": "function", "name": "symbol", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "string"}]},
    {"type": "function", "name": "decimals", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint8"}]},
    {"type": "function", "name": "totalSupply", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "balanceOf", "stateMutability": "view",
     "inputs": [{"type": "address"}], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "allowance", "stateMutability": "view",
     "inputs": [{"type": "address"}, {"type": "address"}], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "approve", "stateMutability": "nonpayable",
     "inputs": [{"type": "address"}, {"type": "uint256"}], "outputs": [{"type": "bool"}]},
]

STATE_VIEW_ABI = [
    {"type": "function", "name": "getSlot0", "stateMutability": "view",
     "inputs": [{"name": "poolId", "type": "bytes32"}],
     "outputs": [
         {"name": "sqrtPriceX96", "type": "uint160"},
         {"name": "tick", "type": "int24"},
         {"name": "protocolFee", "type": "uint24"},
         {"name": "lpFee", "type": "uint24"},
     ]},
    {"type": "function", "name": "getLiquidity", "stateMutability": "view",
     "inputs": [{"name": "poolId", "type": "bytes32"}],
     "outputs": [{"name": "liquidity", "type": "uint128"}]},
    {"type": "function", "name": "getFeeGrowthInside", "stateMutability": "view",
     "inputs": [
         {"name": "poolId", "type": "bytes32"},
         {"name": "tickLower", "type": "int24"},
         {"name": "tickUpper", "type": "int24"},
     ],
     "outputs": [
         {"name": "feeGrowthInside0X128", "type": "uint256"},
         {"name": "feeGrowthInside1X128", "type": "uint256"},
     ]},
    # The 5-argument overload. The `bytes32 positionId` form silently returns zeros
    # when the key is built wrong, so this is the one to use.
    {"type": "function", "name": "getPositionInfo", "stateMutability": "view",
     "inputs": [
         {"name": "poolId", "type": "bytes32"},
         {"name": "owner", "type": "address"},
         {"name": "tickLower", "type": "int24"},
         {"name": "tickUpper", "type": "int24"},
         {"name": "salt", "type": "bytes32"},
     ],
     "outputs": [
         {"name": "liquidity", "type": "uint128"},
         {"name": "feeGrowthInside0LastX128", "type": "uint256"},
         {"name": "feeGrowthInside1LastX128", "type": "uint256"},
     ]},
    {"type": "function", "name": "getTickLiquidity", "stateMutability": "view",
     "inputs": [{"name": "poolId", "type": "bytes32"}, {"name": "tick", "type": "int24"}],
     "outputs": [
         {"name": "liquidityGross", "type": "uint128"},
         {"name": "liquidityNet", "type": "int128"},
     ]},
    # One word of the tick bitmap: bit `i` is set when tick
    # `(wordPos * 256 + i) * tickSpacing` is initialized. This is what makes reserves
    # readable with no eth_getLogs at all.
    {"type": "function", "name": "getTickBitmap", "stateMutability": "view",
     "inputs": [{"name": "poolId", "type": "bytes32"}, {"name": "wordPos", "type": "int16"}],
     "outputs": [{"name": "tickBitmap", "type": "uint256"}]},
]

POSITION_MANAGER_ABI = [
    {"type": "function", "name": "getPoolAndPositionInfo", "stateMutability": "view",
     "inputs": [{"name": "tokenId", "type": "uint256"}],
     "outputs": [
         {"name": "poolKey", "type": "tuple", "components": POOL_KEY_COMPONENTS},
         {"name": "info", "type": "uint256"},
     ]},
    {"type": "function", "name": "getPositionLiquidity", "stateMutability": "view",
     "inputs": [{"name": "tokenId", "type": "uint256"}],
     "outputs": [{"name": "liquidity", "type": "uint128"}]},
    {"type": "function", "name": "ownerOf", "stateMutability": "view",
     "inputs": [{"name": "tokenId", "type": "uint256"}], "outputs": [{"type": "address"}]},
    {"type": "function", "name": "nextTokenId", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "poolManager", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "address"}]},
    {"type": "function", "name": "permit2", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "address"}]},
    {"type": "function", "name": "modifyLiquidities", "stateMutability": "payable",
     "inputs": [{"name": "unlockData", "type": "bytes"}, {"name": "deadline", "type": "uint256"}],
     "outputs": []},
    {"type": "event", "name": "Transfer",
     "inputs": [
         {"name": "from", "type": "address", "indexed": True},
         {"name": "to", "type": "address", "indexed": True},
         {"name": "id", "type": "uint256", "indexed": True},
     ]},
]

PERMIT2_ABI = [
    {"type": "function", "name": "allowance", "stateMutability": "view",
     "inputs": [
         {"name": "owner", "type": "address"},
         {"name": "token", "type": "address"},
         {"name": "spender", "type": "address"},
     ],
     "outputs": [
         {"name": "amount", "type": "uint160"},
         {"name": "expiration", "type": "uint48"},
         {"name": "nonce", "type": "uint48"},
     ]},
    {"type": "function", "name": "approve", "stateMutability": "nonpayable",
     "inputs": [
         {"name": "token", "type": "address"},
         {"name": "spender", "type": "address"},
         {"name": "amount", "type": "uint160"},
         {"name": "expiration", "type": "uint48"},
     ],
     "outputs": []},
]

POOL_MANAGER_EVENTS_ABI = [
    {"type": "event", "name": "Initialize",
     "inputs": [
         {"name": "id", "type": "bytes32", "indexed": True},
         {"name": "currency0", "type": "address", "indexed": True},
         {"name": "currency1", "type": "address", "indexed": True},
         {"name": "fee", "type": "uint24", "indexed": False},
         {"name": "tickSpacing", "type": "int24", "indexed": False},
         {"name": "hooks", "type": "address", "indexed": False},
         {"name": "sqrtPriceX96", "type": "uint160", "indexed": False},
         {"name": "tick", "type": "int24", "indexed": False},
     ]},
    {"type": "event", "name": "ModifyLiquidity",
     "inputs": [
         {"name": "id", "type": "bytes32", "indexed": True},
         {"name": "sender", "type": "address", "indexed": True},
         {"name": "tickLower", "type": "int24", "indexed": False},
         {"name": "tickUpper", "type": "int24", "indexed": False},
         {"name": "liquidityDelta", "type": "int256", "indexed": False},
         {"name": "salt", "type": "bytes32", "indexed": False},
     ]},
]

V3_FACTORY_ABI = [
    {"type": "function", "name": "getPool", "stateMutability": "view",
     "inputs": [{"type": "address"}, {"type": "address"}, {"type": "uint24"}],
     "outputs": [{"type": "address"}]},
]

V3_POOL_ABI = [
    {"type": "function", "name": "slot0", "stateMutability": "view", "inputs": [],
     "outputs": [
         {"name": "sqrtPriceX96", "type": "uint160"},
         {"name": "tick", "type": "int24"},
         {"name": "observationIndex", "type": "uint16"},
         {"name": "observationCardinality", "type": "uint16"},
         {"name": "observationCardinalityNext", "type": "uint16"},
         {"name": "feeProtocol", "type": "uint8"},
         {"name": "unlocked", "type": "bool"},
     ]},
    {"type": "function", "name": "liquidity", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint128"}]},
    {"type": "function", "name": "token0", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "address"}]},
    {"type": "function", "name": "token1", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "address"}]},
    {"type": "function", "name": "fee", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint24"}]},
    {"type": "function", "name": "tickSpacing", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "int24"}]},
]

# ---------------------------------------------------------------------------
# Launchpad registries (Base)
#
# These entry points make a token's pool findable without scanning PoolManager
# logs, which is what keeps discovery viable on a chain that will not serve a wide
# eth_getLogs range. See assets/v4-reference.md.
# ---------------------------------------------------------------------------

# Clanker v4 and Liquid share this shape; Liquid is a Clanker fork. Verified against
# Clanker RED 0x361e38fe…Eb07 -> hook 0xb429d62f…28CC, locker 0x63D2DfEA…3496.
CLANKER_FACTORY_ABI = [
    {"type": "function", "name": "tokenDeploymentInfo", "stateMutability": "view",
     "inputs": [{"name": "token", "type": "address"}],
     "outputs": [{"type": "tuple", "components": [
         {"name": "token", "type": "address"},
         {"name": "hook", "type": "address"},
         {"name": "locker", "type": "address"},
         {"name": "extensions", "type": "address[]"},
     ]}]},
]

# Inputs only, deliberately: the return struct's field order drifts across Clanker
# versions and is not guaranteed identical in the Liquid fork, so `launchers` word-scans
# the raw return and verifies every candidate position id against the PositionManager
# rather than trusting a byte offset.
CLANKER_LOCKER_ABI = [
    {"type": "function", "name": "tokenRewards", "stateMutability": "view",
     "inputs": [{"name": "token", "type": "address"}], "outputs": []},
]

# Doppler's unified entry point. getAssetData is the only reliable way in, because each
# Doppler token gets its own address-mined hook (flags 0x2544) that cannot be enumerated.
# Verified against BLEND 0x88601AEe…4ba3 -> numeraire WETH, poolInitializer 0xBDF9…6544.
DOPPLER_AIRLOCK_ABI = [
    {"type": "function", "name": "getAssetData", "stateMutability": "view",
     "inputs": [{"name": "asset", "type": "address"}],
     "outputs": [
         {"name": "numeraire", "type": "address"},
         {"name": "timelock", "type": "address"},
         {"name": "governance", "type": "address"},
         {"name": "liquidityMigrator", "type": "address"},
         {"name": "poolInitializer", "type": "address"},
         {"name": "pool", "type": "address"},
         {"name": "migrationPool", "type": "address"},
     ]},
]

# Topic0s, hardcoded so a log scan never depends on the encoder agreeing with us.
# The self-test recomputes all three from their signatures — if keccak256 were wrong,
# these constants would not match and the failure surfaces immediately.
TOPIC_INITIALIZE = "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"
TOPIC_MODIFY_LIQUIDITY = "0xf208f4912782fd25c7f114ca3723a2d5dd6f3bcc3ac8db5af63baa85f711d5ec"
TOPIC_ERC721_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
