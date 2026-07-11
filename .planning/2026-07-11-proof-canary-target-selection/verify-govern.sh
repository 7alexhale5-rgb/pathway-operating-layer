#!/usr/bin/env bash
# Verify the proof-canary target-selection decision without changing runtime behavior.
set -euo pipefail

ROOT="/Users/alexhale/Projects/pathway-operating-layer"
ARTIFACT="$ROOT/.planning/2026-07-11-proof-canary-target-selection/GOVERN.md"

cd "$ROOT"

test -s "$ARTIFACT"
for heading in \
  "## Decision" \
  "## Metric And Acceptance Criteria" \
  "## Cost And Risk" \
  "## Rollback" \
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
grep -q "unrelated_dirty_false_demotions" "$ARTIFACT"
grep -q "canary_mutant_failed: true" "$ARTIFACT"
grep -q "canary_mutant_failed: false" "$ARTIFACT"
grep -q "returns \`None\`" "$ARTIFACT"

python3 -m py_compile scripts/operating-layer.py
for test_name in \
  test_verifier_receipt_canary_mutant_catches_noop_verifier \
  test_canary_mutant_is_symlink_safe \
  test_canary_mutant_resolves_repo_root_from_subdir \
  test_canary_honors_explicit_project_over_dirty_registered_checkout; do
  grep -q "def $test_name" scripts/tests/operating_layer_test.py
done
git diff --check -- "$ARTIFACT" "$0"

printf '%s\n' "PASS proof-canary governance verifier"
