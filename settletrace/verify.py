"""Verify recorded bundle bytes and structure, not origin or completeness."""

import hashlib
import json
from pathlib import Path
import re

from .models import InputError, SUPPORTED_CURRENCIES


_OUTPUTS = frozenset({"report.json", "report.html", "findings.csv"})
_SOURCES = frozenset({"sales", "processor", "bank"})
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _integer(value, *, minimum=None) -> bool:
    return type(value) is int and (minimum is None or value >= minimum)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InputError(message)


def _read(path: Path) -> bytes:
    _require(not path.is_symlink() and path.is_file(), f"Expected a regular, non-symlink file: {path.name}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise InputError(f"Cannot read {path.name}: {exc}") from exc


def _object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _unsupported_number(value):
    raise InputError(f"Non-integer JSON number is unsupported: {value}")


def _json(data: bytes, source: str) -> dict:
    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=_object,
                            parse_constant=_unsupported_number, parse_float=_unsupported_number)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise InputError(f"{source}: invalid JSON: {exc}") from exc
    _require(isinstance(result, dict), f"{source}: expected a JSON object")
    return result


def _fingerprint(value: dict, *, source: bool) -> None:
    _require(isinstance(value, dict), "Malformed fingerprint")
    _require(isinstance(value.get("sha256"), str) and _HASH.fullmatch(value["sha256"]) is not None,
             "Malformed SHA-256 fingerprint")
    if source:
        name = value.get("name")
        _require(isinstance(name, str) and name not in {"", ".", ".."} and "/" not in name and "\\" not in name,
                 "Input name must be a basename")
        _require(_integer(value.get("size_bytes"), minimum=0), "Input size must be a nonnegative integer")


def _report(value: dict) -> None:
    _require(value.get("schema_version") == "1", "Unsupported report schema_version")
    summary, findings = value.get("summary"), value.get("findings")
    _require(isinstance(summary, dict) and isinstance(findings, list), "Malformed report summary/findings")
    for key in ("sales", "processor_entries", "bank_deposits", "findings", "matched_sales", "matched_payouts"):
        _require(_integer(summary.get(key), minimum=0), f"Invalid summary count: {key}")
    _require(summary["findings"] == len(findings), "Finding count disagrees with report")
    _require(type(summary.get("reconciled")) is bool and summary["reconciled"] == (not findings),
             "Reconciliation status disagrees with findings")
    _require(summary["matched_sales"] <= summary["sales"] and summary["matched_payouts"] <= summary["bank_deposits"],
             "Matched counts exceed observed records")
    for finding in findings:
        _require(isinstance(finding, dict), "Malformed finding")
        for key in ("code", "reference", "message"):
            _require(isinstance(finding.get(key), str) and bool(finding[key]), f"Invalid finding {key}")
        _require(isinstance(finding.get("severity"), str) and finding["severity"] in {"error", "review"}, "Invalid finding severity")
        evidence = finding.get("evidence")
        _require(isinstance(evidence, list) and bool(evidence), "Finding has no source evidence")
        for item in evidence:
            _require(isinstance(item, dict) and isinstance(item.get("source"), str)
                     and item["source"] in _SOURCES and _integer(item.get("row"), minimum=0)
                     and isinstance(item.get("id"), str) and bool(item["id"]), "Malformed source evidence")
        if "details" in finding:
            details = finding["details"]
            _require(isinstance(details, dict), "Malformed finding details")
            _require(isinstance(details.get("currency"), str) and details["currency"] in SUPPORTED_CURRENCIES
                     and all(_integer(details.get(key)) for key in ("expected_minor", "observed_minor", "delta_minor")),
                     "Malformed amount evidence")
            _require(details["observed_minor"] - details["expected_minor"] == details["delta_minor"],
                     "Amount difference disagrees with evidence")
    totals = value.get("totals_by_currency")
    _require(isinstance(totals, dict), "Malformed currency totals")
    for currency, amounts in totals.items():
        _require(currency in SUPPORTED_CURRENCIES and isinstance(amounts, dict)
                 and all(_integer(amounts.get(key)) for key in ("gross_minor", "fee_minor", "net_minor", "bank_minor")),
                 "Malformed currency amounts")


def verify_bundle(path: Path | str) -> dict:
    directory = Path(path)
    _require(not directory.is_symlink() and directory.is_dir(), "Expected a non-symlink bundle directory")
    manifest = _json(_read(directory / "manifest.json"), "manifest.json")
    _require(manifest.get("schema_version") == "1" and isinstance(manifest.get("tool_version"), str)
             and bool(manifest["tool_version"]), "Unsupported or malformed manifest version")
    inputs, outputs = manifest.get("inputs"), manifest.get("outputs")
    _require(isinstance(inputs, dict) and set(inputs) == _SOURCES, "Manifest must describe sales, processor, and bank inputs")
    _require(isinstance(outputs, dict) and set(outputs) == _OUTPUTS, "Manifest must describe exactly the three report outputs")
    for fingerprint in inputs.values():
        _fingerprint(fingerprint, source=True)
    payloads = {}
    for name in sorted(_OUTPUTS):
        _fingerprint(outputs[name], source=False)
        data = _read(directory / name)
        _require(hashlib.sha256(data).hexdigest() == outputs[name]["sha256"], f"Output hash mismatch: {name}")
        payloads[name] = data
    report = _json(payloads["report.json"], "report.json")
    _report(report)
    return {"manifest": manifest, "report": report}


def verify_sources(manifest: dict, paths: dict[str, Path]) -> None:
    """Check explicitly supplied source paths against a verified manifest.

    File names may differ after copying. No path from the manifest is opened.
    Hashing is streamed, so a large or changed source is not read into memory.
    """
    _require(set(paths) == _SOURCES, "Supply all three source paths: --sales, --processor, --bank")
    for source in sorted(_SOURCES):
        expected = manifest["inputs"][source]
        path = Path(paths[source])
        _require(path.is_file(), f"Expected a source file for {source}")
        digest, size = hashlib.sha256(), 0
        try:
            with path.open("rb") as stream:
                while chunk := stream.read(65536):
                    size += len(chunk)
                    _require(size <= expected["size_bytes"], f"Input size mismatch: {source}")
                    digest.update(chunk)
        except OSError as exc:
            raise InputError(f"Cannot read {source}: {exc}") from exc
        _require(size == expected["size_bytes"], f"Input size mismatch: {source}")
        _require(digest.hexdigest() == expected["sha256"], f"Input hash mismatch: {source}")
