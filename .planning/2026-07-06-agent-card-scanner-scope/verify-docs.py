#!/usr/bin/env python3
"""Verify the durable scanner-scope runbook is linked and actionably complete."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
RUNBOOK = ROOT / "docs" / "agent-card-scanner-scope.md"
README = ROOT / "README.md"
RECEIPT = ROOT / ".planning" / "2026-07-06-agent-card-scanner-scope" / "DOCS_RECEIPT.txt"


def main() -> int:
    text = RUNBOOK.read_text(encoding="utf-8")
    required = [
        "agent_cards_scope_false_blockers = 0",
        'selected_systems = ["atlas-ceo"]',
        "hermes/profiles/",
        "Exclude generic helper folders",
        "Exclude legacy Codex automations",
        "Exclude symlinked candidates",
        "--expect alert",
        "--expect pass",
        "verify-data.py",
        "verify-security.py",
        "scripts/tests/operating_layer_test.py",
        "does not mutate a Hermes runtime profile",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        print(f"runbook missing: {missing}", file=sys.stderr)
        return 1
    if "docs/agent-card-scanner-scope.md" not in README.read_text(encoding="utf-8"):
        print("README does not link the scanner-scope runbook", file=sys.stderr)
        return 1
    RECEIPT.write_text("PASS scanner-scope runbook linked and actionable\n", encoding="utf-8")
    print("PASS scanner-scope docs verifier")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
