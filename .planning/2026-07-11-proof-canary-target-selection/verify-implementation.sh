#!/usr/bin/env bash
# Exercise the implemented proof-canary selector through the CLI in an isolated temporary checkout.
set -euo pipefail

ROOT="/Users/alexhale/Projects/pathway-operating-layer"
ARTIFACT_DIR="$ROOT/.planning/2026-07-11-proof-canary-target-selection"
ARTIFACT="$ARTIFACT_DIR/IMPLEMENTATION.md"
RECEIPT="$ARTIFACT_DIR/IMPLEMENTATION_RECEIPT.json"
TMP_DIR="$(mktemp -d -t proof-canary-implementation.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

cd "$ROOT"

test -s "$ARTIFACT"
python3 -m py_compile scripts/operating-layer.py scripts/proof-canary-observability.py
python3 - "$ROOT/scripts/operating-layer.py" "$TMP_DIR" "$RECEIPT" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

cli = Path(sys.argv[1])
tmp = Path(sys.argv[2])
receipt_path = Path(sys.argv[3])
repo = tmp / "repo"
out = tmp / "out"
evidence = tmp / "evidence.md"
repo.mkdir()

def git(*args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)

git("init", "-q")
git("config", "user.email", "proof@example.test")
git("config", "user.name", "Proof Canary")
(repo / "value.txt").write_text("42\n", encoding="utf-8")
(repo / "unrelated.yml").write_text("jobs: e2e\n", encoding="utf-8")
git("add", "-A")
git("commit", "-q", "-m", "baseline")
(repo / "value.txt").write_text("100\n", encoding="utf-8")
(repo / "unrelated.yml").write_text("jobs: e2e-stale\n", encoding="utf-8")
evidence.write_text("implementation proof\n", encoding="utf-8")

def prove(pathway, command, *extra):
    proc = subprocess.run([
        sys.executable, str(cli), "proof-add", "--output-root", str(out),
        "--project", str(repo), "--pathway", pathway, "--proof-type", "artifact",
        "--result", "pass", "--evidence", str(evidence), "--verify-cmd", command, *extra,
        "--json",
    ], check=True, capture_output=True, text=True)
    return json.loads(proc.stdout)["records"][0]

named = prove("implementation", "grep 100 value.txt")
opaque = prove("quality", "printf checked")
explicit = prove("observability", "printf checked", "--canary-target", str(repo / "value.txt"))

assert named["canary_target"] == "value.txt"
assert named["canary_target_source"] == "verifier_reference"
assert named["canary_target_reason"] == "verifier_named_changed_file"
assert named["canary_mutant_failed"] is True and named["trivial_verifier"] is False
assert opaque["canary_target"] is None
assert opaque["canary_target_source"] == "unavailable"
assert opaque["canary_target_reason"] == "no_relevant_changed_file"
assert opaque["canary_mutant_failed"] is None and opaque["trivial_verifier"] is False
assert explicit["canary_target"] == "value.txt"
assert explicit["canary_target_source"] == "explicit"
assert explicit["canary_target_reason"] == "explicit_changed_regular_file"
assert explicit["canary_mutant_failed"] is False and explicit["trivial_verifier"] is True
assert not explicit["canary_target"].startswith("/")
assert (repo / "value.txt").read_text(encoding="utf-8") == "100\n"
assert (repo / "unrelated.yml").read_text(encoding="utf-8") == "jobs: e2e-stale\n"

receipt = {
    "automatic_named_target": {key: named[key] for key in (
        "canary_target", "canary_target_source", "canary_target_reason", "canary_mutant_failed", "trivial_verifier",
    )},
    "opaque_unavailable_target": {key: opaque[key] for key in (
        "canary_target", "canary_target_source", "canary_target_reason", "canary_mutant_failed", "trivial_verifier",
    )},
    "explicit_ignored_target": {key: explicit[key] for key in (
        "canary_target", "canary_target_source", "canary_target_reason", "canary_mutant_failed", "trivial_verifier",
    )},
    "restored_value": (repo / "value.txt").read_text(encoding="utf-8").strip(),
    "unrelated_file_unchanged": (repo / "unrelated.yml").read_text(encoding="utf-8").strip(),
}
receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

python3 - "$RECEIPT" <<'PY'
import json
import sys

receipt = json.load(open(sys.argv[1]))
assert receipt["automatic_named_target"]["canary_mutant_failed"] is True
assert receipt["opaque_unavailable_target"]["canary_target"] is None
assert receipt["opaque_unavailable_target"]["trivial_verifier"] is False
assert receipt["explicit_ignored_target"]["canary_mutant_failed"] is False
assert receipt["explicit_ignored_target"]["canary_target"] == "value.txt"
assert receipt["restored_value"] == "100"
assert receipt["unrelated_file_unchanged"] == "jobs: e2e-stale"
assert "/" not in receipt["explicit_ignored_target"]["canary_target"]
PY

python3 scripts/tests/operating_layer_test.py
git diff --check

printf '%s\n' "PASS proof-canary implementation verifier"
