#!/usr/bin/env python3
"""Re-execute the three real Phase 1 G1 checks and validate its receipt."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
RECEIPT_PATH = Path(__file__).with_name("receipt-phase1-g1.json")
WORK_ID = "W-20260830-pathway-operating-layer-per-project-observabilit-e65d28"
BASE_COMMIT = "9ecedb620169fdcd5919e5cd7f3fd26d9ac67387"
COMMANDS = (
    ("characterization", [sys.executable, "scripts/tests/test_observability_contracts.py"]),
    (
        "fidelity",
        [
            sys.executable,
            ".planning/per-project-observability-contracts/quality/verify_phase1_fidelity.py",
        ],
    ),
    ("canonical", [sys.executable, "scripts/tests/operating_layer_test.py"]),
)


def fail(message: str) -> int:
    print(f"FAIL: {message}")
    return 1


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    if completed.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} exited {completed.returncode}: {output}")
    return output


def main() -> int:
    try:
        receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return fail(f"G1 receipt is unreadable: {exc}")

    expected_header = {
        "schema_version": 1,
        "work_id": WORK_ID,
        "phase": 1,
        "gate": "G1",
        "result": "PASS",
        "base_commit": BASE_COMMIT,
    }
    for key, expected in expected_header.items():
        if receipt.get(key) != expected or type(receipt.get(key)) is not type(expected):
            return fail(f"receipt {key} differs from the locked G1 value")

    required_carry_forward = (
        "lineage",
        "verification",
        "what_changed",
        "more_relevant",
        "less_relevant",
        "next_pathway_must_use",
        "do_not_do_yet",
        "open_decisions",
        "active_risk_overlays",
    )
    if any(key not in receipt for key in required_carry_forward):
        return fail("receipt is missing required lineage, verification, or carry-forward fields")

    artifacts = receipt.get("artifact_sha256")
    if not isinstance(artifacts, dict) or not artifacts:
        return fail("receipt artifact digest map is missing")
    for relative, expected_digest in artifacts.items():
        path = (REPO / relative).resolve()
        if REPO not in path.parents or not path.is_file():
            return fail(f"receipt artifact is outside the repository or missing: {relative}")
        if sha256_file(path) != expected_digest:
            return fail(f"receipt artifact digest changed: {relative}")

    try:
        outputs = {name: run(command) for name, command in COMMANDS}
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        return fail(str(exc))

    if outputs["characterization"] != "PASS: 5/5 characterization scenarios match goldens":
        return fail("frozen characterization output changed")

    try:
        fidelity = json.loads(outputs["fidelity"])
    except json.JSONDecodeError:
        return fail("fidelity verifier did not emit JSON")
    if (
        fidelity.get("result") != "PASS"
        or fidelity.get("matched_constant_count") != 24
        or fidelity.get("mismatches") != []
        or fidelity.get("contract_sha256") != artifacts["contracts/observability/rainman-thorp.json"]
    ):
        return fail("mechanical extraction fidelity no longer matches 24/24")

    match = re.fullmatch(r"(\d+)/\1 checks passed", outputs["canonical"])
    if not match or int(match.group(1)) < 1295:
        return fail("canonical suite did not pass at least the recorded 1295 checks")

    print(
        "PASS: Phase 1 G1 reverified "
        f"(5/5 characterization, 24/24 fidelity, {match.group(1)}/{match.group(1)} canonical)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
