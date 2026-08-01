---
name: senior-unilp-manager
description: "Query and manage Uniswap V4 liquidity on Base (8453) and Robinhood Chain (4663). Use when the user asks how much liquidity a token has, wants a pool's reserves or market-cap bands, asks who launched a token or whether its LP is locked, wants to inspect an LP position or a wallet's positions, or wants to mint, increase, decrease, collect fees from, or burn a V4 position. NOT for: Uniswap v2/v3 positions, token swaps, or price quotes."
homepage: https://docs.uniswap.org/contracts/v4/overview
triggers: [uniswap v4, liquidity position, "check LP", pool id, collect fees, robinhood chain]
provenance:
  origin: agentos-original
  license: MIT
  maintained_by: AgentOS
metadata:
  agentos:
    emoji: "🦄"
    category: crypto
    risk: high
    capabilities: [network-read, network-write, signing]
    requires:
      anyBins: ["python3", "python"]
      env:
        - name: RPC_BASE_URL
          description: JSON-RPC endpoint for Base mainnet (chain id 8453).
          url: https://docs.base.org/chain/network-information
          secret: false
        - name: RPC_ROBINHOOD_URL
          description: JSON-RPC endpoint for Robinhood Chain (chain id 4663).
          url: https://robinhood.com
          secret: false
        - name: UNIV4_LP_PRIVATE_KEY
          description: Signing key for LP writes. Read-only commands never touch it.
          secret: true
---

# Senior UniLP Manager — Uniswap V4 pools and positions

Two scripts, Python 3 stdlib only, no install step.

**`lp_read.py` never touches a private key**; every write goes through `lp_write.py`, which
is a dry run unless it is given both `--broadcast` and the `--confirm <PLAN_HASH>` printed by
that same dry run.

**Part A (read) needs no confirmation. Part B (write) must never broadcast until the user has
seen the parameter table and explicitly said yes.**

```bash
# Keep the quotes — the path can contain spaces.
S="{baseDir}/scripts"

python3 "$S"/lp_read.py  <command> [flags]   # default chain: robinhood
python3 "$S"/lp_write.py <command> [flags]   # add --chain base for Base
```

Chain endpoints come from `RPC_ROBINHOOD_URL` and `RPC_BASE_URL`; `--rpc <url>` overrides.

---

# Part A — Read

## 1. How much liquidity does a token have?

```bash
python3 "$S"/lp_read.py pools --token <addr> [--include-v3]
python3 "$S"/lp_read.py pools --token <addr> --chain base
```

Finds the token's v4 pools, computes exact reserves, prices them, and prints the market-cap
band of every liquidity range. `--include-v3` also probes the Uniswap **v3** factory across
fee tiers 100/500/3000/10000. Dust pools collapse into a one-line count (`--all-pools` shows
them); `--json` for machine-readable output.

Read the **`self-check`** line under the range table: it compares liquidity summed over
ranges straddling the current tick against `StateView.getLiquidity`. If it does not say `OK`,
the numbers are wrong — say so rather than reporting them.

**On Base, discovery goes through the launchpad registries, not logs.** Base cannot serve a
wide `eth_getLogs` range, so a token nobody launched cannot be swept — the command says so
and exits 2 rather than hanging for an hour. Use `pool --id`, or `--scan-logs` to force it.

## 2. One pool in depth

```bash
python3 "$S"/lp_read.py pool --id <poolId> [--ranges 10]
python3 "$S"/lp_read.py pool --id <poolId> --token <addr> --chain base
```

Prints the full PoolKey, dynamic-fee status, decoded hook permissions (labelled with the
launchpad when known), a `poolId recompute` line that must say `OK`, and every liquidity
range with its market-cap band and owner.

**`--token` is required on Base.** A poolId is a keccak hash and cannot be inverted, so the
PoolKey normally comes from the pool's `Initialize` log — which Base will not serve.
`--token` derives it from the launchpad registry in one multicall instead.

| `--mode` | `logs` (default on Robinhood) | `ticks` (default on Base) |
|---|---|---|
| source | replays every `ModifyLiquidity` event | walks `StateView.getTickBitmap` |
| rows are | individual LP positions, **with owner** | merged segments, no owner |
| cost on Base | thousands of requests — unusable | ~36 calls, ~150 ms |

Totals are exact either way — cross-checked on the AGENTOS pool: identical `amount0`, within
1 wei on `amount1`. If a `ticks` read had to be truncated it prints which bitmap words were
skipped; do not report those totals as complete.

## 3. A single position

```bash
python3 "$S"/lp_read.py position --token-id <id>
```

Ticks, the market-cap band the position was added across, principal at the current price,
in/out of range, uncollected fees, USD values. The owner line names known contracts and flags
**LP is LOCKED** when it is a launchpad locker. Works on Base with no log scan.

## 4. A wallet's positions

```bash
python3 "$S"/lp_read.py positions --owner <address> [--include-empty]
```

The v4 PositionManager has no enumerable index, so this scans inbound ERC-721 `Transfer` logs
and re-checks `ownerOf` — a tokenId that was received and later sold will not appear. Not
available on Base; use `position --token-id` or `launcher --token` there.

## 5. Who launched this token, and is the LP locked?

```bash
python3 "$S"/lp_read.py launcher --token <addr> --chain base
```

Supported on Base: **Clanker v4 / v4.1**, **Liquid Protocol**, **Bankr / Doppler**. Each
publishes an on-chain registry mapping token → hook, so the poolId is derived with one keccak
and confirmed with one `getSlot0` — no log scan, ~1–2 s.

- Clanker and Liquid lock the LP as PositionManager NFTs held by their locker. The command
  lists every locked tokenId; feed one to `position --token-id`.
- Doppler mints liquidity directly on the PoolManager, so there is **no NFT** — pool-level
  reads are the only view.
- Trading fees for all three accrue to a separate fee-locker contract, **not** to the
  position. This skill does not read or claim those.

## 6. Turn a market-cap target into ticks

```bash
python3 "$S"/lp_read.py ticks --pool <poolId> --mcap-lower 2000000 --mcap-upper 3000000
```

Snaps outward to `tickSpacing` and reports whether the range is single-sided. Feed the
printed `--tick-lower` / `--tick-upper` straight into `mint`.

---

# Part B — Write

**IMPORTANT: do NOT broadcast any transaction until the user explicitly confirms.**

## The protocol — follow it exactly

1. Run the command **without** `--broadcast`. It simulates and prints a parameter table, the
   simulated wallet deltas, and a `PLAN_HASH`.
2. Show the user that table and use **AskUserQuestion** to get an explicit yes/no.
3. Only on an explicit yes, re-run the **identical** command plus
   `--broadcast --confirm <PLAN_HASH>`.
4. If the hash changed in between, the parameters changed — go back to step 1. Never paste a
   hash the script did not just print.

`PLAN_HASH` covers chain, contract, subcommand, tokenId/poolId, ticks, liquidity, slippage
bounds, recipient and signer. It excludes the deadline and gas, so a re-run a few minutes
later still matches.

## Signing

The key is read from **`UNIV4_LP_PRIVATE_KEY` in the environment and nowhere else**.
**Never put a private key on a command line** — it would land in shell history and in the
agent transcript, and redaction only masks `NAME=value`, not a bare hex string. Override the
variable name with `--signer-env <VAR>`. Only the derived address is ever printed. Signing is
pure Python and therefore **not constant-time**: use a hot LP key, not a treasury key.

`--from <address>` is **planning mode**: simulate as any address with no key present. It can
never broadcast. Use it to answer "would this even work" before anyone approves tokens.

## 7. Approvals (Permit2, two legs)

```bash
python3 "$S"/lp_write.py approve --token <erc20>
```

v4 pulls tokens through Permit2, so both legs are needed: `ERC20.approve(Permit2, max)` and
`Permit2.approve(token, PositionManager, amount, expiration)`. The command reports current
allowances and skips whichever leg is already satisfied. Expiration defaults to 30 days.
Native ETH needs no approval.

## 8. Mint a new position

```bash
python3 "$S"/lp_write.py mint --pool <poolId> --tick-lower <t> --tick-upper <t> \
  --amount1 <humanAmount> [--slippage-bps 100] [--recipient <addr>]
```

Size with exactly one of `--amount0`, `--amount1`, or `--liquidity` (give both for a
two-sided position). Ticks snap outward to `tickSpacing`. A range entirely above the current
tick takes **currency1 only**; entirely below takes **currency0 only** — the wrong side is
rejected with an explanation rather than minting nothing. Hooked pools are refused unless you
pass `--allow-hooked`.

## 9. Increase / decrease / collect / burn

```bash
python3 "$S"/lp_write.py increase --token-id <id> --amount1 <n>
python3 "$S"/lp_write.py decrease --token-id <id> --pct 50
python3 "$S"/lp_write.py collect  --token-id <id>
python3 "$S"/lp_write.py burn     --token-id <id>
```

`decrease` also sweeps accrued fees — `TAKE_PAIR` returns principal and fees together. There
is no `collect()` in v4: it is `DECREASE_LIQUIDITY` with `liquidity = 0` plus `TAKE_PAIR`.
`BURN_POSITION` reverts on a non-empty position, so `burn` emits `DECREASE(100%)` +
`BURN_POSITION` + `TAKE_PAIR` in one call — the NFT is destroyed, confirm carefully.

---

## Reading the simulation

Every write dry-run runs `eth_simulateV1` with `traceTransfers`. `modifyLiquidities` returns
nothing, so that trace is the only way to know what a call really moves.

**When the trace disagrees with the computed table, the trace is right** — the script prints
a `WARNING` above 0.5% divergence. Causes and how to read a revert:
`assets/v4-reference.md`.

## Error handling

| Symptom | Cause / fix |
|---|---|
| `no RPC url for …` | Set `RPC_ROBINHOOD_URL` / `RPC_BASE_URL`, or pass `--rpc <url>` |
| `env var UNIV4_LP_PRIVATE_KEY is not set` | Set it in the agent environment — never as a flag |
| `Base cannot serve a wide eth_getLogs range …` | Pass `--token <addr>` to derive the PoolKey from the registry, or `--scan-logs` |
| `No known launchpad on Base deployed …` | Token predates the registries or used another launcher |
| `NOTE: scanned N of M bitmap words` | A `--mode ticks` read was truncated — the totals are incomplete |
| `poolId recompute … MISMATCH` | PoolKey does not hash to the id — usually the live `lpFee` was used instead of the `0x800000` dynamic flag |
| `self-check … MISMATCH` | Log decode or tick math is off. Do not report the reserves |
| `pool has hook 0x…` | Intentional gate. Re-run with `--allow-hooked` after telling the user what the hook can do |
| `range is entirely above/below the current price` | Wrong currency for a single-sided range; swap `--amount0` / `--amount1` |
| `AllowanceExpired` / `InsufficientAllowance` | Run `approve` first — the pool accepted the add |
| `MaximumAmountExceeded` / `MinimumAmountInsufficient` | Raise `--slippage-bps` |
| `--confirm mismatch` | Parameters changed after approval. Re-plan — never force it |
| `pool moved: tick X → Y` | Drift past `--max-tick-drift` between plan and send. Re-plan |
| USD columns show `n/a` | GeckoTerminal has not indexed the token. Amounts are still exact |

## Verifying a change

```bash
python3 {baseDir}/scripts/selftest.py     # 429 offline assertions, no network
```

Covers the keccak / EIP-55 / ABI-codec primitives, secp256k1 signing, TickMath, the AGENTOS
reserve figures, market-cap bands, the three Base launchpad poolIds, and every `unlockData`
blob. Run it after touching anything in `scripts/unilp/`; the live fixtures it pins are
listed in its module docstring.

Deeper background — the v4 Actions table, hook permission bits, and the Clanker / Liquid /
Doppler registry architecture: `{baseDir}/assets/v4-reference.md`.
