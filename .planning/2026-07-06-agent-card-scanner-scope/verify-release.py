#!/usr/bin/env python3
"""Verify the release receipt for the agent-card scanner-scope fix."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
RECEIPT = ROOT / ".planning" / "2026-07-06-agent-card-scanner-scope" / "RELEASE.md"
EXPECTED_RECEIPT_SHA256 = "e6e54252dcbf4ecd8a9283bf7e9bff1f690102fe332f1eb27ce7ffa66f4adc88"

REQUIRED_PHRASES = [
    "Ship this as a local operating-layer scanner correction",
    "must not mutate Hermes runtime profiles",
    "The rollout is a controlled local canary",
    "`agent_cards_scope_false_blockers` is `0`",
    "proof command guards the current first dirty diff line",
    "grep -Fx '# 6. Start a measured real-project pilot cohort' README.md",
    "git restore -- scripts/operating-layer.py scripts/tests/operating_layer_test.py",
    "git revert <scanner-scope-commit-sha>",
    "A focused scanner-scope fixture proves false blockers are zero",
    "real incomplete agent candidate still produces an",
    "incomplete-readiness warning",
    "No runtime profile push, Slack send, cron mutation, launchd mutation, deploy",
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
            f"release receipt hash mismatch: expected {EXPECTED_RECEIPT_SHA256}, got {actual_hash}",
            file=sys.stderr,
        )
        return 1

    missing = [phrase for phrase in REQUIRED_PHRASES if phrase not in text]
    if missing:
        print("release receipt missing required content:", file=sys.stderr)
        for phrase in missing:
            print(f"- {phrase}", file=sys.stderr)
        return 1

    if "Status: pass" not in text or "Pathway: release" not in text:
        print("release receipt is not marked as a passing release artifact", file=sys.stderr)
        return 1

    print("release receipt verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
