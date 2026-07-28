#!/usr/bin/env python3
"""Verify the govern receipt for the agent-card scanner-scope fix."""

from __future__ import annotations

import sys
import hashlib
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
RECEIPT = ROOT / ".planning" / "2026-07-06-agent-card-scanner-scope" / "GOVERN.md"
EXPECTED_RECEIPT_SHA256 = "70f546e4f3012cd9b57465cbe6f73393d917275acd6c277167d4c60f7ea956f5"

REQUIRED_PHRASES = [
    "Primary metric: `agent_cards_scope_false_blockers`",
    "Target: `0`",
    "Preserve the warning for a real incomplete agent candidate.",
    "Exclude non-agent helper folders such as `tenants` and `mcp-servers`",
    "Exclude legacy Codex automations from this readiness blocker",
    "explicit inclusion signals",
    "do not weaken readiness scoring for real agent candidates",
    "next_pathway_must_use:",
    "active_risk_overlays: `llm-agent-eval`.",
]


def main() -> int:
    if not RECEIPT.is_file():
        print(f"missing receipt: {RECEIPT}", file=sys.stderr)
        return 1

    text = RECEIPT.read_text(encoding="utf-8")
    actual_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if actual_hash != EXPECTED_RECEIPT_SHA256:
        print(
            f"govern receipt hash mismatch: expected {EXPECTED_RECEIPT_SHA256}, got {actual_hash}",
            file=sys.stderr,
        )
        return 1

    missing = [phrase for phrase in REQUIRED_PHRASES if phrase not in text]
    if missing:
        print("govern receipt missing required content:", file=sys.stderr)
        for phrase in missing:
            print(f"- {phrase}", file=sys.stderr)
        return 1

    if "Status: pass" not in text or "Pathway: govern" not in text:
        print("govern receipt is not marked as a passing govern artifact", file=sys.stderr)
        return 1

    print("govern receipt verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
