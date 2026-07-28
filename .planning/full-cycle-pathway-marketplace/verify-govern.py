#!/usr/bin/env python3
"""Verify the govern proof for the pathway command 92+ push."""

from __future__ import annotations

import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    "Decision",
    "Governing Metric",
    "Acceptance Gate",
    "First Implementation Slice",
    "Scope Boundaries",
    "Verifier Good",
    "Summary",
    "What Changed",
    "More Relevant",
    "Less Relevant",
    "Next Pathway Must Use",
    "Do Not Do Yet",
    "Open Decisions",
    "Active Risk Overlays",
]


REQUIRED_SNIPPETS = [
    "overall_score >= 92",
    "pathway-audit --project",
    "Research proof conversion reaches `>= 0.25`",
    "Field proof conversion reaches `>= 0.30`",
    "--verify-cmd",
    "W-20260706-pathway-operating-layer-raise-pathway-command-to-3402fb",
    "pathway-audit` is the first implementation slice",
    "Do not log proof against `W-20260706-pathway-operating-layer-fix-agent-card-scanner-s-c64f27`",
    "rollback",
    "human-gate",
    "llm-agent-eval",
]

TRACKED_ANCHORS = [
    (
        Path("/Users/alexhale/Projects/pathway-operating-layer/README.md"),
        "# 6. Start a measured real-project pilot cohort",
    ),
]


def fail(message: str) -> int:
    print(f"FAIL: {message}", file=sys.stderr)
    return 1


def has_heading(text: str, heading: str) -> bool:
    pattern = rf"(?m)^##\s+{re.escape(heading)}\s*$"
    return re.search(pattern, text) is not None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return fail("usage: verify-govern.py /absolute/path/to/GOVERN.md")

    artifact = Path(argv[1]).expanduser()
    if not artifact.is_absolute():
        return fail("artifact path must be absolute")
    if not artifact.exists():
        return fail(f"artifact does not exist: {artifact}")

    text = artifact.read_text(encoding="utf-8")
    missing_sections = [section for section in REQUIRED_SECTIONS if not has_heading(text, section)]
    if missing_sections:
        return fail(f"missing required sections: {', '.join(missing_sections)}")

    missing_snippets = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in text]
    if missing_snippets:
        return fail(f"missing required snippets: {', '.join(missing_snippets)}")

    if "--verified-by" in text:
        return fail("govern proof must not present --verified-by as proof")

    for path, expected in TRACKED_ANCHORS:
        if expected not in path.read_text(encoding="utf-8"):
            return fail(f"tracked anchor missing from {path}: {expected}")

    print(f"PASS: govern proof is complete: {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
