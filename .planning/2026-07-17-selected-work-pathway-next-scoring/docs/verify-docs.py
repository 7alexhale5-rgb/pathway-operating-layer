#!/usr/bin/env python3
"""Verify the selected-work ADR is complete, discoverable, and source-aligned."""

from pathlib import Path
import ast
import subprocess
import sys


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
DOC = ROOT / "docs/selected-work-pathway-next-scoring.md"
README = ROOT / "README.md"
SOURCE = ROOT / "scripts/operating-layer.py"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    text = DOC.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    source = SOURCE.read_text(encoding="utf-8")

    for heading in (
        "## The Answer",
        "## Operator Invariant",
        "## Delivered Contract",
        "## Selection And No-Active Behavior",
        "## Required Regression Corpus",
        "## Control Safety",
        "## Verification",
        "## Compatibility And Rollback",
        "## Summary",
        "## What Changed",
        "## More Relevant",
        "## Less Relevant",
        "## Next Pathway Must Use",
        "## Do Not Do Yet",
        "## Open Decisions",
        "## Active Risk Overlays",
    ):
        require(text.count(heading) == 1, f"missing or duplicate heading: {heading}")

    for phrase in (
        "singular optional summary, named `active_summary`",
        "Older `17` stale measurements",
        "Two selected missing-evidence records",
        "project security finding retains its score and reason",
        "work-status and portfolio-next",
        "Do not use `work-log` for the older mutation",
        "persisted recommendation IDs are expected to differ",
        "Without `--work-id`, active work remains ordered",
        "nested checkout under the requested project root is valid",
        "unknown, closed, or different-project ID fails closed",
        "does not add control-scope fields",
        "Do not change scoring weights, portfolio aggregation, or control schema",
        "implementation/verify-selected-work-scoring.py",
        "Pre-implementation research evidence",
        "Data must verify the singular `active_summary` contract",
        "No deployment, external send, production flag, data migration, or work close",
    ):
        require(phrase in text, f"missing ADR contract: {phrase}")

    require("docs/selected-work-pathway-next-scoring.md" in readme,
            "README does not link the selected-work scoring ADR")

    tree = ast.parse(source)
    definitions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "score_pathways"
    ]
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "score_pathways"
    ]
    require(len(definitions) == 1 and len(calls) == 1,
            "ADR no longer matches the one-definition/one-caller scorer architecture")

    diff = subprocess.run(
        ["git", "diff", "--check", "--", str(DOC), str(README), str(Path(__file__))],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    require(diff.returncode == 0, diff.stdout + diff.stderr)

    print("PASS selected-work pathway-next documentation verifier")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, SyntaxError) as exc:
        print(f"FAIL selected-work pathway-next documentation verifier: {exc}", file=sys.stderr)
        raise SystemExit(1)
