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

The last block is **`recommended pool`** — the deepest by TVL, with its id in full, whether
it needs `--allow-hooked`, and the next command. A launched token routinely has dozens of
pools of which one has real depth and the rest are dust at punitive fee tiers, so take the
recommendation unless the user asked for a specific pool.

**On Base, discovery goes through the launchpad registries, not logs.** Base cannot serve a
wide `eth_getLogs` range. If no launchpad claims the token, the command probes for **hook-less
pools** (see below) before giving up; only if that finds nothing does it exit 2 rather than
hanging for an hour. Use `pool --id`, or `--scan-logs` to force a full scan.

### Finding pools with **no hook**

```bash
python3 "$S"/lp_read.py pools --token <addr> --no-hook
python3 "$S"/lp_read.py pools --token <addr> --no-hook --quote <addr> --chain base
```

A hook-less pool has no registry to look it up in — but with `hooks` pinned to the zero
address only `fee` and `tickSpacing` are free, so its poolId is derived directly at the
conventional tiers (0.01%/1, 0.05%/10, 0.30%/60, 1.00%/200) and confirmed with **one
multicall**. No log scan, same speed on every chain.

This is the fastest way to answer "does a plain, hook-free pool exist for this token?" — the
question to ask before minting, since a hooked pool is refused by default (§8). It covers
only pools paired with a **known quote currency** at a **conventional tier**; `--quote <addr>`
probes a different pairing currency. It is a fast probe, not an exhaustive index, so a
negative result means "not found at the usual shapes", not "does not exist" — drop `--no-hook`
for full discovery.

## 2. One pool in depth

```bash
python3 "$S"/lp_read.py pool --id <poolId> [--ranges 10]
python3 "$S"/lp_read.py pool --id <poolId> --token <addr> --chain base
```

Prints the full PoolKey, dynamic-fee status, decoded hook permissions (labelled with the
launchpad when known), a `poolId recompute` line that must say `OK`, and every liquidity
range with its market-cap band and owner.

**On Base the PoolKey must be recoverable some other way.** A poolId is a keccak hash and
cannot be inverted, so it normally comes from the pool's `Initialize` log — which Base will
not serve. Three routes, cheapest first:

| flag | what it does | cost |
|---|---|---|
| `--currency0 --currency1 --fee --tick-spacing [--hooks]` | give the PoolKey outright — works for **any** pool on any chain | free |
| `--token <addr>` | derive it from the launchpad registry, or from the hook-less fee tiers | 1 multicall |
| `--scan-logs` | scan `Initialize` logs anyway | very slow on Base |

The explicit PoolKey is checked by recomputing the poolId and requiring it to match `--id`, so
a typo errors out instead of silently addressing the wrong pool. `--hooks` is optional and
**defaults to the zero address** — spelling out a PoolKey is the general escape hatch for a
hook-less pool that discovery cannot reach. Pass `--fee 0x800000` for a dynamic-fee pool (hex
is accepted); note that is the PoolKey fee, not the live `lpFee` from slot0.

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
python3 "$S"/lp_read.py ticks --pool <poolId> --mcap-lower 156000 --mcap-upper 200000 --from-current
```

Snaps outward to `tickSpacing` and reports whether the range is single-sided. Feed the
printed `--tick-lower` / `--tick-upper` straight into `mint`.

The two `--mcap` flags may be given in either order — which one is the larger number
depends on whether the target sits above or below where the token trades now.

**`--from-current` when one end of the band is today's price.** Outward snapping would push
that end across the current tick, and the range comes back `two-sided: needs both
currencies` — not what "from this price to X" means. `--from-current` pulls the near edge
back to the correct side of the current tick, keeping the larger part of the band you asked
for, so the result is genuinely single-sided.

The `position type` line names the currency the range takes. **Read it rather than working
the direction out yourself** — it is the same rule `mint` enforces, so if they disagree the
mint is what is wrong. USD columns need a price for the quote currency; if the indexer is
rate-limiting, the error says so and the fix is to wait, not to change pool (§ Error
handling).

---

# Part B — Write

**IMPORTANT: do NOT broadcast any transaction until the user explicitly confirms.**

## Recipe — add a single-sided LP position

The common request: *"add N of my token as LP, from the current price to a market cap of
X"*. Run these five commands in order. Do not design your own sequence, and do not go
looking for a different pool between steps — every deviation below cost a real run ten
minutes of wandering.

```bash
# 1. Which pool? Take the one it prints as "recommended pool" — deepest TVL.
python3 "$S"/lp_read.py pools --token <addr>

# 2. Ticks for the band. --from-current keeps it single-sided; the two --mcap flags go in
#    either order, so "from here to 200k" is the same whether 200k is above or below.
python3 "$S"/lp_read.py ticks --pool <poolId> \
  --mcap-lower <current mcap> --mcap-upper <target mcap> --from-current

# 3. Dry run. Read `position type` from step 2: it names the currency, so use --amount0 for
#    currency0 and --amount1 for currency1. Add --allow-hooked if step 1 said to.
python3 "$S"/lp_write.py mint --pool <poolId> \
  --tick-lower <t> --tick-upper <t> --amount1 <n> [--allow-hooked]

# 4. If step 3 exits 2 with "blocked on approvals" — approve, then repeat step 3.
python3 "$S"/lp_write.py approve --token <addr>

# 5. Show the user the table from step 3, ask, and only then:
python3 "$S"/lp_write.py mint ...same flags... --broadcast --confirm <PLAN_HASH>
```

Things that turn this into a loop, all of them seen in practice:

- **Choosing the side yourself.** Step 2 prints `position type: single-sided: 100% SYM
  (currencyN)`. Use that. Deriving it from whether the target mcap is higher or lower gets
  it backwards half the time (§8).
- **Abandoning a pool because it has a hook.** Check the hook's flags first (§8) — a
  Doppler pool takes third-party LPs, and it is usually the only pool with real depth.
- **Skipping `approve`.** `mint` exiting 2 on approvals is not a reason to try another
  pool; it means the parameters were fine and the allowance was not.
- **Omitting `--from-current`** when one end of the band is today's price. Without it the
  ticks snap outward across the current tick and the position comes back two-sided.
- **Recomputing ticks by hand in Python.** `ticks` already does it, against the same math
  the mint uses.

## The protocol — follow it exactly

1. Run the command **without** `--broadcast`. It simulates and prints a parameter table, the
   simulated wallet deltas, and a `PLAN_HASH`.
2. Show the user that table and use **AskUserQuestion** to get an explicit yes/no.
3. Only on an explicit yes, re-run the **identical** command plus
   `--broadcast --confirm <PLAN_HASH>`.
4. If the hash changed in between, the parameters changed — go back to step 1. Never paste a
   hash the script did not just print.

`PLAN_HASH` covers chain, contract, subcommand, tokenId/poolId, ticks, liquidity, slippage
bounds, recipient, signer, and the guards the table showed you: the Permit2 expiration, the
tick-drift bound and the deadline offset. It excludes the *absolute* deadline and the gas
price, so a re-run a few minutes later still matches. Anything that changes what the
transaction does changes the hash — if you find a flag that does not, that is a bug, and
`selftest.py` Tier 6 is where it gets pinned.

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
two-sided position). Ticks snap outward to `tickSpacing`.

**Which currency a single-sided range takes.** A range entirely **above** the current price
takes **currency0 only**; entirely **below** takes **currency1 only**. The wrong side is
rejected with an explanation rather than minting nothing.

Do not reason about this from the market cap — the mapping flips with which currency the
token is. When the token is `currency1`, a *higher* market cap is a *lower* tick, so "from
here up to a higher mcap" is a range **below** the current tick and takes the token itself.
When it is `currency0` it is the other way round. `ticks` (§6) prints the side outright on
its `position type` line: trust that line and pass its `--tick-lower` / `--tick-upper`
straight through, rather than deriving the direction yourself.

**Hook policy: this skill mints into hook-less pools by default.** A pool whose `hooks` is not
the zero address is refused outright unless you pass `--allow-hooked`, because a hook can
revert the add or take a delta out of it. So plain `mint` is already the "add LP with no hook"
path — the parameter table prints `hooks: none` when that is what you got.

**A hook is not by itself a reason to walk away from a pool.** Which one it is decides that:

| hook | flags | third-party LP adds |
|---|---|---|
| Doppler / Bankr | `0x2544` | **accepted** — no `BEFORE_ADD_LIQUIDITY` gate, so nothing turns the add away up front. Use `--allow-hooked` |
| Clanker / Liquid | `0x28cc` | rejected — `BEFORE_ADD_LIQUIDITY` turns them away |
| anything else | — | unknown; the dry run is the cheap way to find out |

Read the `hook flags` line that `pool` prints rather than the hook address: `BEFORE_ADD_LIQUIDITY`
in the decoded list is the one that refuses outsiders. `AFTER_ADD_LIQUIDITY` — which Doppler
does set — runs after the add and can still revert it, which is exactly what the dry run
catches.

`--allow-hooked` lets the attempt through, it does not make it work — but the dry run costs
one call and never broadcasts, so on a Doppler pool run it rather than going off to hunt for
a hook-less alternative. The deepest pool for a launched token is usually the launch pool,
and on Robinhood Chain that is normally a Doppler pool; the hook-less pools that also exist
for the same token are frequently dust with punitive fee tiers. Compare `TVL` before
switching pools, and prefer the one `pools` marks as recommended (§1).

**Targeting the pool.** `mint` takes a `--pool <poolId>` that must already exist — this skill
**never creates a pool**; there is no `initialize` path in it. Find one first with
`pools --token <addr> --no-hook` (§1). On Base the PoolKey behind that id still has to be
recovered, so pass `--token <addr>`, or spell the key out with
`--currency0 --currency1 --fee --tick-spacing` (§2) — those flags work here too.

## 9. Increase / decrease / collect / burn

```bash
python3 "$S"/lp_write.py increase --token-id <id> --amount1 <n> [--slippage-bps 100]
python3 "$S"/lp_write.py decrease --token-id <id> --pct 50 [--recipient <addr>]
python3 "$S"/lp_write.py collect  --token-id <id> [--recipient <addr>]
python3 "$S"/lp_write.py burn     --token-id <id> [--recipient <addr>]
```

`--recipient` defaults to the signer everywhere. On `decrease`, `collect` and `burn` it is
where the tokens come out. On `increase` it is only the `SWEEP` target — the unspent part of
`msg.value` on a native-currency0 pool — and the table says which of the two it is.

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
| `Base cannot serve a wide eth_getLogs range …` | Give the PoolKey directly (`--currency0 --currency1 --fee --tick-spacing`), or `--token <addr>` to derive it, or `--scan-logs` |
| `could not derive the PoolKey for … from token …` | Not a launch pool, and not a hook-less pool at a conventional tier. Spell the PoolKey out, or `--scan-logs` |
| `the PoolKey given on the command line does not describe …` | Recompute guard did its job. Check fee (`0x800000` for dynamic), tickSpacing, `--hooks`, and that `currency0 < currency1` |
| `No known launchpad on Base deployed …, no hook-less pool …` | Token predates the registries, used another launcher, or its pool pairs with an unlisted currency — try `--quote <addr>` |
| `NOTE: scanned N of M bitmap words` | A `--mode ticks` read was truncated — the totals are incomplete |
| `poolId recompute … MISMATCH` | PoolKey does not hash to the id — usually the live `lpFee` was used instead of the `0x800000` dynamic flag |
| `self-check … MISMATCH` | Log decode or tick math is off. Do not report the reserves |
| `pool has hook 0x…` | Intentional gate. Re-run with `--allow-hooked` after telling the user what the hook can do |
| `range is entirely above/below the current price` | Wrong currency for a single-sided range; swap `--amount0` / `--amount1`. Above takes currency0, below takes currency1 — or just re-read `position type` from `ticks` |
| `the price indexer is rate-limiting us …` | Temporary, not a property of the token. Wait ~60s and re-run the same command; a successful fetch is cached for 60s and shared across commands. Do not switch pools over it |
| `the band is narrower than one tickSpacing …` | `--from-current` had no room on either side of the current tick. Widen the mcap band, or pass `--tick-lower` / `--tick-upper` |
| `AllowanceExpired` / `InsufficientAllowance` | Run `approve` first — the pool accepted the add |
| `MaximumAmountExceeded` / `MinimumAmountInsufficient` | Raise `--slippage-bps` |
| `--confirm mismatch` | Parameters changed after approval. Re-plan — never force it |
| `pool moved: tick X → Y` | Drift past `--max-tick-drift` between plan and send. Re-plan |
| USD columns show `n/a` | GeckoTerminal has not indexed the token. Amounts are still exact |

## Verifying a change

```bash
python3 {baseDir}/scripts/selftest.py     # 503 offline assertions, no network
```

Covers the keccak / EIP-55 / ABI-codec primitives, secp256k1 signing, TickMath, the AGENTOS
reserve figures, market-cap bands, the three Base launchpad poolIds, every `unlockData`
blob, and the planning helpers `--from-current` leans on. Run it after touching anything in
`scripts/unilp/`; the live fixtures it pins are listed in its module docstring.

Deeper background — the v4 Actions table, hook permission bits, and the Clanker / Liquid /
Doppler registry architecture: `{baseDir}/assets/v4-reference.md`.
