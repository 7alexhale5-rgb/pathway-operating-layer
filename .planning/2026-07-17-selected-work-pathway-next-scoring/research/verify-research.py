#!/usr/bin/env python3
"""Verify the research dossier against source and live Pathway ledger evidence."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
RESEARCH = ROOT / ".planning/2026-07-17-selected-work-pathway-next-scoring/research"
DOSSIER = RESEARCH / "DOSSIER.md"
REPORT = RESEARCH / "VERIFICATION_REPORT.md"
SOURCE = ROOT / "scripts/operating-layer.py"
INTEL = Path("/Users/alexhale/Projects/memory-vault/operator-intelligence")

SELECTED_KOHO = "W-20260717-koho-complete-consultops-inte-2a7d82"
OLDER_KOHO = {
    "W-20260702-koho-seed-the-sdr-rail-prune--6e4c48": 9,
    "W-20260630-koho-fork-josh-s-template-rev-8b69d2": 8,
}
TARGET_WORK = "W-20260718-pathway-operating-layer-scope-pathway-next-scori-81ef31"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_ndjson(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def stale_count(work_id: str, measurements: list[dict]) -> int:
    now = datetime.now(timezone.utc)
    count = 0
    for item in measurements:
        if item.get("work_id") != work_id or not item.get("timestamp"):
            continue
        age_days = (now - parse_time(item["timestamp"])).days
        if age_days > int(item.get("stale_after_days") or 7):
            count += 1
    return count


def source_contract() -> None:
    source_text = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source_text)
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "score_pathways"
    ]
    require(len(calls) == 1, f"expected one score_pathways call, found {len(calls)}")

    compute = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "compute_pathway_next"
    )
    compute_text = ast.get_source_segment(source_text, compute) or ""
    scorer = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "score_pathways"
    )
    scorer_text = ast.get_source_segment(source_text, scorer) or ""

    require("work_summaries = [work_status_summary" in compute_text,
            "compute no longer builds all active work summaries; research seam changed")
    require("scoped_findings, work_summaries" in compute_text,
            "compute no longer passes all summaries to scoring; research seam changed")
    for phrase in (
        "for summary in work_summaries",
        "open_controls.extend",
        "stale_count +=",
        "missing_evidence_count +=",
        "for f in scoped_findings",
        "learned_pathway_closures",
    ):
        require(phrase in scorer_text, f"missing researched scorer behavior: {phrase}")
    require(source_text.count("score_pathways(") == 2,
            "expected one definition and one direct score_pathways call")


def live_ledger_contract() -> None:
    items = read_ndjson(INTEL / "work-items.ndjson")
    measurements = read_ndjson(INTEL / "pathway-measurements.ndjson")
    controls = read_ndjson(INTEL / "controls.ndjson")

    active_koho = [
        item for item in items
        if item.get("status", "active") != "closed"
        and (item.get("project") == "/Users/alexhale/Projects/koho" or item.get("project_name") == "koho")
    ]
    active_koho.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    require(active_koho and active_koho[0].get("work_id") == SELECTED_KOHO,
            "expected Koho selected work is no longer first by active-work ordering")
    require(stale_count(SELECTED_KOHO, measurements) == 0,
            "selected Koho work no longer has zero stale measurements")
    for work_id, expected in OLDER_KOHO.items():
        require(stale_count(work_id, measurements) == expected,
                f"older Koho stale count changed for {work_id}")

    selected_controls = [
        item for item in controls
        if item.get("work_id") == SELECTED_KOHO and item.get("status", "open") != "resolved"
    ]
    require(any(
        "Supabase PAT" in item.get("risk", "")
        and set(item.get("target_pathways") or []) == {"security", "release"}
        for item in selected_controls
    ), "selected Koho Supabase credential control is missing")

    active_target = [
        item for item in items
        if item.get("status", "active") != "closed"
        and (
            item.get("project") == "/Users/alexhale/Projects/pathway-operating-layer"
            or item.get("project_name") == "pathway-operating-layer"
        )
    ]
    require(len(active_target) == 1 and active_target[0].get("work_id") == TARGET_WORK,
            "target project no longer has exactly the governed active work item")
    target_ids = {item.get("work_id") for item in items if (
        item.get("project") == "/Users/alexhale/Projects/pathway-operating-layer"
        or item.get("project_name") == "pathway-operating-layer"
    )}
    target_open_controls = [
        item for item in controls
        if item.get("work_id") in target_ids and item.get("status", "open") != "resolved"
    ]
    require(not target_open_controls, "target project now has an open control requiring promotion review")

    item_by_id = {item.get("work_id"): item for item in items}
    globally_open = [item for item in controls if item.get("status", "open") != "resolved"]
    require(len(globally_open) == 3, f"expected three globally open controls, found {len(globally_open)}")
    for control in globally_open:
        owner = item_by_id.get(control.get("work_id"))
        require(owner is not None and owner.get("status", "active") != "closed",
                f"open control is not owned by active work: {control.get('control_id')}")
        candidates = [
            item for item in items
            if item.get("status", "active") != "closed"
            and (
                item.get("project") == owner.get("project")
                or item.get("project_name") == owner.get("project_name")
            )
        ]
        candidates.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        require(candidates and candidates[0].get("work_id") == owner.get("work_id"),
                f"open control belongs to non-selected work: {control.get('control_id')}")


def artifact_contract() -> None:
    dossier = DOSSIER.read_text(encoding="utf-8")
    report = REPORT.read_text(encoding="utf-8")
    for heading in (
        "## Question",
        "## Sources And Method",
        "## Current Failure Evidence",
        "## Scoring Boundary Map",
        "## Regression Design",
        "## Security And Control Findings",
        "## Summary",
        "## What Changed",
        "## More Relevant",
        "## Less Relevant",
        "## Next Pathway Must Use",
        "## Do Not Do Yet",
        "## Open Decisions",
        "## Active Risk Overlays",
    ):
        require(dossier.count(heading) == 1, f"missing or duplicate dossier heading: {heading}")
    for phrase in (
        "0 + 9 + 8 = 17",
        "score `76`",
        "singular `active_summary`",
        "older-missing-ignored",
        "selected-missing-counted",
        "metamorphic-isolation",
        "portfolio-next",
        "All three current open controls",
        "Blockers\n\nNone",
    ):
        require(phrase in dossier, f"missing planning-ready claim: {phrase}")
    require("`PASS`" in report and "## Sources" in report and "## Independent Review" in report,
            "verification report is incomplete")

    diff = subprocess.run(
        ["git", "diff", "--check", "--", str(DOSSIER), str(REPORT), str(Path(__file__))],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    require(diff.returncode == 0, diff.stdout + diff.stderr)


def main() -> int:
    source_contract()
    live_ledger_contract()
    artifact_contract()
    print("PASS selected-work pathway-next research verifier")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, ValueError, StopIteration) as exc:
        print(f"FAIL selected-work pathway-next research verifier: {exc}", file=sys.stderr)
        raise SystemExit(1)
