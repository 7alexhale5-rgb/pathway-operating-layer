#!/usr/bin/env python3
"""Gate-specific verification for selected-work pathway-next closeout."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "scripts/operating-layer.py"
FOCUSED = (
    ROOT
    / ".planning/2026-07-17-selected-work-pathway-next-scoring/implementation/verify-selected-work-scoring.py"
)
QUALITY = (
    ROOT
    / ".planning/2026-07-17-selected-work-pathway-next-scoring/quality/verify-selected-work-quality.py"
)
KOHO_ROOT = Path("/Users/alexhale/Projects/koho")
KOHO_WORK_ID = "W-20260630-koho-consultops-1.13-oliver-sdr-ux-faithful-i-ad8a56"
GATES = ("security", "field", "observability", "techdebt", "release")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_cli():
    spec = importlib.util.spec_from_file_location("pathway_closeout_cli", SOURCE)
    require(spec is not None and spec.loader is not None, "could not load operating-layer source")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compute(cli, work_id: str):
    args = cli.build_parser().parse_args([
        "pathway-next",
        "--project", str(KOHO_ROOT),
        "--work-id", work_id,
    ])
    return cli.compute_pathway_next(args, cli.Paths(args))


def run_checked(command: list[str], label: str) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    require(result.returncode == 0, f"{label} failed:\n{output.strip()}")
    return output


def verify_security(cli) -> None:
    require(
        cli.work_item_is_within_project(
            {"project": str(KOHO_ROOT / "consult-ops/app"), "project_name": "app"},
            KOHO_ROOT,
            "koho",
        ),
        "a nested checkout was rejected",
    )
    require(
        not cli.work_item_is_within_project(
            {"project": "/Users/alexhale/Projects/other/koho", "project_name": "koho"},
            KOHO_ROOT,
            "koho",
        ),
        "a same-name sibling escaped the project boundary",
    )
    invalid = compute(cli, "W-selected-work-closeout-does-not-exist")
    require(
        {row.get("id") for row in invalid.get("findings", [])}
        == {"pathway-next-work-id-not-active"}
        and "recommended" not in invalid,
        "unknown explicit work did not fail closed",
    )


def verify_field(cli) -> None:
    state = compute(cli, KOHO_WORK_ID)
    require(state.get("work_id") == KOHO_WORK_ID, "real Koho work identity was replaced")
    require(
        state.get("latest_carry_forward", {}).get("work_id") == KOHO_WORK_ID,
        "real Koho carry-forward came from another outcome",
    )
    require(
        str(state.get("karpathy_card", {}).get("goal", "")).startswith("Oliver SDR UX:"),
        "operator card did not retain the selected outcome goal",
    )


def verify_observability(cli) -> None:
    state = compute(cli, KOHO_WORK_ID)
    quality = next(row for row in state["ranked"] if row["pathway"] == "quality")
    require(
        any("9 stale measurement" in reason for reason in quality.get("reasons", [])),
        "selected stale-measurement count is absent from recommendation reasons",
    )
    require(
        state.get("itinerary_coverage", {}).get("covered") == 8
        and state.get("itinerary_coverage", {}).get("total") == 8,
        "selected itinerary coverage is not observable in the result",
    )


def verify_techdebt(cli) -> None:
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    scorer = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "score_pathways"
    )
    require(scorer.args.args[4].arg == "active_summary", "aggregate scorer contract returned")
    require(source.count("def work_item_is_within_project(") == 1, "project helper is duplicated")
    require("work_summaries" not in (ast.get_source_segment(source, scorer) or ""),
            "cross-outcome aggregation returned")
    run_checked(["git", "diff", "--check"], "diff hygiene")


def verify_release(_cli) -> None:
    focused = run_checked([sys.executable, str(FOCUSED)], "focused conformance")
    require("PASS deterministic selected-work" in focused, "focused receipt missing")
    quality = run_checked([sys.executable, str(QUALITY)], "quality gate")
    require("593/593 full-suite checks passed" in quality, "full-suite receipt missing")
    run_checked([sys.executable, str(SOURCE), "--help"], "CLI help smoke")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", choices=GATES, required=True)
    args = parser.parse_args()
    cli = load_cli()
    {
        "security": verify_security,
        "field": verify_field,
        "observability": verify_observability,
        "techdebt": verify_techdebt,
        "release": verify_release,
    }[args.gate](cli)
    print(f"PASS selected-work closeout gate: {args.gate}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, OSError, StopIteration, SyntaxError) as exc:
        print(f"FAIL selected-work closeout: {exc}", file=sys.stderr)
        raise SystemExit(1)
