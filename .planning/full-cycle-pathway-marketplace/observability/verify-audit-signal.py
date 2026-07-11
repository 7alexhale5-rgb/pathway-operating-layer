#!/usr/bin/env python3
"""Verify the Audit v1 observability signal is local, compact, and non-sensitive."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
ENGINE = ROOT / "scripts" / "operating-layer.py"


def main() -> int:
    proc = subprocess.run(
        [sys.executable, str(ENGINE), "pathway-audit", "--project", str(ROOT), "--json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if proc.returncode != 0:
        raise SystemExit(f"pathway-audit failed: {proc.stderr.strip()}")
    audit = json.loads(proc.stdout)
    signal = json.loads(Path(audit["signal"]).read_text(encoding="utf-8"))
    required = {"schema_version", "overall_score", "coverage", "recommendation_proved_rate", "verifier_template_count", "template_mismatch_count", "canary", "drift_count"}
    if required - set(signal):
        raise SystemExit("audit signal omits required health fields")
    if signal["overall_score"] != audit["overall_score"] or signal["coverage"]["covered"] != audit["metric_snapshot"]["covered_pathways"]:
        raise SystemExit("audit signal is not consistent with the measured audit")
    serialized = json.dumps(signal)
    if "verify_command" in serialized or "evidence_path" in serialized:
        raise SystemExit("audit signal leaks proof implementation detail")
    print(f"PASS audit signal score={signal['overall_score']} coverage={signal['coverage']['covered']}/{signal['coverage']['required']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
