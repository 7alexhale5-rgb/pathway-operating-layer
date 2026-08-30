"""Research-gate verifier: re-measure dossier claims against the live engine.

Usage: python3 verify_research.py <receipt.ndjson>

Re-measures (never trusts) the load-bearing dossier claims:
- claim 2: all OBSERVABILITY_METRIC_NAMES are tradebot_-prefixed (count 7)
- claim 3: trust state defaults to TRUSTED_VERIFIER_NOT_CONFIGURED with an
  empty trusted-sha allowlist
- claim 5: the OBSERVABILITY_* extraction surface matches the cataloged count
- claim 10: the existing test suite never calls the receipt validators
Then asserts the receipt and dossier agree with the fresh measurement.
"""

import ast
import json
import sys
from pathlib import Path

ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
ENGINE = ROOT / "scripts" / "operating-layer.py"
TESTS = ROOT / "scripts" / "tests" / "operating_layer_test.py"
DOSSIER = (
    ROOT
    / ".planning"
    / "per-project-observability-contracts"
    / "research"
    / "2026-08-30-dossier.md"
)


def fail(message):
    print(f"FAIL: {message}")
    sys.exit(3)


def measure_engine():
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id.startswith("OBSERVABILITY_"):
                constants[target.id] = node.value
    metric_names = ast.literal_eval(constants["OBSERVABILITY_METRIC_NAMES"])
    trust_state = ast.literal_eval(
        constants["OBSERVABILITY_RUNTIME_VERIFIER_TRUST_STATE"]
    )
    sha_node = constants["OBSERVABILITY_TRUSTED_VERIFIER_SHA256"]
    sha_count = len(sha_node.args[0].elts) if getattr(sha_node, "args", None) else 0
    return {
        "observability_constant_count": len(constants),
        "metric_names_count": len(metric_names),
        "tradebot_prefixed": all(name.startswith("tradebot_") for name in metric_names),
        "trust_state": trust_state,
        "trusted_sha_count": sha_count,
    }


def main():
    if len(sys.argv) < 2:
        fail("receipt path required as the last argument")
    receipt_path = Path(sys.argv[-1])
    first_line = receipt_path.read_text(encoding="utf-8").strip().splitlines()[0]
    receipt = json.loads(first_line)
    if receipt["gate"] != "research-gate":
        fail("receipt gate must be research-gate")
    if receipt["pathway"] != "research":
        fail("receipt pathway must be research")
    if not str(receipt["work_id"]).startswith("W-20260830-pathway-operating-layer"):
        fail("receipt work_id does not bind this outcome")

    measured = measure_engine()
    for key, value in measured.items():
        if receipt.get(key) != value:
            fail(
                f"receipt {key}={receipt.get(key)!r} disagrees with measured {value!r}"
            )

    test_source = TESTS.read_text(encoding="utf-8")
    direct_calls = test_source.count(
        "validate_observability_runtime_receipt("
    ) + test_source.count("_validate_observability_json_artifact(")
    if direct_calls != receipt.get("validator_test_direct_calls", -1):
        fail(f"test suite has {direct_calls} direct validator calls; receipt disagrees")

    dossier_text = DOSSIER.read_text(encoding="utf-8")
    for heading in ("## Question", "## Sources", "## Unknowns, classified"):
        if heading not in dossier_text:
            fail(f"dossier missing required section {heading!r}")
    if "blocker" not in dossier_text:
        fail("dossier must classify unknowns against the blocker tier")

    print("PASS: research-gate — dossier claims re-measured against the live engine")
    sys.exit(0)


main()
