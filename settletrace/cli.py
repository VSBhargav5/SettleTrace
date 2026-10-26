"""Command-line entry point with explicit outcome codes and reproducible bundles."""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys

from . import __version__
from .compare import compare_findings
from .engine import reconcile
from .ingest import ENTRY_FIELDS, parse_deposits, parse_entries, parse_sales
from .models import InputError
from .report import findings_csv, render_html
from .stripe import parse_stripe
from .verify import verify_bundle, verify_sources


DEFAULT_MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_CAPTURE_BYTES = 256 * 1024 * 1024


def _positive_limit(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("byte limit must be a positive integer") from exc
    if not 0 < result <= MAX_CAPTURE_BYTES:
        raise argparse.ArgumentTypeError(f"byte limit must be between 1 and {MAX_CAPTURE_BYTES}")
    return result


def _capture(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise InputError(f"{path}: input exceeds --max-input-bytes={limit}")
    return data


def _fingerprint(path: Path, data: bytes) -> dict:
    return {"name": path.name, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}


def _json(value: dict) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def _input_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--sales", type=Path, required=True)
    command.add_argument("--processor", type=Path, required=True)
    command.add_argument("--bank", type=Path, required=True)
    command.add_argument("--processor-format", choices=("canonical", "stripe-payout-itemized-7"), default="canonical")
    command.add_argument("--decimal-separator", choices=(".", ","), default=".")
    command.add_argument("--max-input-bytes", type=_positive_limit, default=DEFAULT_MAX_INPUT_BYTES,
                         help="Maximum bytes captured per input (default: 16777216)")


def _read_inputs(args: argparse.Namespace) -> tuple:
    paths = {"sales": args.sales, "processor": args.processor, "bank": args.bank}
    # Each immutable snapshot supplies both the hash and the parsed records.
    snapshots = {name: _capture(path, args.max_input_bytes) for name, path in paths.items()}
    fingerprints = {name: _fingerprint(path, snapshots[name]) for name, path in paths.items()}
    sales = parse_sales(snapshots["sales"], str(args.sales))
    if args.processor_format == "canonical":
        if args.decimal_separator != ".":
            raise InputError("--decimal-separator applies only to the Stripe format")
        entries = parse_entries(snapshots["processor"], str(args.processor))
    else:
        entries = parse_stripe(snapshots["processor"], str(args.processor), decimal_separator=args.decimal_separator)
    deposits = parse_deposits(snapshots["bank"], str(args.bank))
    return sales, entries, deposits, fingerprints


def _write_pack(output: Path, payloads: dict[str, str], manifest: dict, marker: str) -> None:
    manifest["outputs"] = {
        name: {"sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}
        for name, content in sorted(payloads.items())
    }
    # Exclusive directory creation preserves existing files and concurrent runs.
    output.mkdir(parents=True, exist_ok=False)
    for name, content in payloads.items():
        (output / name).write_text(content, encoding="utf-8", newline="")
    # Publish the marker only after its entire content has been written and closed.
    staging = output / ("." + marker + ".tmp")
    staging.write_text(_json(manifest), encoding="utf-8", newline="")
    staging.rename(output / marker)


def _bundle(result: dict, inputs: dict, output: Path, configuration: dict | None = None) -> None:
    manifest = {"schema_version": "1", "tool_version": __version__, "inputs": inputs,
                "configuration": configuration or {"processor_format": "canonical", "decimal_separator": "."}}
    payloads = {"report.json": _json(result), "findings.csv": findings_csv(result),
                "report.html": render_html(result, manifest)}
    _write_pack(output, payloads, manifest, "manifest.json")


def _normalize(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise InputError(f"Output path already exists: {args.output}; choose a new directory")
    data = _capture(args.input, args.max_input_bytes)
    entries = parse_stripe(data, str(args.input), decimal_separator=args.decimal_separator)
    if not entries:
        raise InputError("No processor records to normalize")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=ENTRY_FIELDS)
    writer.writeheader()
    for entry in entries:
        writer.writerow({field: getattr(entry, field) for field in ENTRY_FIELDS})
    canonical = stream.getvalue()
    canonical_entries = parse_entries(canonical.encode("utf-8"), "processor.csv")
    audit = {"schema_version": "1", "tool_version": __version__,
             "input": _fingerprint(args.input, data),
             "configuration": {"processor_format": "stripe-payout-itemized-7", "decimal_separator": args.decimal_separator,
                               "max_input_bytes": args.max_input_bytes},
             "rows": [{"transaction_id": entry.transaction_id, "canonical_row": normalized.row, "source_row": entry.row}
                      for entry, normalized in zip(entries, canonical_entries)]}
    _write_pack(args.output, {"processor.csv": canonical}, audit, "audit.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="settletrace", description="Trace exceptions in supplied payment records, offline.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("reconcile", help="Compare canonical sales, processor, and bank CSVs")
    _input_arguments(command)
    command.add_argument("--output", type=Path, required=True, help="New output directory; existing paths are never overwritten")
    command.add_argument("--fail-on", choices=("any", "error"), default="any",
                         help="Exit 1 for any finding (default), or only error-severity findings")
    validate = commands.add_parser("validate", help="Validate input contracts without writing a report")
    _input_arguments(validate)
    normalize = commands.add_parser("normalize-stripe", help="Export canonical activity and raw-row mapping from a Stripe itemized.7 CSV")
    normalize.add_argument("--input", type=Path, required=True)
    normalize.add_argument("--output", type=Path, required=True)
    normalize.add_argument("--decimal-separator", choices=(".", ","), default=".")
    normalize.add_argument("--max-input-bytes", type=_positive_limit, default=DEFAULT_MAX_INPUT_BYTES)
    verify = commands.add_parser("verify", help="Check a completed report bundle's recorded hashes")
    verify.add_argument("--bundle", type=Path, required=True)
    for source in ("sales", "processor", "bank"):
        verify.add_argument("--" + source, type=Path)
    compare = commands.add_parser("compare", help="Compare observed findings in two verified report bundles")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--current", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "compare":
            baseline, current = verify_bundle(args.baseline), verify_bundle(args.current)
            comparison = compare_findings(baseline["report"], current["report"])
            comparison["input_changes"] = [source for source in ("sales", "processor", "bank")
                                            if baseline["manifest"]["inputs"][source]["sha256"]
                                            != current["manifest"]["inputs"][source]["sha256"]]
            print(_json(comparison), end="")
            return 0
        if args.command == "verify":
            checked = verify_bundle(args.bundle)
            paths = {source: getattr(args, source) for source in ("sales", "processor", "bank") if getattr(args, source) is not None}
            if paths:
                verify_sources(checked["manifest"], paths)
                print("SettleTrace: all three supplied source files match the recorded fingerprints.")
            print(f"SettleTrace: bundle hashes verified; {checked['report']['summary']['findings']} finding(s) remain in the report.")
            return 0
        if args.command == "normalize-stripe":
            _normalize(args)
            print(f"SettleTrace: canonical activity and source-row audit written to {args.output}")
            return 0
        if args.command == "reconcile" and args.output.exists():
            raise InputError(f"Output path already exists: {args.output}; choose a new directory")
        sales, entries, deposits, fingerprints = _read_inputs(args)
        result = reconcile(sales, entries, deposits)
        if args.command == "validate":
            print(_json({"schema_version": "1", "valid": True,
                         "records": {"sales": len(sales), "processor": len(entries), "bank": len(deposits)},
                         "observed_findings": result["summary"]["findings"],
                         "note": "Input contracts are valid; any reconciliation findings still need investigation."}), end="")
            return 0
        _bundle(result, fingerprints, args.output, {"processor_format": args.processor_format,
                                                  "decimal_separator": args.decimal_separator, "fail_on": args.fail_on,
                                                  "max_input_bytes": args.max_input_bytes})
    except (InputError, OSError) as exc:
        print(f"SettleTrace input/output error: {exc}", file=sys.stderr)
        return 2
    summary = result["summary"]
    state = "no exceptions observed" if summary["reconciled"] else "needs review"
    print(f"SettleTrace: {state}; {summary['findings']} finding(s).")
    print(f"Report: {args.output / 'report.html'}")
    print(f"Exit policy: {args.fail_on}; all findings remain in the report.")
    failed = bool(result["findings"]) if args.fail_on == "any" else any(f["severity"] == "error" for f in result["findings"])
    return 1 if failed else 0
