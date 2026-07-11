#!/usr/bin/env python3
"""Verify Audit v1 scores active proof readiness separately from historical ledger hygiene."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
ENGINE = ROOT / "scripts" / "operating-layer.py"


def main() -> int:
    spec = importlib.util.spec_from_file_location("pathway_active_proof_scope", ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    active = {"work_id": "active", "verifier_strength": "executed", "exit_code": 0, "trivial_verifier": False, "canary_mutant_failed": None, "result": "pass"}
    historical = {"work_id": "old", "verifier_strength": "attested", "exit_code": None, "trivial_verifier": False, "canary_mutant_failed": None, "result": "pass"}
    sample = module.audit_proof_integrity_snapshot([active, historical], ["active"])
    if sample["verified_count"] != 1 or sample["proof_count"] != 1 or sample["historical_unverified_count"] != 1:
        raise SystemExit("active proof scope does not preserve the historical baseline")
    proc = subprocess.run([sys.executable, str(ENGINE), "pathway-audit", "--project", str(ROOT), "--json"], cwd=ROOT, check=False, capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        raise SystemExit(f"pathway-audit failed: {proc.stderr.strip()}")
    audit = json.loads(proc.stdout)
    metric = audit["metric_snapshot"]
    if metric["proof_integrity_scope"] != "active outcomes" or metric["proof_integrity_verified_count"] != metric["proof_integrity_proof_count"]:
        raise SystemExit("current active work is not fully reflected in proof integrity")
    print(f"PASS active proof scope={metric['proof_integrity_verified_count']}/{metric['proof_integrity_proof_count']} historical_unverified={metric['historical_unverified_proof_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
