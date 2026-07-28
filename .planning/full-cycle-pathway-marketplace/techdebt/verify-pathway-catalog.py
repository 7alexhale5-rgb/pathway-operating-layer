#!/usr/bin/env python3
"""Verify the canonical Pathway catalog is aligned across audited authority surfaces."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
CLI = ROOT / "scripts" / "operating-layer.py"
CATALOG = "govern, research, data, security, design, implementation, quality, field, observability, techdebt, release, docs"


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
    drift = audit.get("drift_findings", [])
    catalog_drift = [item for item in drift if "canonical-pathway-catalog" in item.get("id", "")]
    if catalog_drift:
        raise SystemExit(f"catalog drift remains: {catalog_drift}")
    documentation = next(
        (item for item in audit.get("pathway_scores", []) if item.get("dimension") == "documentation alignment"),
        None,
    )
    if not documentation or documentation.get("score") != documentation.get("max_score"):
        raise SystemExit("documentation alignment is not fully scored")
    source = (ROOT / "scripts" / "operating-layer.py").read_text(encoding="utf-8")
    if f'CANONICAL_PATHWAY_CATALOG = "{CATALOG}"' not in source:
        raise SystemExit("engine catalog constant does not match the governed order")
    print(f"PASS canonical catalog aligned score={audit['overall_score']} docs={documentation['evidence']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
