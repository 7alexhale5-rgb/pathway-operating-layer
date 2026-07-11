#!/usr/bin/env bash
# Verify the proof-canary target-selection documentation without claiming unbuilt behavior is live.
set -euo pipefail

ROOT="/Users/alexhale/Projects/pathway-operating-layer"
DOC="$ROOT/docs/proof-canary-target-selection.md"
PROOFS="/Users/alexhale/Projects/memory-vault/operator-intelligence/proofs.ndjson"
TMP_DIR="$(mktemp -d -t proof-canary-docs.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

cd "$ROOT"

test -s "$DOC"
test -s "$PROOFS"
for heading in \
  "## The Answer" \
  "## Current State" \
  "## Future Contract" \
  "## Privacy Boundary" \
  "## Release And Rollback" \
  "## Summary" \
  "## What Changed" \
  "## More Relevant" \
  "## Less Relevant" \
  "## Next Pathway Must Use" \
  "## Do Not Do Yet" \
  "## Open Decisions" \
  "## Active Risk Overlays"; do
  grep -q "$heading" "$DOC"
done
grep -q "local operating-layer working tree now supports relevance-aware selection" "$DOC"
grep -q "no focused release commit has been requested" "$DOC"
grep -q '"canary_target_source": "unavailable"' "$DOC"
grep -q '"canary_mutant_failed": null' "$DOC"
grep -q "must not contain the raw \`--canary-target\` input" "$DOC"
grep -q "Do not use a broad \`git restore\`" "$DOC"

python3 -m py_compile scripts/operating-layer.py scripts/proof-canary-observability.py
python3 scripts/proof-canary-observability.py --proofs "$PROOFS" --out "$TMP_DIR/report.json" > "$TMP_DIR/report.stdout"
python3 - "$TMP_DIR/report.json" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1]))
assert report["status"] == "alert"
assert report["counts"]["legacy_receipts"] > 0
assert report["privacy"] == {
    "includes_raw_commands": False,
    "includes_canary_target_paths": False,
}
assert "verify_command" not in json.dumps(report)
assert '"canary_target":' not in json.dumps(report)
PY

python3 scripts/tests/operating_layer_test.py
git diff --check

printf '%s\n' "PASS proof-canary documentation verifier"
