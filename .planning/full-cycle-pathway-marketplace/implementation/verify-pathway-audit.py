#!/usr/bin/env python3
"""Exercise the read-only Pathway Audit v1 contract against the real local ledgers."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
CLI = ROOT / "scripts" / "operating-layer.py"


def main() -> int:
    proc = subprocess.run(
        [sys.executable, str(CLI), "pathway-audit", "--project", str(ROOT), "--json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if proc.returncode != 0:
        raise SystemExit(f"pathway-audit failed: {proc.stderr.strip()}")
    audit = json.loads(proc.stdout)
    required = {
        "overall_score", "pathway_scores", "metric_snapshot", "drift_findings",
        "highest_value_refinements", "report", "html",
    }
    missing = sorted(required - set(audit))
    if missing:
        raise SystemExit(f"audit JSON missing fields: {missing}")
    if not isinstance(audit["overall_score"], int) or not 0 <= audit["overall_score"] <= 100:
        raise SystemExit("audit score is not a bounded integer")
    if not Path(audit["report"]).is_file() or not Path(audit["html"]).is_file():
        raise SystemExit("audit did not render both operator reports")
    if not audit["drift_findings"]:
        raise SystemExit("current incomplete scorecard should expose at least one actionable finding")
    print(f"PASS pathway-audit contract score={audit['overall_score']} drift={len(audit['drift_findings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
