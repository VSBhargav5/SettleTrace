"""Command-line entry point with explicit outcome codes and reproducible bundles."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

from . import __version__
from .engine import reconcile
from .ingest import parse_deposits, parse_entries, parse_sales
from .models import InputError
from .report import findings_csv, render_html
from .stripe import parse_stripe


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


def _read_inputs(args: argparse.Namespace) -> tuple:
    paths = {"sales": args.sales, "processor": args.processor, "bank": args.bank}
    # Each immutable snapshot supplies both the hash and the parsed records.
    snapshots = {name: path.read_bytes() for name, path in paths.items()}
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


def _bundle(result: dict, inputs: dict, output: Path, configuration: dict | None = None) -> None:
    manifest = {"schema_version": "1", "tool_version": __version__, "inputs": inputs,
                "configuration": configuration or {"processor_format": "canonical", "decimal_separator": "."}}
    payloads = {
        "report.json": _json(result),
        "findings.csv": findings_csv(result),
        "report.html": render_html(result, manifest),
    }
    manifest["outputs"] = {
        name: {"sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}
        for name, content in sorted(payloads.items())
    }
    # Exclusive directory creation preserves existing files and concurrent runs.
    output.mkdir(parents=True, exist_ok=False)
    for name, content in payloads.items():
        (output / name).write_text(content, encoding="utf-8", newline="")
    # Publish the marker only after its entire content has been written and closed.
    staging = output / ".manifest.json.tmp"
    staging.write_text(_json(manifest), encoding="utf-8", newline="")
    staging.rename(output / "manifest.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="settletrace", description="Trace exceptions in supplied payment records, offline.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("reconcile", help="Compare canonical sales, processor, and bank CSVs")
    _input_arguments(command)
    command.add_argument("--output", type=Path, required=True, help="New output directory; existing paths are never overwritten")
    validate = commands.add_parser("validate", help="Validate input contracts without writing a report")
    _input_arguments(validate)
    args = parser.parse_args(argv)
    try:
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
                                                  "decimal_separator": args.decimal_separator})
    except (InputError, OSError) as exc:
        print(f"SettleTrace input/output error: {exc}", file=sys.stderr)
        return 2
    summary = result["summary"]
    state = "no exceptions observed" if summary["reconciled"] else "needs review"
    print(f"SettleTrace: {state}; {summary['findings']} finding(s).")
    print(f"Report: {args.output / 'report.html'}")
    return 0 if summary["reconciled"] else 1
