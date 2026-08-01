"""secp256k1 ECDSA — the one piece viem provided that the stdlib does not.

Only three operations are needed: derive an address from a private key, sign a 32-byte
digest deterministically (RFC 6979, so the same plan always produces the same signature),
and recover the signer from a signature. The last one is not decoration — every signature
this module produces is recovered and checked against the expected address before the
transaction is allowed anywhere near the network. That check costs ~12 ms and removes the
entire class of "wrong v, wrong s normalisation, wrong sighash" bugs, which lose money
silently.

Caveat that must stay visible: pure-Python big-integer arithmetic is **not constant time**.
A local attacker who can measure this process precisely could in principle learn something
about the key. Python has no fix for that. The mitigation is operational — this is a
hot-wallet key for LP operations, not a treasury key.
"""

from __future__ import annotations

import hashlib
import hmac

from .hexutil import checksum_address, strip0x, to_bytes
from .keccak import keccak256

# Curve parameters (SEC 2, secp256k1). a = 0, b = 7.
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
G = (GX, GY)
HALF_N = N // 2


# ---------------------------------------------------------------------------
# Curve arithmetic, in Jacobian coordinates
# ---------------------------------------------------------------------------
#
# Affine addition needs a modular inverse per step; at 256 doublings that dominates the
# runtime. Jacobian coordinates defer all of it to a single inverse at the end.
# The point at infinity is any triple with y == 0.


def _jacobian_double(point: tuple[int, int, int]) -> tuple[int, int, int]:
    x, y, z = point
    if not y:
        return (0, 0, 0)
    ysq = (y * y) % P
    s = (4 * x * ysq) % P
    m = (3 * x * x) % P  # + a*z^4, and a == 0 on this curve
    nx = (m * m - 2 * s) % P
    ny = (m * (s - nx) - 8 * ysq * ysq) % P
    nz = (2 * y * z) % P
    return (nx, ny, nz)


def _jacobian_add(p: tuple[int, int, int], q: tuple[int, int, int]) -> tuple[int, int, int]:
    if not p[1]:
        return q
    if not q[1]:
        return p
    u1 = (p[0] * q[2] * q[2]) % P
    u2 = (q[0] * p[2] * p[2]) % P
    s1 = (p[1] * q[2] * q[2] * q[2]) % P
    s2 = (q[1] * p[2] * p[2] * p[2]) % P
    if u1 == u2:
        # Same x: either the same point (double it) or a point and its negation (infinity).
        return _jacobian_double(p) if s1 == s2 else (0, 0, 1)
    h = u2 - u1
    r = s2 - s1
    h2 = (h * h) % P
    h3 = (h * h2) % P
    u1h2 = (u1 * h2) % P
    nx = (r * r - h3 - 2 * u1h2) % P
    ny = (r * (u1h2 - nx) - s1 * h3) % P
    nz = (h * p[2] * q[2]) % P
    return (nx, ny, nz)


def _jacobian_multiply(point: tuple[int, int, int], scalar: int) -> tuple[int, int, int]:
    if point[1] == 0 or scalar == 0:
        return (0, 0, 1)
    if scalar == 1:
        return point
    if scalar < 0 or scalar >= N:
        return _jacobian_multiply(point, scalar % N)
    half = _jacobian_multiply(point, scalar // 2)
    if scalar % 2 == 0:
        return _jacobian_double(half)
    return _jacobian_add(_jacobian_double(half), point)


def _to_affine(point: tuple[int, int, int]) -> tuple[int, int] | None:
    x, y, z = point
    if z == 0 or y == 0:
        return None
    inv = pow(z, -1, P)
    inv2 = (inv * inv) % P
    return ((x * inv2) % P, (y * inv2 % P) * inv % P)


def multiply(point: tuple[int, int], scalar: int) -> tuple[int, int] | None:
    """Scalar multiplication on the curve. ``None`` is the point at infinity."""
    return _to_affine(_jacobian_multiply((point[0], point[1], 1), scalar))


def add(a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int] | None:
    """Point addition. ``None`` is the point at infinity."""
    return _to_affine(_jacobian_add((a[0], a[1], 1), (b[0], b[1], 1)))


# ---------------------------------------------------------------------------
# Keys and addresses
# ---------------------------------------------------------------------------


def normalize_private_key(private_key: str | bytes | int) -> int:
    """Parse a key in any accepted shape and range-check it.

    ``0`` and anything at or above the group order are not valid scalars; a node would
    accept the resulting signature and it would recover to the wrong address.
    """
    if isinstance(private_key, int):
        value = private_key
    elif isinstance(private_key, (bytes, bytearray)):
        value = int.from_bytes(private_key, "big")
    else:
        text = strip0x(private_key.strip().strip('"').strip("'"))
        if len(text) != 64:
            raise ValueError("private key must be 32 bytes")
        value = int(text, 16)
    if not 1 <= value < N:
        raise ValueError("private key out of range for secp256k1")
    return value


def public_key(private_key: str | bytes | int) -> tuple[int, int]:
    point = multiply(G, normalize_private_key(private_key))
    if point is None:  # Unreachable for an in-range scalar; a guard, not a branch.
        raise ValueError("private key produced the point at infinity")
    return point


def address_from_public_key(point: tuple[int, int]) -> str:
    """Last 20 bytes of keccak over the 64-byte uncompressed key, EIP-55 checksummed."""
    body = point[0].to_bytes(32, "big") + point[1].to_bytes(32, "big")
    return checksum_address("0x" + strip0x(keccak256(body))[24:])


def account_from_private_key(private_key: str | bytes | int) -> dict:
    """The signer identity. Deliberately does not carry the key in the returned dict."""
    point = public_key(private_key)
    return {
        "address": address_from_public_key(point),
        "publicKey": "0x" + point[0].to_bytes(32, "big").hex() + point[1].to_bytes(32, "big").hex(),
    }


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
