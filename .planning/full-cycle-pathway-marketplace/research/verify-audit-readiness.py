#!/usr/bin/env python3
"""Verify that research clears the read-only pathway-audit implementation slice."""

from __future__ import annotations

from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
RESEARCH = ROOT / ".planning" / "full-cycle-pathway-marketplace" / "research" / "AUDIT_READINESS.md"
GOVERN = ROOT / ".planning" / "full-cycle-pathway-marketplace" / "GOVERN.md"
SPEC = ROOT / ".planning" / "full-cycle-pathway-marketplace" / "KARPATHY-SPEC.md"
ENGINE = ROOT / "scripts" / "operating-layer.py"


def main() -> int:
    text = RESEARCH.read_text(encoding="utf-8")
    required = [
        "## Answer",
        "They are sufficient.",
        "overall_score",
        "pathway_scores",
        "metric_snapshot",
        "drift_findings",
        "highest_value_refinements",
        "Exit zero when the command completed its measurement, even below `92`",
        "No blocker prevents implementation.",
        "## Unknowns And Classification",
        "## Next Pathway Must Use",
        "`rollback`, `human-gate`, `llm-agent-eval`.",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise SystemExit(f"research addendum missing: {missing}")
    for required_field in ("overall_score", "pathway_scores", "metric_snapshot", "drift_findings", "highest_value_refinements"):
        if required_field not in GOVERN.read_text(encoding="utf-8"):
            raise SystemExit(f"govern source lacks {required_field}")
    if "Slice 2 — `pathway-audit`" not in SPEC.read_text(encoding="utf-8"):
        raise SystemExit("spec lacks the pathway-audit slice")
    if "pathway-audit" in ENGINE.read_text(encoding="utf-8"):
        raise SystemExit("pathway-audit already exists; research conclusion is stale")
    print("PASS pathway-audit research readiness")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
