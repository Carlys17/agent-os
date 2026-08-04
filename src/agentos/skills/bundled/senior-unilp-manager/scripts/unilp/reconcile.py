"""Answering "did the fire land?" from the chain, never from our own notes.

The mandate file records what the runner *tried*. Only the chain knows what happened, and
after a crash those two can disagree in half a dozen ways. Three oracles resolve it, in
priority order — the first that gives a total answer wins.

The single-transaction fire shape is what makes this tractable. Because DECREASE, BURN and
MINT all live in one unlock, the whole fire either happened or it did not, and **the burned
NFT is the proof**: an ``ownerOf`` that reverts cannot mean anything else. That turns the
hard question into a boolean, and reduces the receipt to a source of *details* rather than
the thing that decides.

One rule is worth stating on its own, because getting it wrong costs money rather than time:
**never blind-retry a mint on ambiguous evidence.** A duplicate burn is impossible — the NFT
is already gone and the second attempt reverts harmlessly. A duplicate mint is not: it would
deploy the remainder twice. When Oracle C cannot run, the answer is "ask a human", not
"probably fine".
"""

from __future__ import annotations

from .abi_defs import POSITION_MANAGER_ABI, TOPIC_ERC721_TRANSFER
from .hexutil import pad, to_hex

# Sentinels for `truth`
LANDED = "landed"          # the fire is on chain
NOT_SENT = "not-sent"      # definitively never mined; safe to rebuild and send again
PENDING = "pending"        # still in the mempool; do nothing this tick
AMBIGUOUS = "ambiguous"    # the chain answered, and the answer needs a human
UNAVAILABLE = "unavailable"  # the chain did not answer; nothing was decided, retry next tick

# The distinction between the last two is worth keeping sharp. AMBIGUOUS is a fact about the
# position — someone transferred it, someone drained it — and it should stop the mandate
# until a human looks. UNAVAILABLE is a fact about the node, and a five-minute cron will hit
# one eventually; halting on it would mean every RPC blip needs a manual `clear-attention`.
# Both are equally fail-closed at the moment they occur: neither ever sends anything.

ZERO_TOPIC = "0x" + "0" * 64


# ---------------------------------------------------------------------------
# Oracle A — the position itself
# ---------------------------------------------------------------------------


def position_truth(client, chain: dict, token_id: int, expected_owner: str) -> dict:
    """Is the old position still there?

    Uses ``ownerOf``, which reverts on a burned id. It deliberately does **not** use
    ``getPoolAndPositionInfo``: that is a mapping read and returns ``success`` with an
    all-zero PoolKey for a burned token, so it cannot distinguish "gone" from "alive".

    **The control call is not optional.** ``RpcClient.multicall`` reports a transport
    failure — node down, HTTP 500, timeout — as ``status: "failure"`` on the individual
    call, exactly like a contract revert (``rpc.py`` bisects a failed chunk and labels a
    lone survivor "call failed on its own"). Read naively, an RPC hiccup would therefore
    say "the NFT is burned", which this module treats as proof the fire landed. On the
    final milestone that would retire a mandate whose position is still alive and still
    filling. ``nextTokenId`` rides along in the same request as a liveness witness: if it
    came back, the node is up, multicall3 works, and the PositionManager has code, so the
    only remaining explanation for a failed ``ownerOf`` is a real revert. If it did not
    come back, we learned nothing and say so.
    """
    owner_call, liquidity_call, control_call = client.multicall([
        {"address": chain["positionManager"], "abi": POSITION_MANAGER_ABI,
         "functionName": "ownerOf", "args": [int(token_id)]},
        {"address": chain["positionManager"], "abi": POSITION_MANAGER_ABI,
         "functionName": "getPositionLiquidity", "args": [int(token_id)]},
        {"address": chain["positionManager"], "abi": POSITION_MANAGER_ABI,
         "functionName": "nextTokenId", "args": []},
    ])

    if owner_call["status"] != "success":
        if control_call["status"] != "success":
            return {"alive": None, "burned": False, "unreachable": True, "owner": None,
                    "liquidity": 0,
                    "anomaly": "could not read the position: ownerOf and the nextTokenId "
                               "control call both failed, so the node — not the token — is "
                               "what is missing"}
        return {"alive": False, "burned": True, "unreachable": False, "owner": None,
                "liquidity": 0}

    owner = owner_call["result"]
    liquidity = int(liquidity_call["result"]) if liquidity_call["status"] == "success" else 0
    base = {"alive": True, "burned": False, "unreachable": False, "owner": owner}
    if str(owner).lower() != str(expected_owner).lower():
        return {**base, "liquidity": liquidity,
                "anomaly": f"position is owned by {owner}, not the mandate signer "
                           f"{expected_owner} — it was transferred out from under us"}
    if liquidity <= 0:
        return {**base, "liquidity": 0,
                "anomaly": "position still exists but holds no liquidity — it was drained "
                           "outside this mandate"}
    return {**base, "liquidity": liquidity}


# ---------------------------------------------------------------------------
# Oracle B — the nonce watermark
# ---------------------------------------------------------------------------


def nonce_truth(client, signer: str, tx_hash: str, nonce: int) -> dict:
    """Has our nonce been consumed, and is our transaction still in the mempool?

    ``latest`` rather than ``pending``: we want the mined watermark, not one that counts
    our own queued transaction and would always say "consumed".
    """
    mined_count = client.transaction_count(signer, "latest")
    consumed = mined_count > int(nonce)

    in_mempool = None
    if not consumed:
        try:
            in_mempool = client.request("eth_getTransactionByHash", [tx_hash]) is not None
        except Exception:  # noqa: BLE001 — an RPC hiccup must not look like "dropped"
            in_mempool = None

    return {"consumed": consumed, "inMempool": in_mempool, "minedCount": mined_count}


# ---------------------------------------------------------------------------
# Oracle C — a bounded log scan for the replacement NFT
# ---------------------------------------------------------------------------


def find_minted_token_id(client, chain: dict, recipient: str, from_block: int,
                         exclude: set[int] | None = None) -> int | None:
    """The tokenId minted to ``recipient`` since ``from_block``, if exactly one exists.

    ``from_block`` comes from the journal, written before the send, which is what keeps this
    to a handful of blocks. Without it the scan would start at genesis and Base would simply
    refuse.

    Returns ``None`` when nothing matched *or* when several did — two candidates is not a
    reason to pick one, it is a reason to stop.
    """
    latest = client.block_number()
    start = max(int(from_block), 0)
    step = int((chain.get("logScan") or {}).get("chunkBlocks") or 9_000)
    skip = exclude or set()

    found: list[int] = []
    cursor = start
    while cursor <= latest:
        window_end = min(cursor + step - 1, latest)
        logs = client.get_logs({
            "address": chain["positionManager"],
            "topics": [TOPIC_ERC721_TRANSFER, ZERO_TOPIC, pad(str(recipient).lower(), size=32)],
            "fromBlock": to_hex(cursor),
            "toBlock": to_hex(window_end),
        })
        for log in logs:
            token_id = int(log["topics"][3], 16)
            if token_id not in skip and token_id not in found:
                found.append(token_id)
        cursor = window_end + 1

    if len(found) == 1:
        return found[0]
    return None


# ---------------------------------------------------------------------------
# The combined verdict
# ---------------------------------------------------------------------------


def reconcile(client, chain: dict, signer: str, token_id: int, sent: dict | None) -> dict:
    """What really happened to the in-flight fire on ``token_id``.

    ``sent`` is the journalled ``{"hash", "nonce", "sentAtBlock"}``, or ``None`` when no
    transaction was ever signed.

    Returns ``{"truth", "reason", "position", "nonce"}``.
    """
    position = position_truth(client, chain, token_id, signer)

    if position.get("unreachable"):
        # Not knowing is its own answer, and the safe one: every other branch below acts.
        return {"truth": UNAVAILABLE, "reason": position["anomaly"],
                "position": position, "nonce": None}

    if position["burned"]:
        return {"truth": LANDED, "reason": "the position NFT is burned, which only this "
                                           "mandate's transaction could have done",
                "position": position, "nonce": None}

    if position.get("anomaly"):
        return {"truth": AMBIGUOUS, "reason": position["anomaly"],
                "position": position, "nonce": None}

    # The position is alive and ours, so the fire did not land. The only question left is
    # whether the transaction is still coming.
    if not sent or not sent.get("hash"):
        return {"truth": NOT_SENT, "reason": "no transaction was ever signed",
                "position": position, "nonce": None}

    nonce = nonce_truth(client, signer, sent["hash"], sent["nonce"])
    if nonce["consumed"]:
        # Nonce spent but the NFT is still alive: our transaction reverted, or a manual
        # replacement took the slot. Either way nothing changed on chain, so re-planning is
        # safe — the burn cannot be duplicated.
        return {"truth": NOT_SENT,
                "reason": "nonce was consumed but the position is untouched — the "
                          "transaction reverted or was replaced",
                "position": position, "nonce": nonce}
    if nonce["inMempool"]:
        return {"truth": PENDING, "reason": "still in the mempool",
                "position": position, "nonce": nonce}
    if nonce["inMempool"] is None:
        return {"truth": UNAVAILABLE,
                "reason": "could not ask the node whether the transaction is still pending",
                "position": position, "nonce": nonce}
    return {"truth": NOT_SENT, "reason": "dropped from the mempool and never mined",
            "position": position, "nonce": nonce}
