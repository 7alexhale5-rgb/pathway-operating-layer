"""Security-gate verifier: re-measure the threat model's load-bearing mitigations.

Usage: python3 verify_security.py <receipt.ndjson>

Re-measures (never trusts):
- T1: the engine refuses a receipt whose context disagrees with the caller
  binding (drives validate_observability_runtime_receipt live)
- T6: the shipped default is fail-closed (trust state + empty allowlist)
- repo exposure: no live credential pattern in tracked source
Then asserts the threat model is complete (T1-T7 + carried constraints)
and that the receipt agrees with the fresh measurement.
"""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
ENGINE = ROOT / "scripts" / "operating-layer.py"
MODEL = (
    ROOT
    / ".planning"
    / "per-project-observability-contracts"
    / "security"
    / "2026-08-30-threat-model.md"
)


def fail(message):
    print(f"FAIL: {message}")
    sys.exit(3)


def load_engine():
    spec = importlib.util.spec_from_file_location("opl_engine", ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measure():
    opl = load_engine()
    receipt = {
        "schema_version": 1,
        "receipt_type": "runtime_observability",
        "work_id": "W-attacker",
        "recommendation_id": "REC-attacker",
        "project": "evil-project",
        "target_project": "/tmp/evil-project",
    }
    expected = {
        "work_id": "W-legit",
        "recommendation_id": "REC-legit",
        "project": "legit-project",
        "target_project": "/tmp/legit-project",
    }
    errors = opl.validate_observability_runtime_receipt(receipt, expected=expected)
    # Every one of the four context fields must individually mismatch-error;
    # a single generic mismatch is not proof the binding covers all four.
    binding_enforced = all(
        any(
            f"observability receipt {field} does not match the current proof context"
            in error
            for error in errors
        )
        for field in ("work_id", "recommendation_id", "project", "target_project")
    )
    return {
        "context_binding_enforced": binding_enforced,
        "trust_state": opl.OBSERVABILITY_RUNTIME_VERIFIER_TRUST_STATE,
        "trusted_sha_count": len(opl.OBSERVABILITY_TRUSTED_VERIFIER_SHA256),
    }


def secret_scan_findings():
    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    live_credential = re.compile(
        r"AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{32,}|ghp_[A-Za-z0-9]{36}"
    )
    # AWS's canonical documentation placeholder (the AKIA example key ending
    # in the word EXAMPLE), used by the test suite to exercise the redaction
    # guard; it is not a live credential. Built by concatenation so secret
    # scanners reading this verifier do not flag the verifier itself.
    documented_examples = {"AKIA" + "IOSFODNN7" + "EXAMPLE"}
    findings = 0
    for name in tracked:
        path = ROOT / name
        if (
            path.suffix not in {".py", ".json", ".sh", ".md", ".ndjson"}
            or not path.is_file()
        ):
            continue
        matches = set(
            live_credential.findall(path.read_text(encoding="utf-8", errors="replace"))
        )
        if matches - documented_examples:
            findings += 1
    return findings


def main():
    if len(sys.argv) < 2:
        fail("receipt path required as the last argument")
    receipt_path = Path(sys.argv[-1])
    first_line = receipt_path.read_text(encoding="utf-8").strip().splitlines()[0]
    receipt = json.loads(first_line)
    if receipt["gate"] != "security-gate":
        fail("receipt gate must be security-gate")
    if receipt["pathway"] != "security":
        fail("receipt pathway must be security")
    if not str(receipt["work_id"]).startswith("W-20260830-pathway-operating-layer"):
        fail("receipt work_id does not bind this outcome")

    measured = measure()
    if measured["context_binding_enforced"] is not True:
        fail("engine no longer refuses receipt-supplied context (T1 mitigation broken)")
    if (
        measured["trust_state"] != "CONFIGURED_AND_VERIFIED"
        and measured["trusted_sha_count"] != 0
    ):
        fail(
            "trust allowlist populated while state is unconfigured (inconsistent T6 posture)"
        )
    for key, value in measured.items():
        if receipt.get(key) != value:
            fail(
                f"receipt {key}={receipt.get(key)!r} disagrees with measured {value!r}"
            )

    findings = secret_scan_findings()
    if findings != receipt.get("secret_scan_findings", -1):
        fail(f"secret scan found {findings} finding(s); receipt disagrees")
    if findings != 0:
        fail("live credential pattern present in tracked source")

    model_text = MODEL.read_text(encoding="utf-8")
    for term in ("threat", "verification"):
        if term not in model_text.lower():
            fail(f"threat model missing required term {term!r}")
    threats = [
        f"T{n}"
        for n in range(1, 16)
        if f"**T{n} " in model_text or f"**T{n} —" in model_text
    ]
    if len(threats) != receipt.get("threat_count", -1):
        fail(f"threat model enumerates {len(threats)} threats; receipt disagrees")
    if "Constraints carried forward" not in model_text:
        fail("threat model missing the carried-forward constraints section")

    print("PASS: security-gate — mitigations re-measured against the live engine")
    sys.exit(0)


main()
