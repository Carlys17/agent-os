"""Ethereum keccak256, in pure Python.

``hashlib.sha3_256`` is FIPS-202 SHA3, which pads with ``0x06``. Ethereum uses the
original Keccak submission, which pads with ``0x01``. Same permutation, one
different byte, completely different digest — so the stdlib hash cannot stand in
here, not even as an approximation.

The implementation is Keccak-f[1600] with rate 136 (=1088 bits) and capacity 512,
which is what keccak256 is. State is a 5x5 array of 64-bit lanes held in a flat
list indexed ``x + 5*y``.

Costs about 0.4 ms per short input, and the skill hashes on the order of tens of
values per invocation, so there is no reason to reach for anything faster.
"""

from __future__ import annotations

_MASK64 = (1 << 64) - 1

# Rotation offsets, indexed [x + 5*y]. From the Keccak reference specification.
_ROTATIONS = (
    0, 1, 62, 28, 27,
    36, 44, 6, 55, 20,
    3, 10, 43, 25, 39,
    41, 45, 15, 21, 8,
    18, 2, 61, 56, 14,
)

# Round constants for the iota step — 24 rounds for a 1600-bit state.
_ROUND_CONSTANTS = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A,
    0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
    0x8000000080008081, 0x8000000000008009, 0x000000000000008A,
    0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
    0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
    0x000000000000800A, 0x800000008000000A, 0x8000000080008081,
    0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)

_RATE = 136  # bytes absorbed per permutation for keccak256


def _rotl64(value: int, shift: int) -> int:
    if shift == 0:
        return value
    return ((value << shift) | (value >> (64 - shift))) & _MASK64


def _keccak_f1600(state: list[int]) -> None:
    """Apply the 24-round permutation to ``state`` in place."""
    for rc in _ROUND_CONSTANTS:
        # theta
        column = [
            state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20]
            for x in range(5)
        ]
        for x in range(5):
            d = column[(x + 4) % 5] ^ _rotl64(column[(x + 1) % 5], 1)
            for y in range(0, 25, 5):
                state[x + y] ^= d

        # rho + pi, written into a fresh array because pi is a permutation of
        # positions: updating in place would read lanes that were already moved.
        moved = [0] * 25
        for x in range(5):
            for y in range(5):
                moved[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl64(
                    state[x + 5 * y], _ROTATIONS[x + 5 * y]
                )

        # chi
        for y in range(0, 25, 5):
            row = moved[y:y + 5]
            for x in range(5):
                state[x + y] = row[x] ^ ((~row[(x + 1) % 5] & _MASK64) & row[(x + 2) % 5])

        # iota
        state[0] ^= rc


def keccak256_bytes(data: bytes) -> bytes:
    """Return the 32-byte keccak256 digest of ``data``."""
    # Pad: 0x01 marker, zeroes, then 0x80 in the final rate byte. When the marker
    # lands on the last byte of a block the two merge into 0x81 — that is the
    # single-byte-padding case, and the reason inputs of exactly rate-1 bytes are
    # a classic silent failure.
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % _RATE != 0:
        padded.append(0x00)
    padded[-1] |= 0x80

    state = [0] * 25
    for offset in range(0, len(padded), _RATE):
        block = padded[offset:offset + _RATE]
        for i in range(_RATE // 8):
            state[i] ^= int.from_bytes(block[i * 8:(i + 1) * 8], "little")
        _keccak_f1600(state)

    # Squeeze: 32 bytes fit inside the rate, so one squeeze round is enough.
    out = bytearray()
    for i in range(4):
        out += state[i].to_bytes(8, "little")
    return bytes(out)


def keccak256(data: bytes | bytearray | str) -> str:
    """keccak256 of ``data``, returned as a ``0x``-prefixed hex string.

    Accepts raw bytes, a ``0x``-prefixed hex string, or plain text. A ``str`` that
    starts with ``0x`` is treated as hex — matching viem's ``keccak256``, which
    only ever takes hex or bytes. Pass text through :func:`keccak256_text` when the
    ambiguity would bite.
    """
    if isinstance(data, str):
        if data.startswith("0x") or data.startswith("0X"):
            raw = bytes.fromhex(data[2:])
        else:
            raw = data.encode("utf-8")
    else:
        raw = bytes(data)
    return "0x" + keccak256_bytes(raw).hex()


def keccak256_text(text: str) -> str:
    """keccak256 of the UTF-8 encoding of ``text``, even if it looks like hex."""
    return "0x" + keccak256_bytes(text.encode("utf-8")).hex()


def function_selector(signature: str) -> str:
    """The 4-byte selector for a canonical function signature.

    ``signature`` must already be canonical — tuples expanded, no argument names,
    no spaces: ``transfer(address,uint256)``.
    """
    return keccak256_text(signature)[:10]


def event_topic(signature: str) -> str:
    """The 32-byte topic0 for a canonical event signature."""
    return keccak256_text(signature)
