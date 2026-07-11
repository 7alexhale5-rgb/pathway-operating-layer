#!/usr/bin/env python3
"""Verify the scanner-scope baseline alert is emitted as structured local evidence."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
ARTIFACT_DIR = ROOT / ".planning" / "2026-07-06-agent-card-scanner-scope"
SIGNAL = ARTIFACT_DIR / "SCANNER_SCOPE_SIGNAL.json"


def main() -> int:
    command = [sys.executable, str(ARTIFACT_DIR / "scanner-scope-observability.py"), "--expect", "alert"]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        print(proc.stderr.strip(), file=sys.stderr)
        return 1
    signal = json.loads(SIGNAL.read_text(encoding="utf-8"))
    if signal != {
        "agent_cards_scope_false_blockers": 3,
        "expected_selected_systems": ["atlas-ceo"],
        "external_calls": False,
        "false_blocker_systems": ["legacy-job", "mcp-servers", "tenants"],
        "missing_real_profile_systems": ["atlas-ceo"],
        "selected_systems": ["legacy-job", "mcp-servers", "tenants"],
        "status": "alert",
    }:
        print(f"unexpected baseline signal: {signal}", file=sys.stderr)
        return 1
    print("PASS scanner scope observability baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
