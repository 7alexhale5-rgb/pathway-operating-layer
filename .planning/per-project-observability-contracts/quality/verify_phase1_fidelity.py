#!/usr/bin/env python3
"""One-time AST proof that Phase 1 mechanically preserves the 9ecedb6 constants."""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
BASE_REF = "9ecedb6"
BASE_COMMIT = "9ecedb620169fdcd5919e5cd7f3fd26d9ac67387"
ENGINE_PATH = "scripts/operating-layer.py"
CONTRACT_PATH = REPO / "contracts" / "observability" / "rainman-thorp.json"
EXPECTED_RECEIPT_SUMMARY = (
    "Phase 1 mechanically extracted the Rainman/Thorp observability contract and preserved "
    "the Phase 2 containment boundary."
)
EXPECTED_RECEIPT_KEYS = {
    "schema_version", "work_id", "phase", "gate", "result", "verified_at", "base_commit",
    "summary", "scope", "lineage", "verification", "what_changed", "more_relevant",
    "less_relevant", "next_pathway_must_use", "do_not_do_yet", "open_decisions",
    "active_risk_overlays", "commands", "artifact_sha256", "fidelity", "separate_scope",
}
EXPECTED_LINEAGE = {
    "source": f"scripts/operating-layer.py at {BASE_COMMIT}",
    "destination": "contracts/observability/rainman-thorp.json",
    "method": "AST extraction of 23 literal constants plus one mechanically derived trust state",
}
EXPECTED_CARRY_FORWARD = {
    "what_changed": [
        "Tradebot observability constants now have a versioned contract file behind the Phase 1 "
        "loader and schema gate."
    ],
    "more_relevant": [
        "Phase 2 must resolve contracts by canonical project identity and enforce containment "
        "before project-specific credit is enabled."
    ],
    "less_relevant": [
        "The separate OS-owned approval-authority repair does not establish or alter Phase 1 "
        "extraction fidelity."
    ],
    "next_pathway_must_use": [
        "Read this G1 receipt and the locked threat-model constraints before implementing Phase 2 "
        "resolution."
    ],
    "do_not_do_yet": [
        "Do not reuse the Phase 1 loader for arbitrary project paths until Phase 2 containment and "
        "project-key binding pass."
    ],
    "open_decisions": [],
    "active_risk_overlays": ["rollback"],
}
METADATA = {
    "schema_version": 1,
    "contract_type": "observability_evidence_contract",
    "project_key": "rainman-thorp",
    "extracted_from": "operating-layer.py constants, verbatim, 2026-08-30",
}
CONTRACT_TO_CONSTANT = {
    "metric_names": "OBSERVABILITY_METRIC_NAMES",
    "metric_label_values": "OBSERVABILITY_METRIC_LABEL_VALUES",
    "metric_domains": "OBSERVABILITY_METRIC_DOMAINS",
    "event_names": "OBSERVABILITY_EVENT_NAMES",
    "correlation_fields": "OBSERVABILITY_CORRELATION_FIELDS",
    "correlation_hash_fields": "OBSERVABILITY_CORRELATION_HASH_FIELDS",
    "correlation_timestamp_fields": "OBSERVABILITY_CORRELATION_TIMESTAMP_FIELDS",
    "correlation_sequence_fields": "OBSERVABILITY_CORRELATION_SEQUENCE_FIELDS",
    "allowed_assets": "OBSERVABILITY_ALLOWED_ASSETS",
    "allowed_modes": "OBSERVABILITY_ALLOWED_MODES",
    "allowed_risk_decisions": "OBSERVABILITY_ALLOWED_RISK_DECISIONS",
    "allowed_reason_codes": "OBSERVABILITY_ALLOWED_REASON_CODES",
    "drill_incident": "OBSERVABILITY_DRILL_INCIDENT",
    "drill_trace_name": "OBSERVABILITY_DRILL_TRACE_NAME",
    "drill_alert": "OBSERVABILITY_DRILL_ALERT",
    "runbook_question_ids": "OBSERVABILITY_RUNBOOK_QUESTION_IDS",
    "runbook_evidence_fields": "OBSERVABILITY_RUNBOOK_EVIDENCE_FIELDS",
    "runbook_dispositions": "OBSERVABILITY_RUNBOOK_DISPOSITIONS",
    "runbook_answer_codes": "OBSERVABILITY_RUNBOOK_ANSWER_CODES",
    "runbook_enum_values": "OBSERVABILITY_RUNBOOK_ENUM_VALUES",
    "runbook_missing_evidence": "OBSERVABILITY_RUNBOOK_MISSING_EVIDENCE",
    "runbook_answer_contract": "OBSERVABILITY_RUNBOOK_ANSWER_CONTRACT",
    "trusted_verifier_sha256": "OBSERVABILITY_TRUSTED_VERIFIER_SHA256",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def literal(node):
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "frozenset" and not node.keywords):
        if not node.args:
            return frozenset()
        if len(node.args) == 1:
            return frozenset(ast.literal_eval(node.args[0]))
    return ast.literal_eval(node)


def normalize(value):
    if isinstance(value, dict):
        return {key: normalize(value[key]) for key in sorted(value)}
    if isinstance(value, (set, frozenset)):
        normalized = [normalize(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    return value


def base_constants(source: bytes):
    wanted = set(CONTRACT_TO_CONSTANT.values()) | {"OBSERVABILITY_RUNTIME_VERIFIER_TRUST_STATE"}
    found = {}
    tree = ast.parse(source.decode("utf-8"), filename=f"{BASE_REF}:{ENGINE_PATH}")
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in wanted:
            found[target.id] = literal(node.value)
    return found


def strict_json_object(text: str):
    """Parse one unambiguous finite JSON object or raise ValueError."""
    duplicates = []

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                duplicates.append(str(key))
            else:
                value[key] = item
        return value

    def reject_constant(value):
        raise ValueError(f"non-finite number {value}")

    data = json.loads(
        text,
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
        parse_float=lambda value: _finite_float(value),
    )
    if duplicates:
        raise ValueError("duplicate JSON key(s): " + ", ".join(sorted(set(duplicates))))
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return data


def _finite_float(value: str) -> float:
    number = float(value)
    if number == float("inf") or number == float("-inf") or number != number:
        raise ValueError(f"non-finite number {value}")
    return number


def validate_g1_receipt(path: Path, contract_sha256: str) -> list[str]:
    try:
        receipt = strict_json_object(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, TypeError, ValueError) as exc:
        return [f"G1 receipt is unreadable: {exc}"]
    errors = []
    expected = {
        "work_id": "W-20260830-pathway-operating-layer-per-project-observabilit-e65d28",
        "phase": 1,
        "gate": "G1",
        "result": "PASS",
        "base_commit": BASE_COMMIT,
        "summary": EXPECTED_RECEIPT_SUMMARY,
    }
    for key, value in expected.items():
        if receipt.get(key) != value or type(receipt.get(key)) is not type(value):
            errors.append(f"G1 receipt field mismatch: {key}")
    if set(receipt) != EXPECTED_RECEIPT_KEYS:
        errors.append("G1 receipt top-level schema differs from the locked Phase 1 schema")
    if receipt.get("schema_version") != 1 or type(receipt.get("schema_version")) is not int:
        errors.append("G1 receipt schema_version mismatch")
    if receipt.get("lineage") != EXPECTED_LINEAGE:
        errors.append("G1 receipt lineage mismatch")
    verification = receipt.get("verification")
    if not isinstance(verification, dict) or set(verification) != {
            "frozen_characterization", "constant_fidelity", "canonical_suite"}:
        errors.append("G1 receipt verification schema mismatch")
    else:
        canonical_parts = str(verification.get("canonical_suite") or "").split("/")
        if (verification.get("frozen_characterization") != "5/5"
                or verification.get("constant_fidelity") != "24/24"
                or len(canonical_parts) != 2
                or not canonical_parts[0].isdigit()
                or canonical_parts[0] != canonical_parts[1]):
            errors.append("G1 receipt verification result mismatch")
    for field, value in EXPECTED_CARRY_FORWARD.items():
        if receipt.get(field) != value or any(
                not isinstance(item, str) for item in receipt.get(field, [])
        ):
            errors.append(f"G1 receipt carry-forward mismatch: {field}")
    expected_fidelity = {
        "contract_key_count": 27,
        "metadata_key_count": 4,
        "extracted_constant_count": 23,
        "derived_constant_count": 1,
        "matched_constant_count": 24,
        "mismatches": [],
    }
    if receipt.get("fidelity") != expected_fidelity:
        errors.append("G1 receipt fidelity block mismatch")
    commands = receipt.get("commands")
    if (not isinstance(commands, list) or not commands
            or any(
                not isinstance(command, dict)
                or set(command) != {"command", "result", "observed"}
                or command.get("result") != "PASS"
                or any(not isinstance(command.get(field), str) or not command.get(field)
                       for field in ("command", "result", "observed"))
                for command in commands
            )):
        errors.append("G1 receipt command evidence schema mismatch")
    artifact_paths = {
        "contracts/observability/rainman-thorp.json": CONTRACT_PATH,
        "scripts/tests/test_observability_contracts.py": REPO / "scripts/tests/test_observability_contracts.py",
        ".planning/per-project-observability-contracts/quality/verify_phase1_fidelity.py": Path(__file__).resolve(),
    }
    try:
        expected_artifacts = {
            name: contract_sha256 if name == "contracts/observability/rainman-thorp.json"
            else sha256_bytes(artifact_path.read_bytes())
            for name, artifact_path in artifact_paths.items()
        }
    except OSError as exc:
        errors.append(f"G1 receipt artifact is unreadable: {exc}")
        expected_artifacts = {}
    if receipt.get("artifact_sha256") != expected_artifacts:
        errors.append("G1 receipt artifact digests do not match the current Phase 1 artifacts")
    return errors


def main() -> int:
    if len(sys.argv) > 2:
        print("usage: verify_phase1_fidelity.py [receipt-phase1-g1.json]", file=sys.stderr)
        return 2
    resolved = subprocess.run(
        ["git", "rev-parse", f"{BASE_REF}^{{commit}}"], cwd=REPO,
        capture_output=True, check=True, text=True,
    ).stdout.strip()
    source = subprocess.run(
        ["git", "show", f"{BASE_REF}:{ENGINE_PATH}"], cwd=REPO,
        capture_output=True, check=True,
    ).stdout
    contract_raw = CONTRACT_PATH.read_bytes()
    contract_error = ""
    try:
        contract = strict_json_object(contract_raw.decode("utf-8"))
    except (UnicodeDecodeError, TypeError, ValueError) as exc:
        contract = {}
        contract_error = f"contract is not strict JSON: {exc}"
    constants = base_constants(source)

    expected_keys = set(METADATA) | set(CONTRACT_TO_CONSTANT)
    mismatches = [contract_error] if contract_error else []
    if resolved != BASE_COMMIT:
        mismatches.append(f"base ref resolved to {resolved}, expected {BASE_COMMIT}")
    if set(contract) != expected_keys:
        mismatches.append("contract key set differs from the 23 extracted fields plus 4 metadata fields")
    for key, expected in METADATA.items():
        if contract.get(key) != expected:
            mismatches.append(f"metadata mismatch: {key}")
    for contract_key, constant_name in CONTRACT_TO_CONSTANT.items():
        if constant_name not in constants:
            mismatches.append(f"missing base constant: {constant_name}")
            continue
        if normalize(contract.get(contract_key)) != normalize(constants[constant_name]):
            mismatches.append(f"value mismatch: {contract_key} != {constant_name}")

    old_trust_state = constants.get("OBSERVABILITY_RUNTIME_VERIFIER_TRUST_STATE")
    derived_trust_state = (
        "CONFIGURED_AND_VERIFIED"
        if contract.get("trusted_verifier_sha256")
        else "TRUSTED_VERIFIER_NOT_CONFIGURED"
    )
    if old_trust_state != derived_trust_state:
        mismatches.append("derived trust state differs from OBSERVABILITY_RUNTIME_VERIFIER_TRUST_STATE")
    if len(sys.argv) == 2:
        mismatches.extend(validate_g1_receipt(Path(sys.argv[1]).resolve(), sha256_bytes(contract_raw)))

    matched = len(CONTRACT_TO_CONSTANT) + 1 - len([
        item for item in mismatches if item.startswith(("missing base constant", "value mismatch", "derived"))
    ])
    receipt = {
        "verification": "phase1-observability-contract-ast-fidelity",
        "base_commit": resolved,
        "base_engine_sha256": sha256_bytes(source),
        "contract_path": "contracts/observability/rainman-thorp.json",
        "contract_sha256": sha256_bytes(contract_raw),
        "contract_key_count": len(contract),
        "metadata_key_count": len(METADATA),
        "extracted_constant_count": len(CONTRACT_TO_CONSTANT),
        "derived_constant_count": 1,
        "matched_constant_count": matched,
        "mismatches": mismatches,
        "result": "PASS" if not mismatches and matched == 24 else "FAIL",
    }
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
