#!/usr/bin/env python3
"""Deterministic post-fix verifier for selected-work pathway-next scoring."""

from __future__ import annotations

import ast
import runpy
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "scripts/operating-layer.py"
TESTS = ROOT / "scripts/tests/operating_layer_test.py"
EXPECTED_CONFORMANCE_ASSERTIONS = 32


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def verify_boundary_shape() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    scorer = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "score_pathways"
    )
    compute = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "compute_pathway_next"
    )
    require(scorer.args.args[4].arg == "active_summary",
            "score_pathways outcome input is not singular active_summary")
    scorer_text = ast.get_source_segment(source, scorer) or ""
    compute_text = ast.get_source_segment(source, compute) or ""
    require("for summary in work_summaries" not in scorer_text,
            "score_pathways still aggregates project work summaries")
    require("work_summaries" not in compute_text,
            "compute_pathway_next still constructs or passes aggregate work summaries")
    require("requested_work_id" in compute_text and "work_item_is_within_project" in compute_text
            and "pathway-next-work-id-not-active" in compute_text,
            "compute_pathway_next does not enforce explicit active work selection")
    require("scoped_findings" in scorer_text and "learned_pathway_closures" in scorer_text,
            "project findings or closed-outcome learning were removed from scoring")


def verify_runtime_conformance() -> None:
    namespace = runpy.run_path(str(TESTS), run_name="selected_work_conformance")
    test = namespace["test_pathway_next_scores_only_selected_active_work"]
    test_globals = test.__globals__
    with tempfile.TemporaryDirectory(prefix="selected-work-conformance-") as test_root:
        test_globals["ROOT"] = Path(test_root)
        passes_before = test_globals["_passes"]
        failures_before = len(test_globals["_failures"])
        test()
        new_failures = test_globals["_failures"][failures_before:]
        executed = test_globals["_passes"] - passes_before + len(new_failures)
    require(executed == EXPECTED_CONFORMANCE_ASSERTIONS,
            f"expected {EXPECTED_CONFORMANCE_ASSERTIONS} conformance assertions, executed {executed}")
    require(not new_failures, "; ".join(new_failures))


def main() -> int:
    verify_boundary_shape()
    verify_runtime_conformance()
    print("PASS deterministic selected-work pathway-next scoring conformance")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, OSError, StopIteration, SyntaxError) as exc:
        print(f"FAIL selected-work pathway-next scoring conformance: {exc}", file=sys.stderr)
        raise SystemExit(1)
