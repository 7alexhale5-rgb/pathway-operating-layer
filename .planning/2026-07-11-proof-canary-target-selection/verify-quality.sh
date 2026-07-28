#!/usr/bin/env bash
# Exercise the rejected explicit-target boundary through the public CLI.
set -euo pipefail

ROOT="/Users/alexhale/Projects/pathway-operating-layer"
ARTIFACT_DIR="$ROOT/.planning/2026-07-11-proof-canary-target-selection"
ARTIFACT="$ARTIFACT_DIR/QUALITY.md"
RECEIPT="$ARTIFACT_DIR/QUALITY_RECEIPT.json"
TEST_OUTPUT="$ARTIFACT_DIR/QUALITY_TEST_OUTPUT.txt"
TMP_DIR="$(mktemp -d -t proof-canary-quality.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

cd "$ROOT"

test -s "$ARTIFACT"
python3 -m py_compile scripts/operating-layer.py scripts/tests/operating_layer_test.py
python3 - "$ROOT/scripts/operating-layer.py" "$TMP_DIR" "$RECEIPT" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

cli = Path(sys.argv[1])
tmp = Path(sys.argv[2])
receipt_path = Path(sys.argv[3])
repo = tmp / "repo"
outside = tmp / "OUTSIDE.txt"
out = tmp / "out"
evidence = tmp / "evidence.md"
repo.mkdir()
outside.write_text("DO NOT TOUCH\n", encoding="utf-8")

def git(*args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)

git("init", "-q")
git("config", "user.email", "quality@example.test")
git("config", "user.name", "Proof Canary Quality")
(repo / "value.txt").write_text("42\n", encoding="utf-8")
(repo / "unchanged.txt").write_text("stable\n", encoding="utf-8")
git("add", "-A")
git("commit", "-q", "-m", "baseline")
(repo / "value.txt").write_text("100\n", encoding="utf-8")
evidence.write_text("quality proof\n", encoding="utf-8")

def prove(pathway, target):
    proc = subprocess.run([
        sys.executable, str(cli), "proof-add", "--output-root", str(out),
        "--project", str(repo), "--pathway", pathway, "--proof-type", "artifact",
        "--result", "pass", "--evidence", str(evidence), "--verify-cmd", "printf checked",
        "--canary-target", target, "--json",
    ], check=True, capture_output=True, text=True)
    return json.loads(proc.stdout)["records"][0]

outside_proof = prove("quality", str(outside))
unchanged_proof = prove("observability", "unchanged.txt")
for proof, reason in (
    (outside_proof, "explicit_target_outside_verification_checkout"),
    (unchanged_proof, "explicit_target_not_changed_regular_file"),
):
    assert proof["canary_target"] is None
    assert proof["canary_target_source"] == "unavailable"
    assert proof["canary_target_reason"] == reason
    assert proof["canary_mutant_failed"] is None
    assert proof["trivial_verifier"] is False
assert str(outside) not in json.dumps(outside_proof)
assert outside.read_text(encoding="utf-8") == "DO NOT TOUCH\n"
assert (repo / "unchanged.txt").read_text(encoding="utf-8") == "stable\n"

receipt_path.write_text(json.dumps({
    "outside_target": {key: outside_proof[key] for key in (
        "canary_target", "canary_target_source", "canary_target_reason", "canary_mutant_failed", "trivial_verifier",
    )},
    "unchanged_target": {key: unchanged_proof[key] for key in (
        "canary_target", "canary_target_source", "canary_target_reason", "canary_mutant_failed", "trivial_verifier",
    )},
    "outside_file_unchanged": outside.read_text(encoding="utf-8").strip(),
    "unchanged_file_unchanged": (repo / "unchanged.txt").read_text(encoding="utf-8").strip(),
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

python3 scripts/tests/operating_layer_test.py > "$TEST_OUTPUT"
cat "$TEST_OUTPUT"
python3 - "$RECEIPT" "$TEST_OUTPUT" <<'PY'
import json
import sys

receipt = json.load(open(sys.argv[1]))
output = open(sys.argv[2]).read()
for outcome in (receipt["outside_target"], receipt["unchanged_target"]):
    assert outcome["canary_target"] is None
    assert outcome["canary_target_source"] == "unavailable"
    assert outcome["canary_mutant_failed"] is None
    assert outcome["trivial_verifier"] is False
assert receipt["outside_file_unchanged"] == "DO NOT TOUCH"
assert receipt["unchanged_file_unchanged"] == "stable"
assert "/" not in json.dumps(receipt)
assert "checks passed" in output
PY
git diff --check

printf '%s\n' "PASS proof-canary quality verifier"
