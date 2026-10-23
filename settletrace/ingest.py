"""Read SettleTrace's canonical CSVs, not raw processor report exports.

Headers may appear in any order, but names must match the documented schema
exactly. Text is never trimmed, case-folded, or fuzzy-matched; surrounding
whitespace is rejected. Amounts are ASCII base-10 integer minor units with an
optional leading sign. UTF-8 with or without a BOM is accepted. A header-only
file is an intentional empty dataset. As in Python's CSV reader, blank separator
lines are ignored. Returned records preserve the physical line on which each
CSV record ends, including quoted records spanning multiple lines. Error
messages also include the supplied source label. Byte parsers consume exactly
the supplied immutable snapshot; path loaders read their input once.
"""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path
import re
from typing import Callable, TypeVar

from .models import Deposit, Entry, InputError, SUPPORTED_CURRENCIES, Sale


SALES_FIELDS = ("sale_id", "payment_ref", "currency", "gross_minor")
ENTRY_FIELDS = (
    "transaction_id", "payment_ref", "payout_id", "kind", "currency",
    "gross_minor", "fee_minor", "net_minor",
)
DEPOSIT_FIELDS = ("bank_ref", "payout_id", "currency", "amount_minor")
_INTEGER = re.compile(r"[+-]?[0-9]+\Z")
_Record = TypeVar("_Record")


def _parse(
    data: bytes,
    source: str,
    fields: tuple[str, ...],
    amount_fields: tuple[str, ...],
    record_type: Callable[..., _Record],
) -> list[_Record]:
    if not isinstance(data, bytes):
        raise TypeError("data must be an immutable bytes snapshot")
    records = []
    reader = None

    def invalid(message: str, line: int | None = None) -> InputError:
        # DictReader.line_num updates only after successful records; the wrapped
        # reader also advances when malformed CSV raises before returning a row.
        source_line = line if line is not None else max(1, reader.reader.line_num if reader else 1)
        return InputError(f"{source}:{source_line}: {message}")

    try:
        with StringIO(data.decode("utf-8-sig"), newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            header = reader.fieldnames
            if header is None:
                raise invalid("empty file; expected a CSV header")
            if len(header) != len(set(header)):
                raise invalid("duplicate column names in CSV header")
            missing = sorted(set(fields) - set(header))
            extra = sorted(set(header) - set(fields))
            if missing or extra:
                problems = []
                if missing:
                    problems.append(f"missing columns: {', '.join(missing)}")
                if extra:
                    problems.append(f"unexpected columns: {', '.join(extra)}")
                raise invalid("; ".join(problems))

            for row in reader:
                line = reader.line_num
                if None in row:
                    raise invalid("row has more cells than the CSV header", line)
                if any(value is None for value in row.values()):
                    raise invalid("row has fewer cells than the CSV header", line)

                values: dict[str, str | int] = {}
                for field in fields:
                    value = row[field]
                    if field in amount_fields:
                        if not _INTEGER.fullmatch(value):
                            raise invalid(f"{field} must be an integer in minor units", line)
                        try:
                            values[field] = int(value)
                        except ValueError as exc:
                            raise invalid(f"{field} is too large to parse as an integer", line) from exc
                    else:
                        if value != value.strip():
                            raise invalid(f"{field} has surrounding whitespace", line)
                        values[field] = value

                if values["currency"] not in SUPPORTED_CURRENCIES:
                    supported = ", ".join(sorted(SUPPORTED_CURRENCIES))
                    raise invalid(f"currency must be one of {supported} (uppercase)", line)
                try:
                    records.append(record_type(**values, row=line))
                except InputError as exc:
                    raise invalid(str(exc), line) from exc
    except UnicodeDecodeError as exc:
        prefix = exc.object[:exc.start]
        line = len(re.findall(rb"\r\n|\r|\n", prefix)) + 1
        raise invalid(f"invalid UTF-8: {exc}", line) from exc
    except csv.Error as exc:
        raise invalid(f"invalid CSV: {exc}") from exc
    return records


def load_sales(path: Path | str) -> list[Sale]:
    """Load a canonical sales ledger with integer minor-unit gross amounts."""
    source = Path(path)
    return parse_sales(source.read_bytes(), str(source))


def load_entries(path: Path | str) -> list[Entry]:
    """Load canonical processor activity without inferring payout attribution."""
    source = Path(path)
    return parse_entries(source.read_bytes(), str(source))


def load_deposits(path: Path | str) -> list[Deposit]:
    """Load canonical bank deposits with explicit payout references."""
    source = Path(path)
    return parse_deposits(source.read_bytes(), str(source))


def parse_sales(data: bytes, source: str) -> list[Sale]:
    """Parse an immutable sales snapshot; source is an error-message label."""
    return _parse(data, source, SALES_FIELDS, ("gross_minor",), Sale)


def parse_entries(data: bytes, source: str) -> list[Entry]:
    """Parse an immutable processor snapshot without reading its source path."""
    return _parse(data, source, ENTRY_FIELDS, ("gross_minor", "fee_minor", "net_minor"), Entry)


def parse_deposits(data: bytes, source: str) -> list[Deposit]:
    """Parse an immutable bank snapshot without reading its source path."""
    return _parse(data, source, DEPOSIT_FIELDS, ("amount_minor",), Deposit)
