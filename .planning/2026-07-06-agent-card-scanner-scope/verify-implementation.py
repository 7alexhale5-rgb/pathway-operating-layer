#!/usr/bin/env python3
"""Verify the implemented scanner scope against its governed local fixtures."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
ARTIFACT_DIR = ROOT / ".planning" / "2026-07-06-agent-card-scanner-scope"
SIGNAL = ARTIFACT_DIR / "SCANNER_SCOPE_SIGNAL.json"


def run(command: list[str]) -> int:
    proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
    if proc.returncode:
        print(proc.stderr.strip() or proc.stdout.strip(), file=sys.stderr)
    return proc.returncode


def scanner_test_command() -> list[str]:
    code = """
import runpy
ns = runpy.run_path('scripts/tests/operating_layer_test.py', run_name='scanner_scope_tests')
for name in (
    'test_portfolio_evidence_ai_boundary_agent_cards',
    'test_agent_cards_reject_symlinked_candidates_and_markers',
    'test_agent_cards_scope_excludes_helper_and_legacy_records',
):
    ns['_failures'].clear()
    ns['_passes'] = 0
    ns[name]()
    if ns['_failures']:
        raise SystemExit(f'{name} failed: {ns["_failures"]}')
print('PASS focused scanner regression tests')
"""
    return [sys.executable, "-c", code]


def main() -> int:
    commands = [
        [sys.executable, "-m", "py_compile", "scripts/operating-layer.py"],
        [sys.executable, str(ARTIFACT_DIR / "scanner-scope-observability.py"), "--expect", "pass"],
        [sys.executable, str(ARTIFACT_DIR / "verify-data.py")],
        [sys.executable, str(ARTIFACT_DIR / "verify-security.py")],
        scanner_test_command(),
    ]
    if any(run(command) for command in commands):
        return 1
    signal = json.loads(SIGNAL.read_text(encoding="utf-8"))
    if signal != {
        "agent_cards_scope_false_blockers": 0,
        "expected_selected_systems": ["atlas-ceo"],
        "external_calls": False,
        "false_blocker_systems": [],
        "missing_real_profile_systems": [],
        "selected_systems": ["atlas-ceo"],
        "status": "pass",
    }:
        print(f"unexpected implementation signal: {signal}", file=sys.stderr)
        return 1
    print("PASS scanner scope implementation verifier")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
