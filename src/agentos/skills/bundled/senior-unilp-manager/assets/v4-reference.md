# Uniswap V4 reference — actions, hooks, launchpads

Background for `senior-unilp-manager`. SKILL.md tells you which command to run; this file
explains why the numbers come out the way they do, and is worth reading before changing any
encoding, hook gate, or discovery path.

---

# Part 1 — PositionManager actions

Everything goes through one entrypoint:

```solidity
function modifyLiquidities(bytes calldata unlockData, uint256 deadline) external payable;
```

where `unlockData = abi.encode(bytes actions, bytes[] params)`. `actions` is a packed byte
string, one byte per action; `params[i]` is the abi-encoded argument blob for `actions[i]`.
Encoded by `scripts/unilp/v4_actions.py`.

## Action bytes

| Byte | Name | Used for |
|---|---|---|
| `0x00` | INCREASE_LIQUIDITY | add to an existing position |
| `0x01` | DECREASE_LIQUIDITY | remove from a position; `liquidity = 0` realises fees |
| `0x02` | MINT_POSITION | create a new position NFT |
| `0x03` | BURN_POSITION | destroy an **already empty** position NFT |
| `0x0b` | SETTLE | pay one currency |
| `0x0c` | SETTLE_ALL | pay one currency, whole open delta |
| `0x0d` | SETTLE_PAIR | pay both currencies of the PoolKey |
| `0x0e` | TAKE | receive one currency |
| `0x0f` | TAKE_ALL | receive one currency, whole open delta |
| `0x10` | TAKE_PORTION | receive a fraction |
| `0x11` | TAKE_PAIR | receive both currencies of the PoolKey |
| `0x12` | CLOSE_CURRENCY | settle or take depending on the sign of the delta |
| `0x13` | CLEAR_OR_TAKE | take if above a threshold, otherwise forfeit dust |
| `0x14` | SWEEP | refund a leftover currency balance to a recipient |

## Parameter layouts

```
MINT_POSITION      abi.encode(PoolKey, int24 tickLower, int24 tickUpper, uint256 liquidity,
                              uint128 amount0Max, uint128 amount1Max, address recipient,
                              bytes hookData)
INCREASE_LIQUIDITY abi.encode(uint256 tokenId, uint256 liquidity,
                              uint128 amount0Max, uint128 amount1Max, bytes hookData)
DECREASE_LIQUIDITY abi.encode(uint256 tokenId, uint256 liquidity,
                              uint128 amount0Min, uint128 amount1Min, bytes hookData)
BURN_POSITION      abi.encode(uint256 tokenId, uint128 amount0Min, uint128 amount1Min,
                              bytes hookData)
SETTLE_PAIR        abi.encode(Currency currency0, Currency currency1)
TAKE_PAIR          abi.encode(Currency currency0, Currency currency1, address recipient)
CLOSE_CURRENCY     abi.encode(Currency currency)
CLEAR_OR_TAKE      abi.encode(Currency currency, uint256 amountMax)
SWEEP              abi.encode(Currency currency, address recipient)
```

`PoolKey` is the tuple `(address currency0, address currency1, uint24 fee, int24 tickSpacing,
address hooks)` — encode it as a real tuple, never packed.

## Pairing rules

Every action leaves a *delta*, and the call reverts with `CurrencyNotSettled()` unless every
delta is closed before the unlock ends.

- Adding liquidity creates **negative** deltas (you owe) → end with `SETTLE_PAIR`.
- Removing liquidity creates **positive** deltas (you are owed) → end with `TAKE_PAIR`.
- `TAKE_PAIR` / `SETTLE_PAIR` argument order must follow the **PoolKey's** currency order,
  not the order the user typed the tokens in.

| Command | Actions |
|---|---|
| `mint` | `MINT_POSITION` → `SETTLE_PAIR` (+ `SWEEP` if currency0 is native) |
| `increase` | `INCREASE_LIQUIDITY` → `SETTLE_PAIR` (+ `SWEEP` if native) |
| `decrease` | `DECREASE_LIQUIDITY` → `TAKE_PAIR` |
| `collect` | `DECREASE_LIQUIDITY(liquidity = 0)` → `TAKE_PAIR` |
| `burn` | `DECREASE_LIQUIDITY(all)` → `BURN_POSITION` → `TAKE_PAIR` |

## Native ETH pools

When `currency0 == address(0)`:

- set `msg.value = amount0Max` (not the exact amount — the pool takes what it needs);
- **append `SWEEP(currency0, recipient)`** or the unspent remainder is left in the
  PositionManager where anyone can claim it;
- there is no Permit2 leg for the native side;
- `TAKE_PAIR` sends raw ETH, so the recipient must be able to receive it.

## Permit2

ERC-20 currencies are pulled through Permit2, which needs two separate approvals:

```
ERC20.approve(PERMIT2, type(uint256).max)
PERMIT2.approve(token, POSITION_MANAGER, uint160 amount, uint48 expiration)
```

They fail differently: a missing first leg reverts inside Permit2's `transferFrom`; a missing
or expired second leg reverts with `InsufficientAllowance()` / `AllowanceExpired(uint256)`.
The `uint48 expiration` expires silently — prefer ~30 days over `type(uint48).max` and
re-approve rather than granting a permanent allowance.

## Sizing and slippage

v4 has **no price bound** on `modifyLiquidities`. The only protections are `amountXMax` when
adding and `amountXMin` when removing, plus the `deadline`.

Order of operations when adding (getting this backwards causes `MaximumAmountExceeded`):

1. derive `liquidity` from the desired amounts, rounding **down**;
2. recompute the amounts that liquidity actually requires, rounding **up**;
3. `amountXMax = ceil(required × (10000 + slippageBps) / 10000)`.

Compute the `deadline` at broadcast time from chain time, never at plan time.

---

# Part 2 — Hooks

A v4 pool can name a hook contract in its PoolKey. The hook's **address itself** encodes
which callbacks it implements: the low 14 bits are the permission flags.

| Bit | Flag | | Bit | Flag |
|---|---|---|---|---|
| 13 | `BEFORE_INITIALIZE` | | 6 | `AFTER_SWAP` |
| 12 | `AFTER_INITIALIZE` | | 5 | `BEFORE_DONATE` |
| 11 | `BEFORE_ADD_LIQUIDITY` | | 4 | `AFTER_DONATE` |
| 10 | `AFTER_ADD_LIQUIDITY` | | 3 | `BEFORE_SWAP_RETURNS_DELTA` |
| 9 | `BEFORE_REMOVE_LIQUIDITY` | | 2 | `AFTER_SWAP_RETURNS_DELTA` |
| 8 | `AFTER_REMOVE_LIQUIDITY` | | 1 | `AFTER_ADD_LIQUIDITY_RETURNS_DELTA` |
| 7 | `BEFORE_SWAP` | | 0 | `AFTER_REMOVE_LIQUIDITY_RETURNS_DELTA` |

`decode_hook_flags()` in `scripts/unilp/v4_pool.py` does this; `lp_read.py pool` prints it.

## Why it matters before you LP

- **`BEFORE_ADD_LIQUIDITY` set** — the hook can reject your add outright. Many launchpad
  hooks use this to keep all liquidity under their own control.
- **`AFTER_ADD_LIQUIDITY` set** — the add reaches the pool, but the hook runs afterwards and
  can still revert.
- **`*_RETURNS_DELTA` set** — the hook can change what you actually pay or receive. Locally
  computed amounts are then only an estimate.

The flags tell you what *can* happen, never what will. That is why `lp_write.py` refuses
hooked pools without `--allow-hooked`, and why the simulated transfer trace, not the computed
table, is the number to trust.

## When the trace disagrees with the table

Every write dry-run runs `eth_simulateV1` with `traceTransfers`, and the trace is
authoritative. Real causes of a >0.5% divergence, all seen on these chains:

- a hook taking a delta in `afterAddLiquidity` / `afterRemoveLiquidity`;
- a fee-on-transfer token;
- a token whose `transfer` returns `true`, emits nothing, and moves nothing — SmokeV4
  (`0x42bcDF8d…`) on Robinhood Chain behaves exactly like this, so its "fees owed" are real
  on paper and uncollectable in practice.

## Reading a simulated failure

The action order is `MINT_POSITION` → `SETTLE_PAIR`, and the hook callbacks fire inside
`MINT_POSITION`. So:

- a revert from the hook or the pool means **you were rejected**;
- a revert naming a Permit2 error (`AllowanceExpired`, `InsufficientAllowance`) comes from
  the later settle leg, which means **the pool accepted the liquidity** and only the
  approvals are missing.

This is what makes `--from <address>` useful before any token is approved: it answers
"would this pool even let me in".

## Launchpad hooks

### Bankr / Doppler — flags `0x2544`

```
BEFORE_INITIALIZE, AFTER_ADD_LIQUIDITY, AFTER_REMOVE_LIQUIDITY,
AFTER_SWAP, AFTER_SWAP_RETURNS_DELTA
```

`BEFORE_ADD_LIQUIDITY` is **not** set, and a simulated mint reached the settle leg (failing
only on Permit2), so third-party liquidity is accepted at the hook level. `AFTER_ADD_LIQUIDITY`
is still set, so re-simulate before every real mint rather than assuming this holds.

Every Doppler token gets its own address-mined hook, so the address differs per token while
the flags stay `0x2544` — on Robinhood AGENTOS that is
`0x4e3468951D49f2EEa976eD0D6e75fFCb44a9a544` (a `DopplerHookInitializer`), on Base BLEND it
is `0xBDF938149ac6a781F94FAa0ed45E6A0e984c6544`. There is no fixed address to match on; use
`Airlock.getAssetData`.

Pool shape: `fee = 0x800000` (dynamic; live LP fee 7000 = 0.70% on AGENTOS), `tickSpacing =
200`, paired against WETH. The launch seeds one wide range plus a reserve tranche far above
spot, which is why the market-cap bands show most of the supply parked well above spot.

### Clanker v4 / Liquid — flags `0x28cc`

```
BEFORE_INITIALIZE, BEFORE_ADD_LIQUIDITY, BEFORE_SWAP, AFTER_SWAP,
BEFORE_SWAP_RETURNS_DELTA, AFTER_SWAP_RETURNS_DELTA
```

`BEFORE_ADD_LIQUIDITY` **is** set here, and both ship a `PoolExtensionAllowlist`, so assume
third-party mints are gated until a simulation proves otherwise. Same `0x800000` / 200 pool
shape. Unlike Doppler these are fixed hook addresses per version (Clanker
`0xb429d62f…28CC` static / `0xd60D6B21…68Cc` dynamic; Liquid `0x9811f10C…28cc` /
`0x80E2F7dC…68CC`), so they can be matched directly.

The LP itself is a normal PositionManager NFT owned by the launchpad's locker — readable with
`position --token-id`, but permanently locked.

## Dynamic fees

`fee & 0x800000 != 0` marks a dynamic-fee pool. The PoolKey carries `0x800000` forever; the
*live* fee lives in `slot0.lpFee` and changes over time.

**Always hash and mint with `0x800000`.** Recomputing a poolId from the live `lpFee` produces
a valid-looking id for a pool that does not exist, and the failure mode is a confusing
"no Initialize event found".

---

# Part 3 — Launchpads on Base

Most Uniswap v4 tokens on Base were not deployed by hand — a launchpad created the token,
opened the pool, and locked the LP. Each publishes an on-chain registry mapping the token to
its hook, which is what makes the pool findable **without scanning PoolManager logs**.

That matters because log discovery does not work on Base. `CHAINS["base"]["logScan"]` is
`{supportsFullRange: False, chunkBlocks: 9_000, fromBlock: 25_350_000}` and Base is past
block 49.4M, so `find_pools_for_token` would issue ~2,700 sequential `eth_getLogs` calls per
filter, and public endpoints reject wider ranges anyway. Measured: `pools --token <clanker
token> --chain base` produced no output in 60 s before this registry existed, and returns in
~1.8 s with it.

## The shared pool shape

| field | value |
|---|---|
| `fee` | `0x800000` — the dynamic-fee flag |
| `tickSpacing` | `200` |
| pairing currency | usually WETH `0x4200…0006` |

So `poolId = keccak256(abi.encode(currency0, currency1, 0x800000, 200, hook))` is fully
determined once the registry gives up the hook. `derive_pool_candidates` builds exactly that,
and `getSlot0` confirms which candidates are real (an uninitialized pool reads back
`sqrtPriceX96 = 0` rather than reverting).

## Clanker v4 / v4.1

`Clanker.tokenDeploymentInfo(address token)` → `{token, hook, locker, extensions[]}`. Returns
a zero-address struct for tokens it did not deploy, so a miss is not a revert.

```
tokenDeploymentInfo(0x361e38fe…Eb07)   # RED
  hook       0xb429d62f8f3bFFb98CdB9569533eA23bF0Ba28CC   ClankerHookStaticFeeV2
  locker     0x63D2DfEA64b3433F4071A98665bcD7Ca14d93496   ClankerLpLockerFeeConversion
  extensions [0xf652B361…91E0, 0x1331f078…00be]
```

**LP custody: real PositionManager NFTs held by the locker.** `ownerOf(2886509)` returns the
locker. So `position --token-id` works unchanged — the LP is simply not withdrawable.

Both v4.0 and v4.1 answer on the same factory `0xE85A59c6…83a9`; the version is attributed by
which hook comes back.

## Liquid Protocol

A Clanker fork, verified ABI-compatible — same `tokenDeploymentInfo` shape, same
`tokenRewards` shape, same NFT-in-locker custody. Only the addresses differ.

```
tokenDeploymentInfo(0x9aa76052…EC90)   # VLAD, factory 0x04F1a284…7760
  hook   0x9811f10Cd549c754Fa9E5785989c422A762c28cc   LiquidHookStaticFeeV2
  locker 0x77247fCD1d5e34A3703AcA898A591Dc7422435f3   LiquidLpLockerFeeConversion
```

## Doppler (Bankr)

Different architecture. `Airlock.getAssetData(address asset)` at `0x660eAaEd…8D12` is the
only reliable entry point, because **every Doppler token gets its own address-mined hook**
(flags `0x2544`) — there is no fixed hook address to enumerate.

```
getAssetData(0x88601AEe…4ba3)   # BLEND
  numeraire         0x4200000000000000000000000000000000000006   WETH
  poolInitializer   0xBDF938149ac6a781F94FAa0ed45E6A0e984c6544   == the pool's hook
```

`poolInitializer` doubles as the hook, and `0xBDF9…6544.airlock()` returns the Airlock,
confirming the link. This initializer is live on Base but *not* in the published docs list —
another reason the Airlock lookup is authoritative and the hardcoded initializer list in
`launchers.py` is best-effort labelling only.

**LP custody: minted directly on the PoolManager**, not as NFTs. There is no tokenId to
inspect, so pool-level reads (`pool --id`) are the only view.

## Locked position ids

Both Clanker and Liquid store a launch as `(startPositionId, positionCount)` in
`tokenRewards(token)`, with the NFTs minted **consecutively**:

- Clanker RED → `(2886509, 5)` → 2886509…2886513
- Liquid VLAD → `(2886409, 3)` → 2886409…2886411

`probe_position_ids` does not read these by byte offset — the struct layout differs across
versions. It word-scans the raw return, expands any `(id, small count)` pair into a run, then
**verifies every id** against the PositionManager: it must be owned by that locker and sit in
a pool containing the token. The id one past each run fails both checks. A layout change
therefore degrades to "found fewer positions", never to wrong output.

## Reading reserves without logs

`walk_tick_ranges` (in `v4_pool.py`) reconstructs a pool's liquidity from
`StateView.getTickBitmap` + `getTickLiquidity` instead of replaying `ModifyLiquidity`. At
`tickSpacing 200` that is 36 bitmap words — the RED pool reads in ~155 ms.

The tradeoff is attribution: it returns merged liquidity **segments**, not per-owner
positions, because the bitmap does not record who added what. Totals are exact either way.
Cross-checked on RED: the segment `-202000 → -155000` has liquidity
`1684492566057752195310837`, exactly the sum of the two overlapping NFT positions 2886510 and
2886511. Against the Robinhood AGENTOS pool, `--mode logs` and `--mode ticks` agree to the
wei on `amount0` and within 1 wei on `amount1`.

## Not covered

Read-only, Uniswap v4 only, by design:

- **No fee claiming.** For all three launchpads the LP is locked and trading fees accrue to a
  separate contract — `ClankerFeeLocker 0xF3622742…5D68`, `LiquidFeeLocker 0xF7d3BE3F…876FF`,
  Doppler `StreamableFeesLocker 0x0a00775d…bd3a` / `V2 0xce3212e6…3d47`. Nothing here reads or
  claims those balances.
- **No Uniswap v3 positions.** Clanker v3.1 and Doppler's v3 initializers still deploy v3
  pools; those fall back to the balance-only `--include-v3` report, which reads raw pool
  balances (including uncollected fees) and cannot read v3 NFT positions.

Sources: [Clanker](https://clanker.world/docs/references/deployed-contracts#base-8453) ·
[Liquid](https://app.liquidprotocol.org/docs#contracts) ·
[Doppler](https://docs.doppler.lol/reference/contract-addresses)
