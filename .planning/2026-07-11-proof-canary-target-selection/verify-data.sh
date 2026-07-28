#!/usr/bin/env bash
# Verify the proof-canary receipt contract without changing proof-engine behavior.
set -euo pipefail

ROOT="/Users/alexhale/Projects/pathway-operating-layer"
ARTIFACT_DIR="$ROOT/.planning/2026-07-11-proof-canary-target-selection"
ARTIFACT="$ARTIFACT_DIR/DATA.md"
EXAMPLE="$ARTIFACT_DIR/CANARY_RECEIPT.example.json"

cd "$ROOT"

test -s "$ARTIFACT"
test -s "$EXAMPLE"
for heading in \
  "## Record Contract" \
  "## Selection Boundary" \
  "## Compatibility" \
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

python3 - "$EXAMPLE" <<'PY'
import json
import sys

record = json.load(open(sys.argv[1]))
assert record == {
    "canary_target": "value.txt",
    "canary_target_source": "explicit",
    "canary_target_reason": "explicit_changed_regular_file",
    "canary_mutant_failed": True,
}
assert not record["canary_target"].startswith("/")
PY

python3 -m py_compile scripts/operating-layer.py
grep -q '"canary_mutant_failed": canary_mutant_failed' scripts/operating-layer.py
grep -q 'parser.add_argument("--verify-cmd"' scripts/operating-layer.py
git diff --check -- "$ARTIFACT" "$EXAMPLE" "$0"

printf '%s\n' "PASS proof-canary data verifier"
