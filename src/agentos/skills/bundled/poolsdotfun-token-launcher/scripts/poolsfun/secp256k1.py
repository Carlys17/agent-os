"""secp256k1 ECDSA — the one piece viem provided that the stdlib does not.

Only three operations are needed: derive an address from a private key, sign a 32-byte
digest deterministically (RFC 6979, so the same plan always produces the same signature),
and recover the signer from a signature. The last one is not decoration — every signature
this module produces is recovered and checked against the expected address before the
transaction is allowed anywhere near the network. That check costs ~12 ms and removes the
entire class of "wrong v, wrong s normalisation, wrong sighash" bugs, which lose money
silently.

The first of those three lives in ``account.py``, not here, and is re-exported below.
That is not tidying: it lets ``lp_read.py`` answer "which wallet is mine" by importing a
module that has no ``sign_digest`` in it at all. Everything a caller needs to *sign* is
in this file, so importing the derivation half cannot reach it.

Caveat that must stay visible: pure-Python big-integer arithmetic is **not constant time**.
A local attacker who can measure this process precisely could in principle learn something
about the key. Python has no fix for that. The mitigation is operational — this is a
hot-wallet key for LP operations, not a treasury key.
"""

from __future__ import annotations

import hashlib
import hmac

from .account import (
    GX,
    GY,
    HALF_N,
    G,
    N,
    P,
    _jacobian_add,
    _jacobian_multiply,
    _to_affine,
    account_from_private_key,
    add,
    address_from_public_key,
    multiply,
    normalize_private_key,
    public_key,
)
from .hexutil import to_bytes

# Re-exported so `from .secp256k1 import ...` keeps working for every existing caller —
# and so the golden vectors in selftest.py go on testing these through this module.
__all__ = [
    "G",
    "GX",
    "GY",
    "HALF_N",
    "N",
    "P",
    "account_from_private_key",
    "add",
    "address_from_public_key",
    "ecrecover",
    "multiply",
    "normalize_private_key",
    "public_key",
    "sign_digest",
]


# ---------------------------------------------------------------------------
# RFC 6979 deterministic nonce
# ---------------------------------------------------------------------------


def _hmac(key: bytes, *chunks: bytes) -> bytes:
    mac = hmac.new(key, digestmod=hashlib.sha256)
    for chunk in chunks:
        mac.update(chunk)
    return mac.digest()


def _rfc6979_nonces(private: int, digest_int: int):
    """Yield candidate nonces exactly as RFC 6979 §3.2 prescribes.

    A generator rather than a single value because a candidate can produce r == 0 or
    s == 0; the RFC's answer is to keep turning the crank, not to fall back to randomness.
    ``digest_int`` is already reduced mod n by the caller — that is RFC 6979's
    ``bits2octets``, and getting it wrong yields signatures that verify but do not match
    any other implementation's output.
    """
    x = private.to_bytes(32, "big")
    h1 = digest_int.to_bytes(32, "big")
    v = b"\x01" * 32
    k = b"\x00" * 32
    k = _hmac(k, v, b"\x00", x, h1)
    v = _hmac(k, v)
    k = _hmac(k, v, b"\x01", x, h1)
    v = _hmac(k, v)
    while True:
        v = _hmac(k, v)
        candidate = int.from_bytes(v, "big")
        if 1 <= candidate < N:
            yield candidate
        k = _hmac(k, v, b"\x00")
        v = _hmac(k, v)


# ---------------------------------------------------------------------------
# Sign / recover
# ---------------------------------------------------------------------------


def sign_digest(private_key: str | bytes | int, digest: str | bytes) -> dict:
    """Sign a 32-byte digest. Returns r, s, yParity and the 65-byte packed form.

    ``s`` is normalised into the lower half of the order (EIP-2): both s and n-s are
    valid, and a high-s signature is rejected outright by much of the ecosystem. Flipping
    s also flips the recovery parity, which is why both are adjusted together.
    """
    private = normalize_private_key(private_key)
    digest_bytes = to_bytes(digest)
    if len(digest_bytes) != 32:
        raise ValueError("digest must be exactly 32 bytes")
    z = int.from_bytes(digest_bytes, "big") % N

    for nonce in _rfc6979_nonces(private, z):
        point = multiply(G, nonce)
        if point is None:
            continue
        r = point[0] % N
        if r == 0:
            continue
        s = (pow(nonce, -1, N) * (z + r * private)) % N
        if s == 0:
            continue
        y_parity = (point[1] & 1) ^ (1 if point[0] >= N else 0)
        if s > HALF_N:
            s = N - s
            y_parity ^= 1
        return {
            "r": r,
            "s": s,
            "yParity": y_parity,
            "hex": "0x"
            + r.to_bytes(32, "big").hex()
            + s.to_bytes(32, "big").hex()
            + bytes([27 + y_parity]).hex(),
        }
    raise AssertionError("unreachable: RFC 6979 always terminates")


def ecrecover(digest: str | bytes, r: int, s: int, y_parity: int) -> str:
    """Recover the signer address, or raise if the signature is not on the curve."""
    if not 1 <= r < N or not 1 <= s < N:
        raise ValueError("signature component out of range")
    if y_parity not in (0, 1):
        raise ValueError("yParity must be 0 or 1")

    x = r
    alpha = (pow(x, 3, P) + 7) % P
    y = pow(alpha, (P + 1) // 4, P)
    if (y * y - alpha) % P != 0:
        raise ValueError("signature r is not an x-coordinate on the curve")
    if y % 2 != y_parity:
        y = P - y

    # Q = r^-1 * (s*R - z*G)
    z = int.from_bytes(to_bytes(digest), "big") % N
    r_inv = pow(r, -1, N)
    point = _to_affine(
        _jacobian_add(
            _jacobian_multiply((x, y, 1), s),
            _jacobian_multiply((GX, GY, 1), N - z),
        )
    )
    if point is None:
        raise ValueError("signature recovers to the point at infinity")
    recovered = multiply(point, r_inv)
    if recovered is None:
        raise ValueError("signature recovers to the point at infinity")
    return address_from_public_key(recovered)
