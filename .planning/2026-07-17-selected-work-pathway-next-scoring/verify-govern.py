#!/usr/bin/env python3
"""Verify the selected-work scoring governance decision without mutating runtime state."""

from pathlib import Path
import subprocess
import sys


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
ARTIFACT = ROOT / ".planning/2026-07-17-selected-work-pathway-next-scoring/GOVERN.md"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    text = ARTIFACT.read_text(encoding="utf-8")

    headings = [
        "## Decision",
        "## Signal Boundary",
        "## Metric And Acceptance Criteria",
        "## Cost And Risk",
        "## Rollback",
        "## Verifier",
        "## Summary",
        "## What Changed",
        "## More Relevant",
        "## Less Relevant",
        "## Next Pathway Must Use",
        "## Do Not Do Yet",
        "## Open Decisions",
        "## Active Risk Overlays",
    ]
    for heading in headings:
        require(text.count(heading) == 1, f"missing or duplicate heading: {heading}")

    required_phrases = [
        "sole authority for outcome-scoped scoring",
        "most-recently-updated active-work ordering",
        "cross_outcome_signal_leakage_count",
        "Acceptance target: `0`",
        "Selected outcome",
        "Project-scoped findings",
        "Portfolio",
        "older-stale-ignored",
        "selected-stale-counted",
        "control-boundary",
        "coverage-boundary",
        "project-finding-preserved",
        "identity-coherence",
        "portfolio-visibility",
        "metamorphic-isolation",
        "seventeen",
        "promote any genuinely project-wide live blocker",
        "caller-level scoping change",
        "No migration, deployment, external send, or production mutation",
    ]
    for phrase in required_phrases:
        require(phrase in text, f"missing governed condition: {phrase}")

    require(text.index("## Decision") < text.index("## Metric And Acceptance Criteria"),
            "decision must precede its metric")
    require(text.index("## Metric And Acceptance Criteria") < text.index("## Cost And Risk"),
            "metric must precede cost and risk")

    result = subprocess.run(
        ["git", "diff", "--check", "--", str(ARTIFACT), str(Path(__file__))],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    require(result.returncode == 0, result.stdout + result.stderr)

    print("PASS selected-work pathway-next governance verifier")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError) as exc:
        print(f"FAIL selected-work pathway-next governance verifier: {exc}", file=sys.stderr)
        raise SystemExit(1)
