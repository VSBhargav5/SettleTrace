"""Validated reconciliation records; every amount is an integer minor unit."""

from dataclasses import dataclass


SUPPORTED_CURRENCIES = frozenset({"USD", "EUR", "GBP", "INR"})
ENTRY_KINDS = frozenset({"charge", "refund", "dispute", "adjustment", "fee"})


class InputError(ValueError):
    """The supplied records cannot be reconciled without guessing."""


def _identifier(name: str, value: str, *, allow_empty: bool = False) -> None:
    if not isinstance(value, str) or (not value.strip() and not (allow_empty and value == "")):
        raise InputError(f"{name} must be a nonblank string" + (" or empty" if allow_empty else ""))


def _integer(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise InputError(f"{name} must be an integer minor-unit amount")


def _currency_and_row(currency: str, row: int) -> None:
    if not isinstance(currency, str) or currency not in SUPPORTED_CURRENCIES:
        raise InputError("currency must be one of USD, EUR, GBP, INR (uppercase)")
    _integer("row", row)
    if row < 0:
        raise InputError("row must be nonnegative")


@dataclass(frozen=True)
class Sale:
    """A captured-payment record; sale_id is unique, not a multi-capture order ID."""

    sale_id: str
    payment_ref: str
    currency: str
    gross_minor: int
    row: int = 0

    def __post_init__(self) -> None:
        _identifier("sale_id", self.sale_id)
        _identifier("payment_ref", self.payment_ref)
        _currency_and_row(self.currency, self.row)
        _integer("gross_minor", self.gross_minor)
        if self.gross_minor <= 0:
            raise InputError("sale gross_minor must be positive")


@dataclass(frozen=True)
class Entry:
    transaction_id: str
    payment_ref: str
    payout_id: str
    kind: str
    currency: str
    gross_minor: int
    fee_minor: int
    net_minor: int
    row: int = 0

    def __post_init__(self) -> None:
        _identifier("transaction_id", self.transaction_id)
        if not isinstance(self.kind, str) or self.kind not in ENTRY_KINDS:
            raise InputError("kind must be charge, refund, dispute, adjustment, or fee")
        _identifier("payment_ref", self.payment_ref, allow_empty=self.kind in {"adjustment", "fee"})
        _identifier("payout_id", self.payout_id, allow_empty=True)
        _currency_and_row(self.currency, self.row)
        for name in ("gross_minor", "fee_minor", "net_minor"):
            _integer(name, getattr(self, name))
        if self.kind == "charge" and self.gross_minor <= 0:
            raise InputError("charge gross_minor must be positive")
        if self.kind in {"refund", "dispute"} and self.gross_minor >= 0:
            raise InputError(f"{self.kind} gross_minor must be negative")
        if self.kind == "fee" and self.gross_minor != 0:
            raise InputError("fee gross_minor must be zero; record the signed fee in fee_minor")
        if self.net_minor != self.gross_minor - self.fee_minor:
            raise InputError("net_minor must equal gross_minor - fee_minor")


@dataclass(frozen=True)
class Deposit:
    bank_ref: str
    payout_id: str
    currency: str
    amount_minor: int
    row: int = 0

    def __post_init__(self) -> None:
        _identifier("bank_ref", self.bank_ref)
        _identifier("payout_id", self.payout_id)
        _currency_and_row(self.currency, self.row)
        _integer("amount_minor", self.amount_minor)
