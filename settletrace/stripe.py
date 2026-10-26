"""Fail-closed import of the supported itemized automatic-payout CSV subset."""

import csv
from io import StringIO
import re

from .models import Entry, InputError
from .money import to_minor


REQUIRED_FIELDS = (
    "balance_transaction_id", "charge_id", "automatic_payout_id",
    "reporting_category", "currency", "gross", "fee", "net",
)


def parse_stripe(data: bytes, source: str, *, decimal_separator: str = ".") -> list[Entry]:
    """Parse immutable report bytes; extra columns and blank lines are allowed.

    References are explicit and never normalized. Evidence uses each record's
    ending physical line. Charges, refunds and debit disputes are supported;
    refund/dispute gross must be negative. Select dot or comma decimal amounts
    explicitly; the CSV column delimiter is always a comma.
    """
    if not isinstance(data, bytes):
        raise TypeError("data must be an immutable bytes snapshot")
    if decimal_separator not in (".", ","):
        raise InputError(f"{source}:1: decimal_separator must be '.' or ','")
    reader = None

    def invalid(message: str, line: int | None = None) -> InputError:
        position = line if line is not None else max(1, reader.reader.line_num if reader else 1)
        return InputError(f"{source}:{position}: {message}")

    records = []
    seen = set()
    try:
        with StringIO(data.decode("utf-8-sig"), newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            header = reader.fieldnames
            if header is None:
                raise invalid("empty file; expected a Stripe CSV header")
            if len(header) != len(set(header)):
                raise invalid("duplicate column names in CSV header")
            missing = sorted(set(REQUIRED_FIELDS) - set(header))
            if missing:
                raise invalid(f"missing columns: {', '.join(missing)}")
            for row in reader:
                line = reader.line_num
                if None in row or any(value is None for value in row.values()):
                    raise invalid("row cell count does not match the CSV header", line)
                for field in REQUIRED_FIELDS:
                    if row[field] != row[field].strip():
                        raise invalid(f"{field} has surrounding whitespace", line)
                for field in ("balance_transaction_id", "charge_id", "automatic_payout_id"):
                    if not row[field]:
                        raise invalid(f"{field} must be nonblank", line)
                transaction_id = row["balance_transaction_id"]
                if transaction_id in seen:
                    raise invalid(f"duplicate balance_transaction_id: {transaction_id}", line)
                if row["reporting_category"] not in {"charge", "refund", "dispute"}:
                    raise invalid(f"unsupported reporting_category: {row['reporting_category']!r}", line)
                raw_currency = row["currency"]
                if re.fullmatch(r"[A-Za-z]{3}", raw_currency) is None:
                    raise invalid("currency must be a supported three-letter ASCII code", line)
                currency = raw_currency.upper()
                try:
                    amounts = {field: to_minor(row[field], currency, decimal_separator=decimal_separator)
                               for field in ("gross", "fee", "net")}
                    entry = Entry(
                        transaction_id=transaction_id,
                        payment_ref=row["charge_id"],
                        payout_id=row["automatic_payout_id"],
                        kind=row["reporting_category"],
                        currency=currency,
                        gross_minor=amounts["gross"],
                        fee_minor=amounts["fee"],
                        net_minor=amounts["net"],
                        row=line,
                    )
                except InputError as exc:
                    raise invalid(str(exc), line) from exc
                records.append(entry)
                seen.add(transaction_id)
    except UnicodeDecodeError as exc:
        line = len(re.findall(rb"\r\n|\r|\n", exc.object[:exc.start])) + 1
        raise invalid(f"invalid UTF-8: {exc}", line) from exc
    except csv.Error as exc:
        raise invalid(f"invalid CSV: {exc}") from exc
    return records
