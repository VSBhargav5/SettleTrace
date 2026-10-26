"""Join bank records to an explicit one-to-one payout mapping, without guesses."""

import csv
from io import StringIO
import re

from .models import Deposit, InputError


BANK_FIELDS = ("bank_ref", "currency", "amount_minor")
MAPPING_FIELDS = ("bank_ref", "payout_id")
_INTEGER = re.compile(r"[+-]?[0-9]+\Z")


def _rows(data: bytes, source: str, fields: tuple[str, ...]) -> list[dict]:
    if not isinstance(data, bytes):
        raise TypeError("data must be an immutable bytes snapshot")
    reader = None

    def invalid(message: str, line: int | None = None) -> InputError:
        ending = line if line is not None else max(1, reader.reader.line_num if reader else 1)
        return InputError(f"{source}:{ending}: {message}")

    records = []
    try:
        with StringIO(data.decode("utf-8-sig"), newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            header = reader.fieldnames
            if header is None:
                raise invalid("empty file; expected a CSV header")
            if len(header) != len(set(header)):
                raise invalid("duplicate column names in CSV header")
            if set(header) != set(fields):
                raise invalid("expected exactly these columns: " + ", ".join(fields))
            for record in reader:
                line = reader.line_num
                if None in record or any(value is None for value in record.values()):
                    raise invalid("row width differs from the CSV header", line)
                for field, value in record.items():
                    if not value or value != value.strip():
                        raise invalid(f"{field} must be nonblank without surrounding whitespace", line)
                record["row"] = line
                records.append(record)
    except UnicodeDecodeError as exc:
        line = len(re.findall(rb"\r\n|\r|\n", exc.object[:exc.start])) + 1
        raise invalid("invalid UTF-8", line) from exc
    except csv.Error as exc:
        raise invalid(f"invalid CSV: {exc}") from exc
    return records


def map_bank(bank_data: bytes, mapping_data: bytes, bank_source: str = "bank.csv",
             mapping_source: str = "mapping.csv") -> tuple[list[Deposit], list[dict]]:
    """Map every bank record once and preserve physical input ending lines.

    The bank input is an explicitly prepared minor-unit extract, not a generic
    bank-provider export. Negative and zero deposits retain their signs. Every
    mapping must name an observed bank record; split and aggregated mappings are
    refused. Mapping records never establish that a payout actually arrived.
    """
    banks = _rows(bank_data, bank_source, BANK_FIELDS)
    mappings = _rows(mapping_data, mapping_source, MAPPING_FIELDS)
    if not banks:
        raise InputError(f"{bank_source}: no bank records to map")
    banks_by_ref = {}
    for record in banks:
        reference = record["bank_ref"]
        if reference in banks_by_ref:
            raise InputError(f"{bank_source}:{record['row']}: duplicate bank_ref: {reference!r}")
        banks_by_ref[reference] = record
    mappings_by_ref = {}
    payouts = set()
    for record in mappings:
        reference, payout = record["bank_ref"], record["payout_id"]
        prefix = f"{mapping_source}:{record['row']}: "
        if reference in mappings_by_ref:
            raise InputError(prefix + f"duplicate bank_ref: {reference!r}; one mapping per bank record is required")
        if payout in payouts:
            raise InputError(prefix + f"duplicate payout_id: {payout!r}; split deposits are unsupported")
        if reference not in banks_by_ref:
            raise InputError(prefix + f"bank_ref was not observed: {reference!r}")
        mappings_by_ref[reference] = record
        payouts.add(payout)

    deposits, audit = [], []
    for record in banks:
        reference = record["bank_ref"]
        prefix = f"{bank_source}:{record['row']}: "
        if reference not in mappings_by_ref:
            raise InputError(prefix + f"bank_ref has no explicit payout mapping: {reference!r}")
        amount = record["amount_minor"]
        if not _INTEGER.fullmatch(amount):
            raise InputError(prefix + "amount_minor must be an integer in minor units")
        mapping = mappings_by_ref[reference]
        try:
            deposit = Deposit(reference, mapping["payout_id"], record["currency"], int(amount), record["row"])
        except (InputError, ValueError) as exc:
            raise InputError(prefix + str(exc)) from exc
        deposits.append(deposit)
        audit.append({"bank_ref": reference, "payout_id": mapping["payout_id"],
                      "bank_row": record["row"], "mapping_row": mapping["row"]})
    return deposits, audit
