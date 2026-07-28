#!/usr/bin/env bash
# Verify the local proof-canary signal and its privacy boundary.
set -euo pipefail

ROOT="/Users/alexhale/Projects/pathway-operating-layer"
ARTIFACT_DIR="$ROOT/.planning/2026-07-11-proof-canary-target-selection"
ARTIFACT="$ARTIFACT_DIR/OBSERVABILITY.md"
LIVE_REPORT="$ARTIFACT_DIR/PROOF_CANARY_OBSERVABILITY.json"
PROOFS="/Users/alexhale/Projects/memory-vault/operator-intelligence/proofs.ndjson"
TMP_DIR="$(mktemp -d -t proof-canary-observability.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

cd "$ROOT"

test -s "$ARTIFACT"
test -s "$PROOFS"
python3 -m py_compile scripts/proof-canary-observability.py
python3 scripts/proof-canary-observability.py --proofs "$PROOFS" --out "$LIVE_REPORT" > "$TMP_DIR/report.json"

python3 - "$LIVE_REPORT" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1]))
assert report["signal"] == "proof_canary_observability"
assert report["status"] == "alert"
assert report["counts"]["legacy_canary_ignored"] > 0
assert report["privacy"] == {
    "includes_raw_commands": False,
    "includes_canary_target_paths": False,
}
assert "verify_command" not in json.dumps(report)
assert '"canary_target":' not in json.dumps(report)
PY

python3 scripts/tests/operating_layer_test.py
git diff --check -- scripts/proof-canary-observability.py scripts/tests/operating_layer_test.py "$ARTIFACT" "$LIVE_REPORT" "$0"

printf '%s\n' "PASS proof-canary observability verifier"
