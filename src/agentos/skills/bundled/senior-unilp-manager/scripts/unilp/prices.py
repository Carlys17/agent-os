"""USD prices from GeckoTerminal — port of ``prices.mjs``.

Prices are a nice-to-have: a token the indexer has never seen returns nothing, and that
must never abort a read. Every failure path resolves to ``None`` and the caller renders
"n/a".
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .rpc import USER_AGENT

NATIVE = "0x0000000000000000000000000000000000000000"
_API = "https://api.geckoterminal.com/api/v2/simple/networks"
_TIMEOUT = 15
_BATCH = 30  # GeckoTerminal caps this endpoint at 30 addresses per call
_RETRIES = 2
_BACKOFF = 3.0
_MAX_BACKOFF = 15.0

_cache: dict[str, float | None] = {}


def _fetch_window(network: str, window: list[str]) -> dict:
    """One token_price call, retrying a 429 rather than degrading to n/a.

    The public endpoint allows roughly 30 calls a minute. Without this retry a burst
    (two commands in a row, or a sweep over many pools) silently turns every USD column
    into "n/a" — which reads as "this token has no price" rather than "ask again in a
    moment". Everything else still falls through to nulls: prices are decoration, and no
    read should ever fail because an indexer is down.
    """
    url = f"{_API}/{network}/token_price/{','.join(window)}"
    for attempt in range(_RETRIES + 1):
        try:
            request = urllib.request.Request(
                url, headers={"accept": "application/json", "User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                if not 200 <= response.status < 300:
                    return {}
                body = json.loads(response.read().decode("utf-8"))
                return body.get("data", {}).get("attributes", {}).get("token_prices") or {}
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == _RETRIES:
                return {}
            retry_after = (exc.headers or {}).get("retry-after")
            try:
                delay = min(float(retry_after), _MAX_BACKOFF)
            except (TypeError, ValueError):
                delay = _BACKOFF * (attempt + 1)
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return {}  # Network hiccup or timeout — the caller renders n/a.
    return {}


def fetch_usd_prices(chain: dict, addresses: list[str]) -> dict[str, float | None]:
    """Map lowercased address -> USD price (or None)."""
    seen: list[str] = []
    for address in addresses:
        if not address:
            continue
        lowered = address.lower()
        if lowered not in seen:
            seen.append(lowered)

    network = chain.get("geckoNetwork")
    out: dict[str, float | None] = {}
    missing: list[str] = []
    for address in seen:
        key = f"{network}:{address}"
        if key in _cache:
            out[address] = _cache[key]
        else:
            missing.append(address)
    if not missing or not network:
        return out

    # Native ETH is priced via the wrapped token.
    wrapped = (chain.get("wrappedNative") or "").lower()
    query = [wrapped if (a == NATIVE and wrapped) else a for a in missing]

    for start in range(0, len(query), _BATCH):
        window = query[start:start + _BATCH]
        originals = missing[start:start + _BATCH]
        prices = _fetch_window(network, window)

        for address, original in zip(window, originals):
            raw = prices.get(address)
            price: float | None
            try:
                price = None if raw is None or raw == "" else float(raw)
            except (TypeError, ValueError):
                price = None
            if price is not None and price != price:  # NaN
                price = None
            if price is not None and price in (float("inf"), float("-inf")):
                price = None
            out[original] = price
            _cache[f"{network}:{original}"] = price
    return out


def fetch_usd_price(chain: dict, address: str) -> float | None:
    """Convenience: price of a single token, or None."""
    return fetch_usd_prices(chain, [address]).get(address.lower())
