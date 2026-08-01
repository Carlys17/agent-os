"""USD prices from GeckoTerminal — port of ``prices.mjs``.

Prices are a nice-to-have: a token the indexer has never seen returns nothing, and that
must never abort a read. Every failure path resolves to ``None`` and the caller renders
"n/a".
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .rpc import USER_AGENT

NATIVE = "0x0000000000000000000000000000000000000000"
_API = "https://api.geckoterminal.com/api/v2/simple/networks"
_TIMEOUT = 15
_BATCH = 30  # GeckoTerminal caps this endpoint at 30 addresses per call
_RETRIES = 2
_BACKOFF = 3.0
_MAX_BACKOFF = 15.0

_cache: dict[str, float | None] = {}

# Every command is a fresh process, so an in-memory cache buys nothing across the two or
# three calls one task makes. GeckoTerminal's free endpoint starts refusing after a couple
# of requests in quick succession, and the obvious sequence — `pools`, then `ticks` on what
# it found — was reliably tripping it. A short-lived file the next process can read keeps
# that sequence to a single fetch.
_DISK_TTL = 60.0
_DISK_MAX_ENTRIES = 500

# Why the last lookup came back empty, so a caller that genuinely needs a price can say
# "wait a moment" instead of "this token has no price".
RATE_LIMITED = "rate_limited"
_last_failure: str | None = None


def _cache_path() -> Path:
    root = os.environ.get("UNILP_CACHE_DIR") or os.environ.get("XDG_CACHE_HOME")
    base = Path(root) if root else Path.home() / ".cache"
    return base / "agentos-unilp" / "prices.json"


def _disk_load() -> dict[str, list]:
    try:
        with _cache_path().open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}  # No cache, unreadable, or half-written — refetching is always correct.


def _disk_read(keys: list[str]) -> dict[str, float | None]:
    if not keys:
        return {}
    now = time.time()
    out: dict[str, float | None] = {}
    for key, entry in _disk_load().items():
        if key not in keys:
            continue
        try:
            stamp, price = entry
        except (TypeError, ValueError):
            continue
        if not isinstance(stamp, (int, float)) or now - stamp > _DISK_TTL:
            continue
        out[key] = None if price is None else float(price)
    return out


def _disk_write(fresh: dict[str, float | None]) -> None:
    """Merge ``fresh`` into the cache file. Best effort — never raise into a read."""
    if not fresh:
        return
    now = time.time()
    merged = {
        key: entry
        for key, entry in _disk_load().items()
        if isinstance(entry, list) and len(entry) == 2
        and isinstance(entry[0], (int, float)) and now - entry[0] <= _DISK_TTL
    }
    for key, price in fresh.items():
        merged[key] = [now, price]
    if len(merged) > _DISK_MAX_ENTRIES:
        newest = sorted(merged.items(), key=lambda kv: kv[1][0], reverse=True)
        merged = dict(newest[:_DISK_MAX_ENTRIES])
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic, so a process reading mid-write sees the old file rather than a truncated one.
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            json.dump(merged, handle)
            temporary = Path(handle.name)
        os.replace(temporary, path)
    except OSError:
        return


def last_failure() -> str | None:
    """``RATE_LIMITED`` if the most recent fetch was throttled, else ``None``."""
    return _last_failure


def price_unavailable_message(chain: dict, quote_symbol: str) -> str:
    """Explain a missing quote price in terms the caller can act on."""
    if _last_failure == RATE_LIMITED:
        return (
            f"the price indexer is rate-limiting us, so {quote_symbol} has no USD price "
            f"right now — this is temporary. Wait ~60s and run the same command again; "
            f"prices are cached for {int(_DISK_TTL)}s once a call gets through. To skip "
            f"prices entirely, pass --tick-lower/--tick-upper instead of --mcap-*"
        )
    network = chain.get("geckoNetwork") or "this chain"
    return (
        f"no USD price for {quote_symbol} — GeckoTerminal has not indexed it on "
        f"{network}. Market-cap targets need a priced quote currency; pass "
        f"--tick-lower/--tick-upper directly instead"
    )


def _fetch_window(network: str, window: list[str]) -> dict:
    """One token_price call, retrying a 429 rather than degrading to n/a.

    The public endpoint allows roughly 30 calls a minute. Without this retry a burst
    (two commands in a row, or a sweep over many pools) silently turns every USD column
    into "n/a" — which reads as "this token has no price" rather than "ask again in a
    moment". Everything else still falls through to nulls: prices are decoration, and no
    read should ever fail because an indexer is down.
    """
    global _last_failure
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
            if exc.code == 429:
                _last_failure = RATE_LIMITED
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

    on_disk = _disk_read([f"{network}:{address}" for address in missing])
    if on_disk:
        still_missing = []
        for address in missing:
            key = f"{network}:{address}"
            if key in on_disk:
                out[address] = on_disk[key]
                _cache[key] = on_disk[key]
            else:
                still_missing.append(address)
        missing = still_missing
    if not missing:
        return out

    # Native ETH is priced via the wrapped token.
    wrapped = (chain.get("wrappedNative") or "").lower()
    query = [wrapped if (a == NATIVE and wrapped) else a for a in missing]

    fresh: dict[str, float | None] = {}
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
            # Only a real answer is worth persisting: caching the None a rate-limit
            # produced would hand the next process the same dead end for a full TTL.
            if price is not None:
                fresh[f"{network}:{original}"] = price
    _disk_write(fresh)
    return out


def fetch_usd_price(chain: dict, address: str) -> float | None:
    """Convenience: price of a single token, or None."""
    return fetch_usd_prices(chain, [address]).get(address.lower())
