"""Reproduce an explicit bank mapping pack from supplied immutable source bytes."""

import csv
import hashlib
from io import StringIO
from pathlib import Path

from .bank import map_bank
from .ingest import DEPOSIT_FIELDS, parse_deposits
from .models import Deposit
from .verify import _fingerprint, _integer, _json, _read, _require


def render_bank(deposits: list[Deposit]) -> str:
    """Render machine CSV preserving identifiers and exact signed minor units."""
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=DEPOSIT_FIELDS)
    writer.writeheader()
    for deposit in deposits:
        writer.writerow({field: getattr(deposit, field) for field in DEPOSIT_FIELDS})
    return stream.getvalue()


def verify_bank_map(bundle: Path, bank_data: bytes, mapping_data: bytes) -> dict:
    """Verify bytes and replay the stated join; attribution itself stays unproven.

    Only fixed pack filenames are opened. Source names are descriptive basenames,
    never paths to follow. Use a stable directory; this does not lock concurrent
    writers, authenticate a pack, or establish the operator's mapping is true.
    """
    directory = Path(bundle)
    _require(not directory.is_symlink() and directory.is_dir(), "Expected a non-symlink bank mapping directory")
    audit = _json(_read(directory / "audit.json"), "audit.json")
    _require(set(audit) == {"schema_version", "tool_version", "inputs", "outputs", "rows"},
             "Unsupported bank mapping audit fields")
    _require(audit["schema_version"] == "1" and isinstance(audit["tool_version"], str)
             and bool(audit["tool_version"].strip()), "Unsupported or malformed bank mapping audit version")
    inputs, outputs = audit["inputs"], audit["outputs"]
    _require(isinstance(inputs, dict) and set(inputs) == {"bank", "mapping"},
             "Bank mapping audit must describe exactly bank and mapping inputs")
    _require(isinstance(outputs, dict) and set(outputs) == {"bank.csv"},
             "Bank mapping audit must describe exactly bank.csv")
    for label, data in (("bank", bank_data), ("mapping", mapping_data)):
        if not isinstance(data, bytes):
            raise TypeError("source data must be immutable bytes snapshots")
        fingerprint = inputs[label]
        _fingerprint(fingerprint, source=True)
        _require(set(fingerprint) == {"name", "size_bytes", "sha256"}, "Unsupported source fingerprint fields")
        _require(len(data) == fingerprint["size_bytes"], f"Input size mismatch: {label}")
        _require(hashlib.sha256(data).hexdigest() == fingerprint["sha256"], f"Input hash mismatch: {label}")
    output = outputs["bank.csv"]
    _fingerprint(output, source=False)
    _require(set(output) == {"sha256"}, "Unsupported output fingerprint fields")
    canonical = _read(directory / "bank.csv")
    _require(hashlib.sha256(canonical).hexdigest() == output["sha256"], "Output hash mismatch: bank.csv")
    deposits, source_rows = map_bank(bank_data, mapping_data)
    expected = render_bank(deposits).encode("utf-8")
    _require(canonical == expected, "bank.csv disagrees with the replayed explicit mapping")
    normalized = parse_deposits(expected, "bank.csv")
    expected_rows = [{**row, "canonical_row": deposit.row} for row, deposit in zip(source_rows, normalized)]
    rows = audit["rows"]
    _require(isinstance(rows, list), "Malformed bank mapping audit rows")
    for row in rows:
        _require(isinstance(row, dict)
                 and set(row) == {"bank_ref", "payout_id", "bank_row", "mapping_row", "canonical_row"}
                 and all(isinstance(row[key], str) and bool(row[key]) for key in ("bank_ref", "payout_id"))
                 and all(_integer(row[key], minimum=1) for key in ("bank_row", "mapping_row", "canonical_row")),
                 "Malformed bank mapping audit row")
    _require(rows == expected_rows, "Audit rows disagree with the replayed physical source and canonical rows")
    return audit
