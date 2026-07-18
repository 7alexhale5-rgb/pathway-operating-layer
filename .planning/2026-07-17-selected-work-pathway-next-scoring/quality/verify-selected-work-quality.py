#!/usr/bin/env python3
"""Falsifiable regression verification for selected-work pathway-next scoring."""

from __future__ import annotations

import re
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TESTS = ROOT / "scripts/tests/operating_layer_test.py"
IMPLEMENTATION_VERIFIER = (
    ROOT
    / ".planning/2026-07-17-selected-work-pathway-next-scoring/implementation/verify-selected-work-scoring.py"
)
EXPECTED_MUTATION_ASSERTIONS = 3
EXPECTED_FULL_SUITE_CHECKS = 593


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_checked(command: list[str], label: str) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = completed.stdout + completed.stderr
    require(completed.returncode == 0, f"{label} failed:\n{output.strip()}")
    return output


def verify_aggregate_mutant_is_killed() -> None:
    namespace = runpy.run_path(str(TESTS), run_name="selected_work_quality_gate")
    test = namespace["test_selected_work_scoring_regression_kills_aggregate_mutant"]
    test_globals = test.__globals__
    with tempfile.TemporaryDirectory(prefix="selected-work-quality-focused-") as test_root:
        test_globals["ROOT"] = Path(test_root)
        passes_before = test_globals["_passes"]
        failures_before = len(test_globals["_failures"])
        test()
        failures = test_globals["_failures"][failures_before:]
        executed = test_globals["_passes"] - passes_before + len(failures)
    require(executed == EXPECTED_MUTATION_ASSERTIONS,
            f"expected {EXPECTED_MUTATION_ASSERTIONS} mutation-gate assertions, executed {executed}")
    require(not failures, "; ".join(failures))


def main() -> int:
    conformance = run_checked(
        [sys.executable, str(IMPLEMENTATION_VERIFIER)],
        "selected-work conformance verifier",
    )
    require("PASS deterministic selected-work pathway-next scoring conformance" in conformance,
            "focused conformance verifier did not emit its passing receipt")
    verify_aggregate_mutant_is_killed()

    suite = run_checked([sys.executable, str(TESTS)], "complete standard-library suite")
    match = re.search(r"(\d+)/(\d+) checks passed", suite)
    require(
        match is not None
        and int(match.group(1)) == EXPECTED_FULL_SUITE_CHECKS
        and int(match.group(2)) == EXPECTED_FULL_SUITE_CHECKS,
        f"complete suite did not emit the pinned {EXPECTED_FULL_SUITE_CHECKS}-check receipt",
    )

    print(
        "PASS selected-work regression verification: "
        f"32-case conformance, aggregate mutant killed, {match.group(1)}/{match.group(2)} full-suite checks passed"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, OSError, re.error) as exc:
        print(f"FAIL selected-work regression verification: {exc}", file=sys.stderr)
        raise SystemExit(1)
