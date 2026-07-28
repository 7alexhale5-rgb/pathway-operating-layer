#!/usr/bin/env python3
"""Run the scanner-scope regression gate after the implementation is present."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
ARTIFACT_DIR = ROOT / ".planning" / "2026-07-06-agent-card-scanner-scope"


def run(command: list[str]) -> int:
    proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
    if proc.returncode:
        print(proc.stderr.strip() or proc.stdout.strip(), file=sys.stderr)
    return proc.returncode


def scanner_test_command() -> list[str]:
    code = """
import runpy
ns = runpy.run_path('scripts/tests/operating_layer_test.py', run_name='scanner_scope_quality')
name = 'test_agent_cards_scope_excludes_helper_and_legacy_records'
ns['_failures'].clear()
ns['_passes'] = 0
ns[name]()
if ns['_failures']:
    raise SystemExit(f'{name} failed: {ns["_failures"]}')
print('PASS main-suite scanner scope regression')
"""
    return [sys.executable, "-c", code]


def main() -> int:
    commands = [
        [sys.executable, str(ARTIFACT_DIR / "verify-implementation.py")],
        [sys.executable, str(ARTIFACT_DIR / "verify-docs.py")],
        scanner_test_command(),
        ["git", "diff", "--check"],
    ]
    if any(run(command) for command in commands):
        return 1
    print("PASS scanner scope quality gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
