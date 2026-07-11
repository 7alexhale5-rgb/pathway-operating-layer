#!/usr/bin/env python3
"""Summarize proof-canary health without exposing proof commands or target paths."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath


RECEIPT_FIELDS = (
    "canary_target",
    "canary_target_source",
    "canary_target_reason",
    "canary_mutant_failed",
)
PROVENANCE_FIELDS = RECEIPT_FIELDS[:-1]
VALID_SOURCES = {"explicit", "verifier_reference", "unavailable"}
DEFAULT_OUTPUT_ROOT = Path.home() / "Projects" / "memory-vault" / "operator-intelligence"
DEFAULT_PROOFS = DEFAULT_OUTPUT_ROOT / "proofs.ndjson"
DEFAULT_REPORT = DEFAULT_OUTPUT_ROOT / "proof-canary-observability.json"


def _safe_repo_relative_path(value):
    if not isinstance(value, str) or not value:
        return False
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    return (
        not posix.is_absolute()
        and not windows.is_absolute()
        and ".." not in posix.parts
        and ".." not in windows.parts
    )


def _receipt_state(record):
    provenance_present = [field in record for field in PROVENANCE_FIELDS]
    if not any(provenance_present):
        return "legacy"
    if not all(provenance_present) or "canary_mutant_failed" not in record:
        return "invalid"

    target = record["canary_target"]
    source = record["canary_target_source"]
    reason = record["canary_target_reason"]
    result = record["canary_mutant_failed"]
    if source not in VALID_SOURCES or not isinstance(reason, str) or not reason:
        return "invalid"
    if result is not True and result is not False and result is not None:
        return "invalid"
    if source == "unavailable":
        return "unavailable" if target is None and result is None else "invalid"
    if not _safe_repo_relative_path(target) or result is None:
        return "invalid"
    return "strict"


def build_report(records, malformed_rows=0):
    counts = {
        "canary_receipts": 0,
        "strict_probe_passed": 0,
        "strict_probe_ignored": 0,
        "legacy_canary_passed": 0,
        "legacy_canary_ignored": 0,
        "target_unavailable": 0,
        "legacy_receipts": 0,
        "invalid_provenance": 0,
        "trivial_verifiers": 0,
        "malformed_rows": malformed_rows,
    }
    for record in records:
        if "canary_mutant_failed" not in record:
            continue
        counts["canary_receipts"] += 1
        if record.get("trivial_verifier") is True:
            counts["trivial_verifiers"] += 1
        state = _receipt_state(record)
        result = record.get("canary_mutant_failed")
        if state == "legacy":
            counts["legacy_receipts"] += 1
            if result is True:
                counts["legacy_canary_passed"] += 1
            elif result is False:
                counts["legacy_canary_ignored"] += 1
        elif state == "unavailable":
            counts["target_unavailable"] += 1
        elif state == "strict":
            if result is True:
                counts["strict_probe_passed"] += 1
            else:
                counts["strict_probe_ignored"] += 1
        else:
            counts["invalid_provenance"] += 1

    if counts["strict_probe_ignored"] or counts["legacy_canary_ignored"]:
        status = "alert"
        action = "Inspect ignored canary mutations before accepting further proof coverage."
    elif counts["invalid_provenance"] or counts["malformed_rows"]:
        status = "watch"
        action = "Repair malformed proof receipts before using this signal for decisions."
    elif not counts["strict_probe_passed"]:
        status = "watch"
        action = "Run a provenance-backed canary before treating mutation coverage as healthy."
    else:
        status = "pass"
        action = "Continue reviewing this report after proof-recording changes."

    return {
        "signal": "proof_canary_observability",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": status,
        "action": action,
        "counts": counts,
        "privacy": {
            "includes_raw_commands": False,
            "includes_canary_target_paths": False,
        },
    }


def load_records(path):
    records, malformed_rows = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            malformed_rows += 1
            continue
        if isinstance(record, dict):
            records.append(record)
        else:
            malformed_rows += 1
    return records, malformed_rows


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proofs", type=Path, default=DEFAULT_PROOFS, help="Path to proofs.ndjson.")
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT, help="Destination for the JSON report.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        records, malformed_rows = load_records(args.proofs)
    except OSError as exc:
        print(f"proof-canary-observability: cannot read proof ledger: {exc}", file=os.sys.stderr)
        return 2
    report = build_report(records, malformed_rows)
    try:
        write_report(args.out, report)
    except OSError as exc:
        print(f"proof-canary-observability: cannot write report: {exc}", file=os.sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
