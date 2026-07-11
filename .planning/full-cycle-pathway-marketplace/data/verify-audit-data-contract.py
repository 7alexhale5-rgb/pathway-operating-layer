#!/usr/bin/env python3
"""Verify Audit v1 emits a self-describing, internally consistent local data payload."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
ENGINE = ROOT / "scripts" / "operating-layer.py"


def main() -> int:
    spec = importlib.util.spec_from_file_location("pathway_audit_contract", ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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
    errors = module.validate_pathway_audit_payload(audit)
    if errors:
        raise SystemExit(f"invalid audit payload: {errors}")
    sources = audit["data_lineage"]["sources"]
    if not all(Path(path).name.endswith((".json", ".ndjson")) for path in sources.values()):
        raise SystemExit("audit lineage contains a non-ledger source")
    print(f"PASS audit data contract {audit['data_lineage']['schema_version']} sources={len(sources)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
