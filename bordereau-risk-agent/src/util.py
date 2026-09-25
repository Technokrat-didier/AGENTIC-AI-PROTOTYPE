"""Shared parsing / normalization helpers."""

from __future__ import annotations

import re
from datetime import date, datetime

BASE_CURRENCY = "USD"

# Simple static FX table (prototype). In production pull daily rates.
FX_TO_USD = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "CHF": 1.12,
    "CAD": 0.74,
}

_CURRENCY_RE = re.compile(r"\b(USD|EUR|GBP|CHF|CAD)\b")


def parse_number(value):
    """Parse '4,500,000', '12.5%', '3200000' -> float. Returns None if empty/invalid."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    # Grab the FIRST numeric token; treat it as a percentage only if that very
    # token is immediately followed by '%'. This avoids mis-reading strings like
    # "USD 42,000 (100% basis)" as a percentage.
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?\s*(%)?", s)
    if not m:
        return None
    num = m.group(0).replace(",", "").replace(" ", "").rstrip("%")
    try:
        n = float(num)
    except ValueError:
        return None
    return n / 100.0 if m.group(1) else n


def parse_date(value):
    """Parse several date layouts into a date object; returns None on failure."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def detect_currency(text, default=None):
    if not text:
        return default
    m = _CURRENCY_RE.search(str(text))
    return m.group(1) if m else default


def to_base_currency(amount, currency):
    """Convert an amount to the base currency. Returns (converted, rate, known)."""
    if amount is None:
        return None, None, False
    cur = (currency or BASE_CURRENCY).upper()
    rate = FX_TO_USD.get(cur)
    if rate is None:
        return amount, None, False
    return amount * rate, rate, True
