#!/usr/bin/env python3
"""Offline self-test. No RPC, no network — pure math, encoding and hashing.

    python3 scripts/selftest.py [--verbose]

Every number checked here comes from ``golden_vectors.json``, which was harvested
from the Node/viem implementation this skill was ported from (the generator is
kept at ``assets/harvest-golden-vectors.mjs.txt``). The Node build is the oracle:
building the vectors from the Python would only prove the Python agrees with
itself.

Tiers, in the order a failure should be investigated:

* **Tier 0 — primitives.** keccak256, EIP-55, fixed-point parsing, and the three
  places JavaScript arithmetic differs from Python's. If Tier 0 is red nothing
  above it means anything.
* **Tier 1 — codec.** ABI encode/decode, including the nested ``bytes[]`` that
  ``unlockData`` is built from, and signed-integer decoding.
* **Tier 2 — signing.** secp256k1, RLP, EIP-1559 assembly, PLAN_HASH.
* **Tier 3 — pool math.** TickMath, liquidity amounts, market-cap bands, poolId
  derivation. These are the 42 assertions carried over from the Node self-test.
* **Tier 4 — domain.** PositionInfo unpacking, hook permission bits, range
  aggregation from real logs, and the display helpers.

Tiers whose modules do not exist yet are reported as skipped rather than failed,
so this runs usefully from the first phase of the port onward.

Live fixtures, for sanity-checking a change that this file cannot cover offline:

Robinhood Chain (4663)

* **AGENTOS** ``0x6eDA83Fc299C10d474068A7E69771c809Bcbbba3``, Bankr pool
  ``0x1299aa8c4ea0db5b8453757ed129ed8e916561925926a161cb89842e3987401a`` —
  WETH/AGENTOS, dynamic fee (live 0.70%), tickSpacing 200, hook
  ``0x4e3468951D49f2EEa976eD0D6e75fFCb44a9a544`` (DopplerHookInitializer), six
  ranges, self-check must pass.
* **tokenId 1** — WETH/SMK4, fee 3000, spacing 60, no hook, full range, poolId
  ``0xdb2c20421239d46bb30a7a73029b7f9b7f166489bfb972057d33cbd7249413a5``.
* **tokenId 429610** — native-ETH pool with a hook, owner
  ``0x7de10Fec3dBC1267446d00a1F3ccFcb7F4176412``.
* Uniswap **v3** here uses factory ``0x1f7d7550B1b028f7571E69A784071F0205FD2EfA``,
  *not* the canonical ``0x1F98431c…F984``.

Base (8453) — one live token per launchpad, each with ``--chain base``

* **Clanker v4.1 · RED** ``0x361E38FE0fb91E8EE43510b12A534388c21cEb07`` → hook
  ``0xb429d62f…28CC``, locker ``0x63D2DfEA…3496``, pool
  ``0xaafb0612c0ae7833566ff6ce5a4da0d0cc9a6e64d2e1285ed4efde0d2da5253c``, **5**
  locked positions 2886509–2886513.
* **Liquid · VLAD** ``0x9aa76052bc108C1aE57F987F797be555Ff52EC90`` → hook
  ``0x9811f10C…28cc``, locker ``0x77247fCD…35f3``, pool ``0xb83153f9…bb1f49``,
  **3** locked positions 2886409–2886411.
* **Doppler/Bankr · BLEND** ``0x88601AEeF7D03ECaF76E6B61eAE1CF85B06c4ba3`` →
  numeraire WETH, initializer/hook ``0xBDF938149ac6a781F94FAa0ed45E6A0e984c6544``,
  pool ``0x6e168b69aaae0094068cbb281747c4e6fa2e6b5923f7191f352fdda981128701``,
  no NFTs.
* ``pools --token <RED> --chain base`` must finish in a couple of seconds. If it
  hangs, the registry lookup regressed and it fell back to the log scan.
* Cross-check of the two range modes: on the RED pool the ``--mode ticks`` segment
  ``-202000 → -155000`` has liquidity ``1684492566057752195310837``, exactly the
  sum of positions 2886510 and 2886511.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

GOLDEN_PATH = HERE / "golden_vectors.json"

# Mirrors abi.mjs POOL_KEY_COMPONENTS.
POOL_KEY_COMPONENTS = [
    {"name": "currency0", "type": "address"},
    {"name": "currency1", "type": "address"},
    {"name": "fee", "type": "uint24"},
    {"name": "tickSpacing", "type": "int24"},
    {"name": "hooks", "type": "address"},
]

POOL_MANAGER_EVENTS = [
    {
        "type": "event", "name": "ModifyLiquidity",
        "inputs": [
            {"name": "id", "type": "bytes32", "indexed": True},
            {"name": "sender", "type": "address", "indexed": True},
            {"name": "tickLower", "type": "int24"},
            {"name": "tickUpper", "type": "int24"},
            {"name": "liquidityDelta", "type": "int256"},
            {"name": "salt", "type": "bytes32"},
        ],
    },
    {
        "type": "event", "name": "Initialize",
        "inputs": [
            {"name": "id", "type": "bytes32", "indexed": True},
            {"name": "currency0", "type": "address", "indexed": True},
            {"name": "currency1", "type": "address", "indexed": True},
            {"name": "fee", "type": "uint24"},
            {"name": "tickSpacing", "type": "int24"},
            {"name": "hooks", "type": "address"},
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
        ],
    },
]

AGG3_IN = [{"type": "tuple[]", "components": [
    {"name": "target", "type": "address"},
    {"name": "allowFailure", "type": "bool"},
    {"name": "callData", "type": "bytes"},
]}]
AGG3_OUT = [{"type": "tuple[]", "components": [
    {"name": "success", "type": "bool"},
    {"name": "returnData", "type": "bytes"},
]}]


class Results:
    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose
        self.passed = 0
        self.failures: list[str] = []
        self.skipped: list[str] = []

    def check(self, label: str, got, want) -> None:
        if got == want:
            self.passed += 1
            if self.verbose:
                print(f"  ok   {label}")
        else:
            self.failures.append(f"{label}\n       got  {got!r}\n       want {want!r}")
            print(f"  FAIL {label}")

    def skip(self, tier: str, reason: str) -> None:
        self.skipped.append(f"{tier}: {reason}")
        print(f"  --   skipped ({reason})")


# ---------------------------------------------------------------------------
# Tier 0 — primitives
# ---------------------------------------------------------------------------

def tier0(g: dict, r: Results) -> None:
    from unilp.hexutil import (
        as_int_n,
        as_uint_n,
        checksum_address,
        div_trunc,
        format_units,
        js_round,
        pad,
        parse_units,
        to_hex,
    )
    from unilp.keccak import event_topic, function_selector, keccak256, keccak256_text

    k = g["keccak"]
    r.check("keccak256('')", keccak256("0x"), k["empty"])
    r.check("keccak256('abc')", keccak256_text("abc"), k["abc"])
    # The rate is 136 bytes. Inputs on either side of it exercise pad, exact-fill
    # and spill — the classic place a keccak implementation is silently wrong.
    for n in (1, 135, 136, 137, 271, 272, 273):
        r.check(f"keccak256('a'*{n})", keccak256_text("a" * n), k[f"len_{n}"])
    r.check("keccak256(raw bytes)", keccak256(bytes([0x00, 0xFF, 0x80, 0x01])), k["bytes_00_ff"])

    # Self-validating: reproduce the topic constants the Node skill hardcoded.
    for name, e in g["event_topics"].items():
        r.check(f"topic0 {name}", event_topic(e["signature"]), e["topic0"])
    pinned = g["event_topics_pinned"]
    r.check("TOPIC_INITIALIZE from its signature",
            event_topic(g["event_topics"]["Initialize"]["signature"]), pinned["TOPIC_INITIALIZE"])
    r.check("TOPIC_MODIFY_LIQUIDITY from its signature",
            event_topic(g["event_topics"]["ModifyLiquidity"]["signature"]),
            pinned["TOPIC_MODIFY_LIQUIDITY"])

    for sig, selector in g["selectors"].items():
        r.check(f"selector {sig}", function_selector(sig), selector)

    # The same check against the ported constants file: abi_defs hardcodes these so a
    # log scan never depends on the encoder, which means nothing else would notice if
    # a digit were mistyped during the port.
    try:
        from unilp import abi_defs
    except ImportError:
        pass
    else:
        r.check("abi_defs.TOPIC_INITIALIZE",
                event_topic(g["event_topics"]["Initialize"]["signature"]),
                abi_defs.TOPIC_INITIALIZE)
        r.check("abi_defs.TOPIC_MODIFY_LIQUIDITY",
                event_topic(g["event_topics"]["ModifyLiquidity"]["signature"]),
                abi_defs.TOPIC_MODIFY_LIQUIDITY)
        r.check("abi_defs.TOPIC_ERC721_TRANSFER",
                event_topic("Transfer(address,address,uint256)"),
                abi_defs.TOPIC_ERC721_TRANSFER)

    for lower, e in g["checksum"].items():
        r.check(f"EIP-55 {lower[:10]}…", checksum_address(lower), e["checksummed"])
        # Re-checksumming must be stable: the launcher registry is mixed-case, and
        # hashing without lowercasing first yields a wrong checksum and a wrong poolId.
        r.check(f"EIP-55 stable {lower[:10]}…", checksum_address(e["checksummed"]),
                e["from_checksummed"])

    for c in g["parse_units"]:
        r.check(f"parseUnits({c['value']}, {c['decimals']})",
                str(parse_units(c["value"], c["decimals"])), c["expected"])
    for c in g["format_units"]:
        r.check(f"formatUnits({c['value']}, {c['decimals']})",
                format_units(int(c["value"]), c["decimals"]), c["expected"])

    # JS-vs-Python arithmetic. Each of these is a wrong number, not an exception.
    r.check("div_trunc(-7, 2) truncates toward zero", div_trunc(-7, 2), -3)
    r.check("div_trunc(7, -2) truncates toward zero", div_trunc(7, -2), -3)
    r.check("div_trunc(7, 2)", div_trunc(7, 2), 3)
    r.check("js_round(0.5) is half-up", js_round(0.5), 1)
    r.check("js_round(2.5) is half-up", js_round(2.5), 3)
    r.check("js_round(-0.5)", js_round(-0.5), 0)
    r.check("as_int_n(24, 0xffffff)", as_int_n(24, 0xFFFFFF), -1)
    r.check("as_int_n(24, 0x800000)", as_int_n(24, 0x800000), -8388608)
    r.check("as_uint_n(256, -1) wraps", as_uint_n(256, -1), (1 << 256) - 1)
    r.check("to_hex(-1, size=1)", to_hex(-1, size=1), "0xff")
    r.check("pad('0x01')", pad("0x01"), "0x" + "0" * 62 + "01")

    # Unsized to_hex is the JSON-RPC *quantity* encoding: minimal, no leading zero
    # byte. Padding it to whole bytes makes a node reject "fromBlock": "0x00", which
    # is how a wrong implementation here shows up — as an unexplained HTTP 400 on
    # every log scan, long after the encoder itself has been declared correct.
    th = g["to_hex"]
    for c in th["unsized"]:
        r.check(f"to_hex({c['v']})", to_hex(int(c["v"])), c["out"])
    for c in th["sized"]:
        r.check(f"to_hex({c['v']}, size=32)", to_hex(int(c["v"]), size=32), c["out"])
    for c in th["padded"]:
        r.check(f"pad(to_hex({c['v']}))", pad(to_hex(int(c["v"]))), c["out"])


# ---------------------------------------------------------------------------
# Tier 1 — ABI codec
# ---------------------------------------------------------------------------

def tier1(g: dict, r: Results) -> None:
    from unilp.abi_codec import (
        canonical_type,
        decode,
        decode_event_log,
        encode,
        encode_function_data,
    )
    from unilp.hexutil import concat_hex, to_hex

    for name, e in g["pool_keys"].items():
        pk = e["poolKey"]
        r.check(f"encode PoolKey {name}",
                encode(POOL_KEY_COMPONENTS, [pk["currency0"], pk["currency1"], pk["fee"],
                                             pk["tickSpacing"], pk["hooks"]]),
                e["encoded"])

    for c in g["int_codec"]:
        spec = [{"type": c["type"]}]
        label = f"{c['type']} = {c['value']}"
        r.check(f"encode {label}", encode(spec, [int(c["value"])]), c["encoded"])
        r.check(f"decode {label}", str(decode(spec, c["encoded"])[0]), c["decoded"])

    # The single highest-value vector set: one assertion per plan pins the entire
    # encoder, including the nested bytes[] head/tail layout of unlockData.
    modify_abi = [{"type": "function", "name": "modifyLiquidities",
                   "inputs": [{"type": "bytes"}, {"type": "uint256"}], "outputs": []}]
    for name, p in g["plans"].items():
        action_bytes = concat_hex([to_hex(a, size=1) for a in p["actions"]])
        r.check(f"unlockData {name}",
                encode([{"type": "bytes"}, {"type": "bytes[]"}], [action_bytes, p["params"]]),
                p["unlockData"])
        r.check(f"modifyLiquidities calldata {name}",
                encode_function_data(modify_abi, "modifyLiquidities",
                                     [p["unlockData"], int(p["deadline"])]),
                p["calldata"])

    _check_plan_builders(g, r)

    m = g["multicall3"]
    r.check("aggregate3 request", encode(AGG3_IN, [m["request_calls"]]), m["request_encoded"])
    decoded = decode(AGG3_OUT, m["response_encoded"])[0]
    for i, want in enumerate(m["response_expected"]):
        r.check(f"aggregate3 response[{i}].success", decoded[i]["success"], want["success"])
        # An empty returnData on a "successful" call means no code at the target.
        # It must stay distinguishable from a zero return value.
        r.check(f"aggregate3 response[{i}].returnData", decoded[i]["returnData"],
                want["returnData"])

    ml = g["logs"]["modify_liquidity_negative"]
    args = decode_event_log(POOL_MANAGER_EVENTS, ml["topics"], ml["data"])["args"]
    r.check("ModifyLiquidity.tickLower", args["tickLower"], ml["expected"]["tickLower"])
    r.check("ModifyLiquidity.tickUpper", args["tickUpper"], ml["expected"]["tickUpper"])
    # Sign extension: getting this wrong turns a removal into a ~1e77 addition and
    # the reserve totals still look plausible.
    r.check("ModifyLiquidity.liquidityDelta is negative",
            str(args["liquidityDelta"]), ml["expected"]["liquidityDelta"])

    iz = g["logs"]["initialize"]
    args = decode_event_log(POOL_MANAGER_EVENTS, iz["topics"], iz["data"])["args"]
    for key, want in iz["expected"].items():
        r.check(f"Initialize.{key}", str(args[key]), str(want))

    r.check("canonical tuple expansion",
            canonical_type({"type": "tuple", "components": POOL_KEY_COMPONENTS}),
            "(address,address,uint24,int24,address)")
    r.check("canonical uint widens to uint256", canonical_type({"type": "uint"}), "uint256")


def _check_plan_builders(g: dict, r: Results) -> None:
    """Rebuild each golden plan through ``v4_actions`` and compare it element by element.

    The ``unlockData`` assertions above pin the *encoder* given a params list. These pin
    the *builders* that produce that list: the action order, the SWEEP that only a native
    currency0 gets, the ``value`` that must accompany it, and the DECREASE leg that a
    zero-liquidity burn must skip. Those are the choices that make a call revert, or —
    worse for SWEEP — silently leave ETH in the PositionManager.
    """
    from unilp import v4_actions as va

    # Same inputs the harvest script fed the Node builders.
    pk = g["pool_keys"]["LETTI_base_liquid"]["poolKey"]
    native_key = dict(pk, currency0="0x0000000000000000000000000000000000000000")
    to = "0x7de10Fec3dBC1267446d00a1F3ccFcb7F4176412"
    built = {
        "mint": va.build_mint_plan(pk, 214000, 230400, 177557320016371022708535,
                                   48237000000000000, 9524320039159120000000000000, to),
        "mint_native": va.build_mint_plan(native_key, -60, 60, 1000000000000000000,
                                          500000000000000000, 1000000, to),
        "increase": va.build_increase_plan(pk, 2493126, 12345678901234567890,
                                           1000000000000000000, 2000000000000000000, to),
        "decrease": va.build_decrease_plan(pk, 2493126, 88778660008185511354267, 0, 0, to),
        "collect": va.build_collect_plan(pk, 2493126, to),
        "burn": va.build_burn_plan(pk, 2493126, 177557320016371022708535, 0, 0, to),
        "burn_empty": va.build_burn_plan(pk, 2493126, 0, 0, 0, to),
    }
    for name, plan in built.items():
        want = g["plans"][name]
        r.check(f"plan {name} actions", plan["actions"], want["actions"])
        r.check(f"plan {name} action names", va.describe_actions(plan["actions"]),
                want["action_names"])
        r.check(f"plan {name} params", plan["params"], want["params"])
        # Non-zero only when currency0 is native; getting it wrong strands ETH.
        r.check(f"plan {name} value", str(plan["value"]), want["value"])
        r.check(f"plan {name} unlockData",
                va.encode_unlock_data(plan["actions"], plan["params"]), want["unlockData"])


# ---------------------------------------------------------------------------
# Tier 2 — signing and PLAN_HASH
# ---------------------------------------------------------------------------

def tier2(g: dict, r: Results) -> None:
    from unilp.hexutil import to_hex
    from unilp.keccak import keccak256

    # PLAN_HASH is keccak over a canonical JSON string. The canonical string is
    # stored in the vectors verbatim so a mismatch is diagnosable here rather than
    # showing up only as a differing 8-character hash.
    for name, e in g["plan_hash"].items():
        r.check(f"PLAN_HASH {name}",
                keccak256(to_hex(e["canonical_json"].encode("utf-8")))[2:10], e["hash"])

    # And the builder itself. The vectors record which keys the Node build held as
    # BigInt and which as Number, because that is the whole difficulty: JSON.stringify
    # quoted the former and not the latter, and Python has a single int type. Rebuild
    # each field set with that distinction restored and check both the exact canonical
    # string and the hash.
    from lp_write import Big, plan_hash

    for name, e in g["plan_hash"].items():
        parsed = json.loads(e["canonical_json"])
        fields = {k: (Big(v) if k in e["bigint_keys"] else v) for k, v in parsed.items()}
        for key in e["number_keys"]:
            r.check(f"PLAN_HASH {name}/{key} stays a JSON number",
                    isinstance(fields[key], int) and not isinstance(fields[key], Big), True)
        r.check(f"PLAN_HASH builder {name}", plan_hash(fields), e["hash"])

    try:
        from unilp.secp256k1 import account_from_private_key, ecrecover, sign_digest
    except ImportError:
        r.skip("tier2/signing", "unilp.secp256k1 not written yet")
        return

    s = g["signing"]
    account = account_from_private_key(s["private_key"])
    r.check("derived signer address", account["address"], s["expected_address"])
    signature = sign_digest(s["private_key"], s["digest"])
    r.check("RFC-6979 signature is deterministic", signature["hex"], s["signature"])
    r.check("ecrecover round-trips to the signer",
            ecrecover(s["digest"], signature["r"], signature["s"], signature["yParity"]),
            s["expected_address"])

    try:
        from unilp.tx import sign_transaction
    except ImportError:
        r.skip("tier2/tx", "unilp.tx not written yet")
        return
    tx = dict(s["tx"])
    signed = sign_transaction(tx, s["private_key"])
    r.check("EIP-1559 raw transaction", signed["raw"], s["signed_raw"])
    r.check("transaction hash", signed["hash"], s["tx_hash"])


# ---------------------------------------------------------------------------
# Tier 3 — pool math (the 42 assertions carried over from the Node self-test)
# ---------------------------------------------------------------------------

def tier3(g: dict, r: Results) -> None:
    try:
        from unilp import v4_math  # noqa: F401
    except ImportError:
        r.skip("tier3/math", "unilp.v4_math not written yet")
        return

    import math as _math

    from unilp.v4_math import (
        get_amounts_for_liquidity_at_ticks,
        get_liquidity_for_amounts,
        get_sqrt_ratio_at_tick,
        get_tick_at_sqrt_ratio,
        max_usable_tick,
        mcap_band_for_range,
        min_usable_tick,
        raw_price_at_tick,
        snap_tick,
        tick_at_mcap,
    )

    m = g["math"]

    def close(label: str, got, want, rel: float = 1e-12) -> None:
        """Float comparison — the display path is float, so exact equality is wrong."""
        if want in (0, None) or got is None or _math.isinf(want) or _math.isinf(got):
            r.check(label, got, want)
            return
        r.check(label, abs(got - want) / abs(want) <= rel, True)

    for tick, want in m["sqrt"].items():
        r.check(f"getSqrtRatioAtTick({tick})", str(get_sqrt_ratio_at_tick(int(tick))), want)
    # Round-trip: every tick must survive the conversion and come back unchanged.
    for tick, want in m["tickAt"].items():
        r.check(f"tick round-trip {tick}",
                get_tick_at_sqrt_ratio(get_sqrt_ratio_at_tick(int(tick))), want)
    for tick, want in m["price"].items():
        close(f"rawPriceAtTick({tick})", raw_price_at_tick(int(tick)), want)

    # The live AGENTOS/LETTI brackets, at the LETTI pool's current price.
    price = get_sqrt_ratio_at_tick(229860)
    for c in m["amounts"]:
        got = get_amounts_for_liquidity_at_ticks(price, c["lo"], c["hi"], int(c["L"]), c["ru"])
        label = f"amounts[{c['lo']},{c['hi']}] roundUp={c['ru']}"
        r.check(f"{label} amount0", str(got["amount0"]), c["amount0"])
        r.check(f"{label} amount1", str(got["amount1"]), c["amount1"])
    for c in m["liq"]:
        r.check(f"getLiquidityForAmounts[{c['lo']},{c['hi']}]",
                str(get_liquidity_for_amounts(
                    price, get_sqrt_ratio_at_tick(c["lo"]), get_sqrt_ratio_at_tick(c["hi"]),
                    int(c["a0"]), int(c["a1"]))), c["L"])

    # snapTick in 'nearest' mode rides on Math.round semantics, so the negative and
    # exactly-halfway cases here are the ones that catch banker's rounding.
    for c in m["snap"]:
        r.check(f"snapTick({c['t']}, {c['s']}, {c['mo']})",
                snap_tick(c["t"], c["s"], c["mo"]), c["r"])
    for c in m["minmax"]:
        r.check(f"minUsableTick({c['s']})", min_usable_tick(c["s"]), c["min"])
        r.check(f"maxUsableTick({c['s']})", max_usable_tick(c["s"]), c["max"])

    opts = dict(m["band_options"])
    opts["total_supply"] = int(opts["total_supply"])
    for c in m["band"]:
        band = mcap_band_for_range(c["lo"], c["hi"], **opts)
        for edge in ("from", "to"):
            want = c[edge]
            if want is None or want == "Infinity":
                want = _math.inf
            close(f"mcapBand[{c['lo']},{c['hi']}].{edge}", band[edge], want, rel=1e-9)
    band_opts = {k: v for k, v in opts.items() if k != "tick_spacing"}
    for c in m["tickAtMcap"]:
        r.check(f"tickAtMcap({c['mcap']})", tick_at_mcap(c["mcap"], **band_opts), c["tick"])

    try:
        from unilp.v4_pool import compute_pool_id
    except ImportError:
        r.skip("tier3/poolid", "unilp.v4_pool not written yet")
        return
    for name, e in g["pool_keys"].items():
        if e["pinned_poolId"]:
            r.check(f"poolId {name}", compute_pool_id(e["poolKey"]), e["pinned_poolId"])

    # Every Base launchpad opens a dynamic-fee pool at tickSpacing 200, so the poolId is
    # fully determined by (currencies, hook). These three ids came from live Initialize
    # logs; if derive_pool_candidates stops reproducing them, launcher discovery on Base
    # is silently broken — and it is the only discovery path that chain can serve.
    try:
        from unilp.chains import CHAINS
        from unilp.launchers import derive_pool_candidates
    except ImportError:
        r.skip("tier3/launchpad", "unilp.launchers not written yet")
        return
    lp = g["launchpad_pools"]
    for c in lp["cases"]:
        derived = derive_pool_candidates(
            CHAINS["base"], c["token"], hook=c["hook"], numeraire=lp["numeraire"]
        )
        r.check(f"{c['name']}: one candidate", len(derived), 1)
        r.check(f"{c['name']}: poolId", derived[0]["poolId"] if derived else None,
                c["poolId"])

    _ = get_amounts_for_liquidity_at_ticks  # exercised by the read-path diff in phase 5


# ---------------------------------------------------------------------------
# Tier 4 — domain layer (PositionInfo, hooks, range aggregation, display)
# ---------------------------------------------------------------------------

def tier4(g: dict, r: Results) -> None:
    try:
        from unilp import v4_pool  # noqa: F401
    except ImportError:
        r.skip("tier4/domain", "unilp.v4_pool not written yet")
        return

    from unilp.v4_pool import (
        aggregate_ranges,
        decode_hook_flags,
        decode_position_info,
        format_hook_flags,
        pool_id_matches_truncated,
    )

    for i, c in enumerate(g["position_info"]):
        got = decode_position_info(int(c["packed"]))
        for key, want in c["expected"].items():
            r.check(f"positionInfo[{i}].{key}", got[key], want)
        # The packed id keeps only the top 25 bytes; the match must still hold.
        r.check(f"positionInfo[{i}] matches its poolId",
                pool_id_matches_truncated(c["source_poolId"], got["truncatedPoolId"]), True)

    for c in g["hook_flags"]:
        got = decode_hook_flags(c["address"])
        for key, want in c["decoded"].items():
            r.check(f"hookFlags({c['address'][:10]}).{key}", got[key], want)
        r.check(f"formatHookFlags({c['address'][:10]})",
                format_hook_flags(c["address"]), c["formatted"])

    # Range aggregation end to end, on the real ModifyLiquidity log. The stored log is a
    # *removal*; feeding only that must produce no ranges, because a net-negative entry
    # is dropped. If sign extension regressed it would instead surface a ~1e77 range.
    ml = g["logs"]["modify_liquidity_negative"]
    liquidity = -int(ml["expected"]["liquidityDelta"])
    positive_data = "0x" + ml["data"][2:-128] + \
        format(liquidity & ((1 << 256) - 1), "064x") + "0" * 64
    pool = {"sqrtPriceX96": int(g["logs"]["initialize"]["expected"]["sqrtPriceX96"]),
            "tick": 229860, "activeLiquidity": None}
    add_log = {"topics": ml["topics"], "data": positive_data}
    remove_log = {"topics": ml["topics"], "data": ml["data"]}

    added = aggregate_ranges([add_log], pool)
    r.check("aggregateRanges add: one range", len(added["ranges"]), 1)
    r.check("aggregateRanges add: liquidity",
            str(added["ranges"][0]["liquidity"]), str(liquidity))
    r.check("aggregateRanges add: ticks",
            (added["ranges"][0]["tickLower"], added["ranges"][0]["tickUpper"]),
            (ml["expected"]["tickLower"], ml["expected"]["tickUpper"]))
    # Current tick 229860 sits far above the range, so it holds currency1 only.
    r.check("aggregateRanges add: status", added["ranges"][0]["status"], "above")
    r.check("aggregateRanges add: amount0 is zero", str(added["amount0"]), "0")
    r.check("aggregateRanges add: owner from topic",
            added["ranges"][0]["owner"], "0x7de10Fec3dBC1267446d00a1F3ccFcb7F4176412")

    netted = aggregate_ranges([add_log, remove_log], pool)
    r.check("aggregateRanges add+remove nets to nothing", len(netted["ranges"]), 0)
    r.check("aggregateRanges counts both events", netted["eventCount"], 2)
    r.check("aggregateRanges removal alone yields nothing",
            len(aggregate_ranges([remove_log], pool)["ranges"]), 0)

    # -- display ----------------------------------------------------------
    from unilp.fmt import (
        fmt_band,
        fmt_units,
        fmt_usd,
        parse_args,
        render_kv,
        render_table,
        short,
        short_id,
    )

    fmt = g["format"]
    for c in fmt["fmt_units"]:
        r.check(f"fmtUnits({c['value']}, {c['decimals']}, {c['maxFrac']})",
                fmt_units(int(c["value"]), c["decimals"], c["maxFrac"]), c["out"])
    for c in fmt["fmt_usd"]:
        value = c["value"]
        # toPrecision's exponential threshold is where Python's %g disagrees with JS.
        value = math.inf if value == "Infinity" else value
        r.check(f"fmtUsd({c['value']})", fmt_usd(value), c["out"])
    for c in fmt["fmt_band"]:
        band = c["band"]
        if band and band.get("to") == "Infinity":
            band = {**band, "to": math.inf}
        r.check(f"fmtBand({c['band']})", fmt_band(band), c["out"])
    r.check("short", short("0x9811f10Cd549c754Fa9E5785989c422A762c28cc"), fmt["short"])
    r.check("shortId", short_id(
        "0x4e539dbb29b663a1345c01240a45b8412b9855b0f69e15879d6ab06aeab6f53e"),
        fmt["short_id"])
    r.check("renderTable", render_table(
        [{"key": "a", "label": "tick"},
         {"key": "b", "label": "liquidity", "align": "right"}],
        [{"a": "-202000", "b": "1684492566057752195310837"}, {"a": "0", "b": "1"}],
    ), fmt["table"])
    r.check("renderKv", render_kv([("poolId", "0x4e53"), ("tickSpacing", "200")]),
            fmt["kv"])

    args = parse_args(["pool", "--id", "0xabc", "--json", "--mode=ticks", "--ranges", "10"])
    r.check("parseArgs positional", args["_"], ["pool"])
    r.check("parseArgs value", args["id"], "0xabc")
    r.check("parseArgs bare flag", args["json"], True)
    r.check("parseArgs --k=v", args["mode"], "ticks")
    r.check("parseArgs trailing value", args["ranges"], "10")


# ---------------------------------------------------------------------------

TIERS = (
    ("Tier 0 — primitives (keccak, EIP-55, fixed point, JS arithmetic)", tier0),
    ("Tier 1 — ABI codec (encode/decode, unlockData, logs)", tier1),
    ("Tier 2 — signing and PLAN_HASH", tier2),
    ("Tier 3 — pool math and poolId", tier3),
    ("Tier 4 — domain layer (PositionInfo, hooks, ranges, display)", tier4),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="print every passing assertion, not just failures")
    args = parser.parse_args()

    if not GOLDEN_PATH.is_file():
        print(f"missing golden vectors: {GOLDEN_PATH}", file=sys.stderr)
        return 2
    golden = json.loads(GOLDEN_PATH.read_text())

    results = Results(args.verbose)
    for title, fn in TIERS:
        print(title)
        try:
            fn(golden, results)
        except Exception:
            results.failures.append(f"{title} raised:\n{traceback.format_exc()}")
            print("  FAIL (exception)")
            traceback.print_exc()

    print()
    if results.failures:
        print(f"{len(results.failures)} FAILED, {results.passed} passed")
        for failure in results.failures:
            print(f"  - {failure}")
        return 1
    print(f"{results.passed} assertions pass" + (
        f", {len(results.skipped)} tier(s) skipped" if results.skipped else ""))
    for entry in results.skipped:
        print(f"  skipped {entry}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
