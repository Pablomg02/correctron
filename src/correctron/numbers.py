"""Decimal parsing, formatting and rounding of grades (D21)."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

_NUMBER_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


def parse_number(raw: str) -> Decimal | None:
    """Parse a cell: blank gives None; accepts dot or comma decimals.

    Raises ValueError when both separators appear or the text is not numeric.
    """
    text = raw.strip()
    if not text:
        return None
    if "," in text and "." in text:
        raise ValueError(f"número ambiguo: {raw!r}")
    text = text.replace(",", ".")
    if not _NUMBER_RE.match(text):
        raise ValueError(f"no es un número: {raw!r}")
    value = Decimal(text)
    return Decimal(0) if value == 0 else value


def format_number(d: Decimal) -> str:
    """Format without exponent and without trailing zeros (8.00 -> 8, 10 -> 10)."""
    if d == 0:
        return "0"
    text = format(d.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def round_grade(d: Decimal, decimales: int) -> Decimal:
    """Round to `decimales` places with ROUND_HALF_UP."""
    return d.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)
