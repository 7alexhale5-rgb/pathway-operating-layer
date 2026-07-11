#!/usr/bin/env bash
# Verify the proof-canary release rehearsal without activating the selector.
set -euo pipefail

ROOT="/Users/alexhale/Projects/pathway-operating-layer"
ARTIFACT_DIR="$ROOT/.planning/2026-07-11-proof-canary-target-selection"
ARTIFACT="$ARTIFACT_DIR/RELEASE.md"
PROOFS="/Users/alexhale/Projects/memory-vault/operator-intelligence/proofs.ndjson"
TMP_DIR="$(mktemp -d -t proof-canary-release.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

cd "$ROOT"

test -s "$ARTIFACT"
test -s "$PROOFS"
for heading in \
  "## Release Decision" \
  "## Rollout Shape" \
  "## Rollback Plan" \
  "## Stop Conditions" \
  "## Summary" \
  "## What Changed" \
  "## More Relevant" \
  "## Less Relevant" \
  "## Next Pathway Must Use" \
  "## Do Not Do Yet" \
  "## Open Decisions" \
  "## Active Risk Overlays"; do
  grep -q "$heading" "$ARTIFACT"
done
grep -q "no runtime feature flag" "$ARTIFACT"
grep -q "canary_mutant_failed: null" "$ARTIFACT"
grep -q "git apply --reverse" "$ARTIFACT"
grep -q "git revert <proof-canary-target-selection-commit-sha>" "$ARTIFACT"
grep -q 'Do not use a broad `git restore`' "$ARTIFACT"

python3 -m py_compile scripts/proof-canary-observability.py scripts/operating-layer.py
python3 scripts/proof-canary-observability.py --proofs "$PROOFS" --out "$TMP_DIR/report.json" > "$TMP_DIR/report.stdout"
python3 - "$TMP_DIR/report.json" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1]))
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
git diff --check

printf '%s\n' "PASS proof-canary release rehearsal"
