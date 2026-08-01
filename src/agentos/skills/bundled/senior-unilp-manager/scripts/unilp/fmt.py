"""Arg parsing, number formatting, and table rendering — port of ``util.mjs``.

Shared by both entrypoints.
"""

from __future__ import annotations

import math
import os
import sys
from typing import Any

from .hexutil import format_units, parse_amount  # noqa: F401 — re-exported

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------


def parse_args(argv: list[str]) -> dict:
    """Parse ``--flag value`` / ``--flag=value`` / ``--bool`` plus positionals."""
    out: dict[str, Any] = {"_": []}
    index = 0
    while index < len(argv):
        arg = argv[index]
        if not arg.startswith("--"):
            out["_"].append(arg)
            index += 1
            continue
        body = arg[2:]
        if "=" in body:
            name, _, value = body.partition("=")
            out[name] = value
            index += 1
            continue
        nxt = argv[index + 1] if index + 1 < len(argv) else None
        if nxt is None or nxt.startswith("--"):
            out[body] = True
            index += 1
        else:
            out[body] = nxt
            index += 2
    return out


def require_arg(args: dict, name: str, hint: str = "") -> Any:
    value = args.get(name)
    if value is None or value is True:
        raise ValueError(f"missing --{name}{f' ({hint})' if hint else ''}")
    return value


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def fmt_units(value: int, decimals: int, max_frac: int = 6) -> str:
    raw = int(value)
    text = format_units(raw, int(decimals))
    negative = text.startswith("-")
    if negative:
        text = text[1:]
    int_part, _, frac = text.partition(".")
    grouped = f"{int(int_part):,}"
    trimmed = frac[:max_frac].rstrip("0")
    if not trimmed and int_part == "0" and raw != 0:
        # Sub-display-precision but non-zero: keep 3 significant digits rather than
        # printing 0, which would read as "this position holds nothing".
        lead = next((i for i, ch in enumerate(frac) if ch in "123456789"), -1)
        if lead != -1:
            trimmed = frac[:lead + 3].rstrip("0")
    body = f"{grouped}.{trimmed}" if trimmed else grouped
    return f"-{body}" if negative else body


def _to_precision(value: float, precision: int) -> str:
    """JavaScript ``Number.prototype.toPrecision`` — fixed unless the exponent falls
    outside ``[-6, precision)``, which is where Python's ``%g`` disagrees."""
    if value == 0:
        return f"{0:.{precision - 1}f}"
    mantissa, _, exponent = f"{value:.{precision - 1}e}".partition("e")
    exp = int(exponent)
    if exp < -6 or exp >= precision:
        sign = "+" if exp >= 0 else "-"
        return f"{mantissa}e{sign}{abs(exp)}"
    return f"{value:.{max(precision - 1 - exp, 0)}f}"


def fmt_usd(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "∞" if value == float("inf") else "n/a"
    if value == 0:
        return "$0"
    magnitude = abs(value)
    if magnitude >= 1e12:
        return f"${value / 1e12:.2f}T"
    if magnitude >= 1e9:
        return f"${value / 1e9:.2f}B"
    if magnitude >= 1e6:
        return f"${value / 1e6:.2f}M"
    if magnitude >= 1e3:
        return f"${value / 1e3:.2f}K"
    if magnitude >= 1:
        return f"${value:.2f}"
    return f"${_to_precision(value, 3)}"


def fmt_band(band: dict | None) -> str:
    """Market-cap band as a single cell, e.g. "$19.98K → $1.20B"."""
    if not band:
        return "n/a"
    return f"{fmt_usd(band.get('from'))} → {fmt_usd(band.get('to'))}"


def short(addr: str | None) -> str:
    if not addr:
        return ""
    return f"{addr[:6]}…{addr[-4:]}"


def short_id(value: str | None) -> str:
    if not value:
        return ""
    return f"{value[:10]}…{value[-6:]}"


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def render_table(columns: list[dict], rows: list[dict]) -> str:
    """``columns`` is [{key, label, align?}]; row values are already stringified."""
    if not rows:
        return "  (none)"

    def cell_of(row: dict, column: dict) -> str:
        # `or ""` would be wrong here: a literal 0 is falsy but must still print.
        value = row.get(column["key"])
        return "" if value is None else str(value)

    widths = [
        max(len(c["label"]), *(len(cell_of(r, c)) for r in rows))
        for c in columns
    ]

    def line(cells: list) -> str:
        parts = []
        for i, cell in enumerate(cells):
            text = str(cell)
            parts.append(text.rjust(widths[i]) if columns[i].get("align") == "right"
                         else text.ljust(widths[i]))
        return "  " + "  ".join(parts)

    head = line([c["label"] for c in columns])
    rule = "  " + "  ".join("─" * w for w in widths)
    body = [line([cell_of(r, c) for c in columns]) for r in rows]
    return "\n".join([head, rule, *body])


def heading(title: str) -> str:
    return f"\n=== {title} ==="


def render_kv(pairs: list) -> str:
    """Aligned ``label : value`` block, matching the capu-vault output style."""
    width = max(len(k) for k, _ in pairs)
    return "\n".join(f"  {k.ljust(width)} : {v}" for k, v in pairs)


def json_safe(value: Any) -> Any:
    """Make a structure JSON-serialisable the way the Node build did.

    The Node original stringified every BigInt and left Numbers alone; Python has one
    integer type, so callers must ``str()`` the values that were BigInt there. This
    only handles the cases Python cannot serialise at all: infinities and sets.
    """
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, float):
        if value == float("inf"):
            return "Infinity"
        if value == float("-inf"):
            return "-Infinity"
        if value != value:
            return None
    return value


def die(err: BaseException | str) -> None:
    message = str(err) or err.__class__.__name__
    print(f"\nERROR: {message}", file=sys.stderr)
    if os.environ.get("UNILP_DEBUG"):
        import traceback
        if isinstance(err, BaseException):
            traceback.print_exception(type(err), err, err.__traceback__)
    sys.exit(1)
