"""RLP, EIP-1559 transaction assembly, and the broadcast sequence.

viem's ``walletClient.sendTransaction`` hid four separate decisions behind one call: what
nonce, what fees, what gas limit, and how to serialise. Each one is spelled out here,
because each one can silently produce a transaction that never mines or mines wrong.

The order is deliberate and matches the Node build: revalidate the plan, read a deadline
from the chain's own clock, take a nonce, price the fees, estimate gas with a margin,
serialise, sign, **verify the signature recovers to the signer**, send, print the hash
*before* polling, then poll with a bounded timeout.
"""

from __future__ import annotations

import time

from .hexutil import checksum_address, js_round, strip0x, to_bytes
from .keccak import keccak256
from .secp256k1 import account_from_private_key, ecrecover, sign_digest

# A priority fee below this is how a transaction ends up pending forever on a quiet chain
# — the node accepts it and no builder ever picks it up. 1 gwei is cheap on both chains.
MIN_PRIORITY_FEE = 10**9
DEFAULT_GAS_MULTIPLIER = 1.25
RECEIPT_TIMEOUT_SECS = 180
RECEIPT_POLL_SECS = 2.0


# ---------------------------------------------------------------------------
# RLP
# ---------------------------------------------------------------------------


def _rlp_length(length: int, offset: int) -> bytes:
    if length < 56:
        return bytes([length + offset])
    encoded = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([len(encoded) + offset + 55]) + encoded


def rlp_encode(item) -> bytes:
    """Encode bytes or an arbitrarily nested list of bytes."""
    if isinstance(item, (bytes, bytearray)):
        data = bytes(item)
        if len(data) == 1 and data[0] < 0x80:
            return data
        return _rlp_length(len(data), 0x80) + data
    if isinstance(item, (list, tuple)):
        body = b"".join(rlp_encode(element) for element in item)
        return _rlp_length(len(body), 0xC0) + body
    raise TypeError(f"rlp_encode cannot encode {type(item).__name__}")


def rlp_int(value: int | str | None) -> bytes:
    """Quantities are minimal big-endian; zero is the empty string, not a zero byte."""
    if value is None:
        return b""
    number = int(value, 16) if isinstance(value, str) and value.startswith("0x") else int(value)
    if number < 0:
        raise ValueError("cannot RLP-encode a negative quantity")
    if number == 0:
        return b""
    return number.to_bytes((number.bit_length() + 7) // 8, "big")


# ---------------------------------------------------------------------------
# EIP-1559 serialisation
# ---------------------------------------------------------------------------


def _access_list(entries) -> list:
    out = []
    for entry in entries or []:
        address = to_bytes(entry["address"])
        keys = [to_bytes(key) for key in entry.get("storageKeys", [])]
        out.append([address, keys])
    return out


def serialize_transaction(tx: dict, signature: dict | None = None) -> str:
    """``0x02 || rlp([...])`` — type-2 only; this skill has no reason to send legacy.

    Without a signature this is the payload that gets hashed to produce the sighash;
    with one it is the raw transaction. Same field order, three extra elements.
    """
    fields = [
        rlp_int(tx["chainId"]),
        rlp_int(tx.get("nonce", 0)),
        rlp_int(tx.get("maxPriorityFeePerGas", 0)),
        rlp_int(tx.get("maxFeePerGas", 0)),
        rlp_int(tx.get("gas", 0)),
        to_bytes(tx["to"]) if tx.get("to") else b"",
        rlp_int(tx.get("value", 0)),
        to_bytes(tx.get("data") or "0x"),
        _access_list(tx.get("accessList")),
    ]
    if signature is not None:
        fields += [
            rlp_int(signature["yParity"]),
            rlp_int(signature["r"]),
            rlp_int(signature["s"]),
        ]
    return "0x02" + rlp_encode(fields).hex()


def sign_transaction(tx: dict, private_key: str) -> dict:
    """Sign a type-2 transaction and self-verify before handing back the raw bytes.

    The recovery check is the point of this function. A wrong sighash, a wrong parity, or
    a missed low-s normalisation all produce a perfectly well-formed transaction that a
    node will happily accept and attribute to a *different* address — which, for an
    approval or a liquidity burn, is a silent loss. Recovering costs ~12 ms.
    """
    account = account_from_private_key(private_key)
    unsigned = serialize_transaction(tx)
    digest = keccak256(unsigned)
    signature = sign_digest(private_key, digest)

    recovered = ecrecover(digest, signature["r"], signature["s"], signature["yParity"])
    if recovered.lower() != account["address"].lower():
        raise RuntimeError(
            "refusing to send: the signature recovers to "
            f"{recovered}, not to the signer {account['address']}"
        )

    raw = serialize_transaction(tx, signature)
    return {
        "raw": raw,
        "hash": keccak256(raw),
        "signature": signature,
        "from": account["address"],
    }


# ---------------------------------------------------------------------------
# Filling in what the chain decides
# ---------------------------------------------------------------------------


def suggest_fees(client, priority_fee: int | None = None) -> dict:
    """EIP-1559 fees: ``maxFee = baseFee*2 + priority``.

    Doubling the base fee leaves room for it to climb for six consecutive full blocks
    before the transaction becomes unmineable; the surplus is refunded, so the only cost
    of being generous is a larger balance check. ``eth_feeHistory`` is the fallback for
    nodes that omit ``baseFeePerGas`` from the block, and a flat floor is the fallback
    for chains that predate 1559 reporting entirely.
    """
    base_fee = 0
    try:
        block = client.get_block("latest")
        base_fee = int(block.get("baseFeePerGas") or "0x0", 16)
    except Exception:  # noqa: BLE001 — any transport failure just moves to the fallback
        base_fee = 0

    if priority_fee is None:
        priority_fee = MIN_PRIORITY_FEE
        try:
            history = client.request("eth_feeHistory", ["0x5", "latest", [50]])
            rewards = [int(r[0], 16) for r in (history.get("reward") or []) if r]
            if rewards:
                priority_fee = max(sorted(rewards)[len(rewards) // 2], MIN_PRIORITY_FEE)
        except Exception:  # noqa: BLE001
            pass

    return {
        "maxPriorityFeePerGas": priority_fee,
        "maxFeePerGas": base_fee * 2 + priority_fee,
        "baseFeePerGas": base_fee,
    }


def estimate_gas(client, tx: dict, multiplier: float = DEFAULT_GAS_MULTIPLIER) -> int:
    """Estimated gas with a margin, matching the Node build's ``gas * round(m*100) / 100``.

    ``js_round`` rather than ``round``: Python rounds halves to even, JavaScript rounds
    them up, and ``--gas-multiplier 1.125`` would otherwise pick a different limit here
    than it did there.
    """
    request = {"from": tx["from"], "to": tx["to"], "data": tx.get("data") or "0x"}
    if int(tx.get("value") or 0) > 0:
        request["value"] = hex(int(tx["value"]))
    return client.estimate_gas(request) * js_round(multiplier * 100) // 100


def prepare_transaction(client, chain: dict, signer: str, to: str, data: str,
                        value: int = 0, gas_multiplier: float = DEFAULT_GAS_MULTIPLIER,
                        priority_fee: int | None = None,
                        max_fee_cap: int | None = None) -> dict:
    """Everything needed to sign, read from the chain in one place.

    ``max_fee_cap`` refuses the send outright when the suggested ``maxFeePerGas`` exceeds
    it, rather than silently clamping — a clamped fee just produces a transaction that sits
    in the mempool and gets dropped, which for an unattended runner is a slower way to fail.
    Off by default; gas price is deliberately excluded from PLAN_HASH, so an interactive
    user approved the plan without seeing it either way.
    """
    fees = suggest_fees(client, priority_fee)
    if max_fee_cap is not None and fees["maxFeePerGas"] > int(max_fee_cap):
        raise RuntimeError(
            f"refusing to send: maxFeePerGas would be {fees['maxFeePerGas']} wei, over the "
            f"{int(max_fee_cap)} wei cap (base fee {fees['baseFeePerGas']}). Wait for gas to "
            "fall, or raise the cap."
        )
    tx = {
        "type": "eip1559",
        "chainId": chain["chainId"],
        "nonce": client.transaction_count(signer, "pending"),
        "maxPriorityFeePerGas": fees["maxPriorityFeePerGas"],
        "maxFeePerGas": fees["maxFeePerGas"],
        "to": checksum_address(to),
        "value": int(value),
        "data": data,
        "from": checksum_address(signer),
    }
    tx["gas"] = estimate_gas(client, tx, gas_multiplier)
    return tx


def send_transaction(client, chain: dict, tx: dict, private_key: str,
                     on_hash=None, on_sent=None) -> str:
    """Sign and broadcast. Returns the hash; does not wait.

    The chain id is re-read from the node rather than trusted from the config: signing
    for 8453 and sending to 4663 produces a transaction that is either rejected or —
    worse, if the same key has funds on both — replayable.

    ``on_sent`` is the durability hook: it fires after signing and before broadcast with
    everything needed to find this transaction again, so a journal can fsync first. A crash
    between that fsync and the broadcast is recoverable (nothing was sent); a broadcast with
    nothing on disk would not be. ``on_hash`` is the older display-only callback and still
    fires, after ``on_sent``.
    """
    live_chain_id = client.chain_id()
    if live_chain_id != int(tx["chainId"]):
        raise RuntimeError(
            f"refusing to send: transaction is signed for chain {tx['chainId']} but the "
            f"RPC endpoint reports chain {live_chain_id}. Check --rpc / {chain['rpcEnv'][0]}."
        )

    signed = sign_transaction({k: v for k, v in tx.items() if k != "from"}, private_key)
    if "from" in tx and signed["from"].lower() != tx["from"].lower():
        raise RuntimeError(
            f"refusing to send: the key derives {signed['from']}, plan says {tx['from']}"
        )

    if on_sent:
        # The head is read BEFORE broadcasting on purpose. A recovery log scan bounded by a
        # block number taken afterwards could start past the block the transaction landed
        # in, and would then conclude it never happened.
        try:
            sent_at_block = client.block_number()
        except Exception:  # noqa: BLE001 — a missing bound only widens the recovery scan
            sent_at_block = None
        on_sent({
            "hash": signed["hash"],
            "nonce": int(tx["nonce"]),
            "sentAtBlock": sent_at_block,
            "maxFeePerGas": int(tx.get("maxFeePerGas") or 0),
            "maxPriorityFeePerGas": int(tx.get("maxPriorityFeePerGas") or 0),
            "gas": int(tx.get("gas") or 0),
        })

    # Print the hash before the send, not after: if the node accepts the transaction and
    # the connection then drops, the hash is the only way to find it again.
    if on_hash:
        on_hash(signed["hash"])
    sent = client.send_raw_transaction(signed["raw"])
    if strip0x(sent).lower() != strip0x(signed["hash"]).lower():
        raise RuntimeError(f"node returned hash {sent}, expected {signed['hash']}")
    return signed["hash"]


def wait_for_receipt(client, tx_hash: str, timeout: float = RECEIPT_TIMEOUT_SECS,
                     interval: float = RECEIPT_POLL_SECS) -> dict:
    """Poll until mined. Times out rather than hanging forever on an underpriced send."""
    deadline = time.monotonic() + timeout
    while True:
        receipt = client.get_receipt(tx_hash)
        if receipt:
            return receipt
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"no receipt for {tx_hash} after {timeout:.0f}s. The transaction may still "
                "be pending — check the hash on an explorer before re-sending, or a "
                "duplicate will be broadcast."
            )
        time.sleep(interval)


def receipt_status(receipt: dict) -> str:
    return "success" if int(receipt.get("status") or "0x0", 16) == 1 else "reverted"
