#!/usr/bin/env python3
"""Verify every Pathway has a template and an empty artifact cannot satisfy it."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
ENGINE = ROOT / "scripts" / "operating-layer.py"
EXPECTED = {"govern", "research", "data", "security", "design", "implementation", "quality", "field", "observability", "techdebt", "release", "docs"}


def main() -> int:
    spec = importlib.util.spec_from_file_location("pathway_templates", ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if set(module.VERIFIER_TEMPLATES) != EXPECTED:
        raise SystemExit("verifier template registry does not cover the canonical catalog")
    if any(module.check_verifier_template(pathway, "")["valid"] for pathway in EXPECTED):
        raise SystemExit("an empty artifact satisfied a verifier template")
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
    if audit.get("metric_snapshot", {}).get("verifier_template_count") != len(EXPECTED):
        raise SystemExit("audit does not report complete verifier-template coverage")
    print(f"PASS verifier templates={len(EXPECTED)} hollow_rejections={len(EXPECTED)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
