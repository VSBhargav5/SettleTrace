"""Hash-bound operator declarations; these do not establish row completeness."""

from datetime import datetime
import json
import re

from .models import InputError


TIME_BASES = {"sales": "captured_at_utc", "processor": "automatic_payout_effective_at_utc",
              "bank": "bank_posted_at_utc"}
MAX_WINDOW_BYTES = 1024 * 1024
_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InputError("Observation window: " + message)


def _timestamp(value) -> datetime:
    _require(isinstance(value, str) and _UTC.fullmatch(value) is not None,
             "timestamps must use YYYY-MM-DDTHH:MM:SSZ (UTC, whole seconds)")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise InputError(f"Observation window: invalid UTC timestamp: {value}") from exc


def validate_window(value: dict) -> None:
    _require(isinstance(value, dict) and set(value) == {"schema_version", "account_scope", "sources"},
             "expected exactly schema_version, account_scope, sources")
    _require(value["schema_version"] == "1", "unsupported schema_version")
    scope = value["account_scope"]
    _require(isinstance(scope, str) and bool(scope.strip()) and scope == scope.strip(),
             "account_scope must be a nonblank, unpadded operator label")
    try:
        scope.encode("utf-8")
    except UnicodeError as exc:
        raise InputError("Observation window: account_scope must be encodable as UTF-8") from exc
    sources = value["sources"]
    _require(isinstance(sources, dict) and set(sources) == set(TIME_BASES),
             "sources must describe sales, processor, and bank")
    for source, basis in TIME_BASES.items():
        item = sources[source]
        _require(isinstance(item, dict) and set(item) == {
            "start_utc", "end_utc", "time_basis", "sha256", "size_bytes"}, f"invalid fields for {source}")
        _require(item["time_basis"] == basis, f"{source} time_basis must be {basis}")
        _require(_timestamp(item["start_utc"]) < _timestamp(item["end_utc"]),
                 f"{source} interval must have start < end")
        _require(isinstance(item["sha256"], str) and _HASH.fullmatch(item["sha256"]) is not None,
                 f"{source} needs a lowercase SHA-256")
        _require(type(item["size_bytes"]) is int and item["size_bytes"] >= 0,
                 f"{source} size_bytes must be a nonnegative integer")


def parse_window(data: bytes, source: str = "window.json") -> dict:
    if not isinstance(data, bytes):
        raise TypeError("data must be an immutable bytes snapshot")
    _require(len(data) <= MAX_WINDOW_BYTES, "declaration exceeds the 1 MiB limit")

    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def number(value):
        raise InputError("Observation window: non-integer JSON numbers are unsupported")

    try:
        value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=object_pairs,
                           parse_constant=number, parse_float=number)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise InputError(f"{source}: invalid observation declaration: {exc}") from exc
    validate_window(value)
    return value


def assess_window(declaration: dict, fingerprints: dict) -> dict:
    """Compare the exact captured bytes, not the truth of the declared dates."""
    validate_window(declaration)
    for source, item in declaration["sources"].items():
        actual = fingerprints.get(source)
        _require(isinstance(actual, dict) and all(actual.get(key) == item[key] for key in ("sha256", "size_bytes")),
                 f"{source} bytes do not match the declared fingerprint")
    boundaries = {(item["start_utc"], item["end_utc"]) for item in declaration["sources"].values()}
    return {"declaration": declaration, "source_bytes_match": True,
            "intervals_have_same_boundaries": len(boundaries) == 1,
            "interval_convention": "start_inclusive_end_exclusive",
            "row_timestamps_checked": False, "completeness": "not_established",
            "note": "Operator-declared dates and account scope are unverified. No records were date-filtered; "
                    "matching bytes or totals do not establish completeness."}
