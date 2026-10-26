"""Convert supported major-unit CSV amounts without floats or rounding."""

import re

from .models import InputError, MAX_MINOR_ABS, SUPPORTED_CURRENCIES


_AMOUNT = re.compile(r"([+-]?)([0-9]+)(?:\.([0-9]{1,2}))?\Z")
_COMMA_AMOUNT = re.compile(r"([+-]?)([0-9]+)(?:,([0-9]{1,2}))?\Z")


def to_minor(value: str, currency: str, *, decimal_separator: str = ".") -> int:
    """Parse only the explicitly selected decimal separator, without guessing."""
    if decimal_separator not in (".", ","):
        raise InputError("decimal_separator must be '.' or ','")
    if not isinstance(currency, str) or currency not in SUPPORTED_CURRENCIES:
        raise InputError("Unsupported currency; expected USD, EUR, GBP, or INR")
    pattern = _AMOUNT if decimal_separator == "." else _COMMA_AMOUNT
    match = pattern.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise InputError("Amount must be an ASCII decimal with at most two fractional digits")
    sign, whole, fraction = match.groups()
    try:
        amount = int(whole) * 100 + int((fraction or "").ljust(2, "0"))
    except ValueError as exc:
        raise InputError("Amount is too large to parse") from exc
    if amount >= MAX_MINOR_ABS:
        raise InputError("Amount exceeds the supported 128-digit minor-unit limit")
    return -amount if sign == "-" else amount
