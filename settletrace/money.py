"""Convert supported major-unit CSV amounts without floats or rounding."""

import re

from .models import InputError, SUPPORTED_CURRENCIES


_AMOUNT = re.compile(r"([+-]?)([0-9]+)(?:\.([0-9]{1,2}))?\Z")


def to_minor(value: str, currency: str) -> int:
    if not isinstance(currency, str) or currency not in SUPPORTED_CURRENCIES:
        raise InputError("Unsupported currency; expected USD, EUR, GBP, or INR")
    match = _AMOUNT.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise InputError("Amount must be an ASCII decimal with at most two fractional digits")
    sign, whole, fraction = match.groups()
    try:
        amount = int(whole) * 100 + int((fraction or "").ljust(2, "0"))
    except ValueError as exc:
        raise InputError("Amount is too large to parse") from exc
    return -amount if sign == "-" else amount
