"""Compare observed exceptions without treating absence as resolution."""

from .models import InputError


def _key(finding: dict) -> tuple:
    identities = tuple(sorted((item["source"], item["id"]) for item in finding["evidence"]))
    return finding["code"], finding["reference"], identities


def _indexed(findings: list[dict]) -> dict:
    result = {}
    for finding in findings:
        key = _key(finding)
        if key in result:
            raise InputError("Ambiguous duplicate finding identity in comparison")
        result[key] = finding
    return result


def _observation(finding: dict) -> dict:
    # CSV line moves are evidence-location changes, not a changed exception.
    return {**finding, "evidence": [{"source": source, "id": identifier}
                                  for source, identifier in _key(finding)[2]]}


def compare_findings(baseline: dict, current: dict) -> dict:
    before = _indexed(baseline["findings"])
    after = _indexed(current["findings"])
    shared = sorted(before.keys() & after.keys())
    changed = [{"before": before[key], "after": after[key]} for key in shared
               if _observation(before[key]) != _observation(after[key])]
    return {
        "schema_version": "1",
        "note": "No longer observed does not prove resolution; input scope or mapping may have changed.",
        "added": [after[key] for key in sorted(after.keys() - before.keys())],
        "no_longer_observed": [before[key] for key in sorted(before.keys() - after.keys())],
        "changed": changed,
        "unchanged_count": len(shared) - len(changed),
    }
