#!/usr/bin/env python3
"""Verify selected-work scoring data contract, fixtures, source weights, and live lineage."""

from __future__ import annotations

import ast
import json
import runpy
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
DATA = ROOT / ".planning/2026-07-17-selected-work-pathway-next-scoring/data"
CONTRACT_PATH = DATA / "SELECTED_WORK_SCORING_CONTRACT.json"
FIXTURE_PATH = DATA / "SELECTED_WORK_SCORING_FIXTURES.json"
LEDGER_FIXTURE_PATH = DATA / "SELECTED_WORK_SCORING_LEDGER_FIXTURE.json"
REPORT_PATH = DATA / "DATA_CONTRACT.md"
SOURCE_PATH = ROOT / "scripts/operating-layer.py"
INTEL = Path("/Users/alexhale/Projects/memory-vault/operator-intelligence")

SELECTED_KOHO = "W-20260717-koho-complete-consultops-inte-2a7d82"
OLDER_KOHO = {
    "W-20260702-koho-seed-the-sdr-rail-prune--6e4c48": 9,
    "W-20260630-koho-fork-josh-s-template-rev-8b69d2": 8,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_ndjson(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def stale_count(work_id: str, measurements: list[dict]) -> int:
    now = datetime.now(timezone.utc)
    return sum(
        1 for item in measurements
        if item.get("work_id") == work_id and item.get("timestamp")
        and (now - parse_time(item["timestamp"])).days > int(item.get("stale_after_days") or 7)
    )


def verify_contract(contract: dict) -> None:
    require(contract["contract_id"] == "selected-work-pathway-next-scoring-v1", "wrong contract id")
    require(contract["selector"] == {
        "owner": "compute_pathway_next",
        "policy": "most-recently-updated-active-work",
        "selected_cardinality": "zero-or-one",
        "explicit_work_id_in_scope": False,
    }, "selector contract drift")
    selected = contract["selected_outcome"]
    require(selected["input_name"] == "active_summary" and selected["cardinality"] == "zero-or-one",
            "selected summary must be singular and optional")
    fields = selected["fields"]
    require(fields["open_controls"]["weight_each_target"] == 50, "control weight drift")
    require(fields["stale_measurements"]["weight_each"] == 5, "stale weight drift")
    require(fields["missing_evidence"]["weight_each"] == 4, "missing-evidence weight drift")
    require(all(value["default"] == [] for value in fields.values()), "selected defaults must be empty lists")
    require(contract["no_active_work"] == {
        "active_summary": None,
        "has_active_work": False,
        "work_id": None,
        "tracked_foundation_weight": 0,
        "untracked_foundation_nudge": 8,
        "next_command": "work-start",
    }, "no-active contract drift")
    require(contract["project_scope"]["scoped_findings"]["behavior"] == "preserve",
            "project findings must remain cross-outcome")
    require(contract["portfolio_scope"]["behavior"] == "continue-aggregating-all-relevant-active-work",
            "portfolio aggregation must remain independent")


def verify_fixture(fixture: dict, contract: dict) -> None:
    selected = fixture["selected"]
    older = fixture["non_selected"]
    expected = fixture["expected"]
    ordered = [selected["work_item"], *(item["work_item"] for item in older)]
    ordered.sort(key=lambda item: item["updated_at"], reverse=True)
    require(ordered[0]["work_id"] == expected["selected_work_id"] == "W-selected",
            "fixture does not deterministically select W-selected")

    selected_summary = selected["summary"]
    older_stale = sum(len(item["summary"]["stale_measurements"]) for item in older)
    older_missing = sum(len(item["summary"]["missing_evidence"]) for item in older)
    require(older_stale == expected["non_selected_stale_count"] == 17, "older stale fixture is not 17")
    require(older_missing == expected["non_selected_missing_evidence_count"] == 2,
            "older missing-evidence fixture is not 2")
    require(len(selected_summary["stale_measurements"]) == expected["selected_base_stale_count"] == 0,
            "selected base stale count must be zero")
    require(len(selected_summary["missing_evidence"]) == expected["selected_base_missing_evidence_count"] == 0,
            "selected base missing-evidence count must be zero")

    mutation = fixture["selected_mutation"]
    weights = contract["selected_outcome"]["fields"]
    require(len(mutation["stale_measurements"]) * weights["stale_measurements"]["weight_each"]
            == expected["selected_stale_score_delta"] == 10, "selected stale delta drift")
    require(len(mutation["missing_evidence"]) * weights["missing_evidence"]["weight_each"]
            == expected["selected_missing_evidence_score_delta"] == 8, "selected missing delta drift")
    require(weights["open_controls"]["weight_each_target"]
            == expected["selected_control_score_delta_each_target"] == 50, "selected control delta drift")
    require(expected["older_control_score_delta"] == 0, "older control must contribute zero")
    require(expected["project_critical_finding_score_delta"] == 40, "critical project finding weight drift")
    require(expected["metamorphic_non_selected_change_delta"] == 0, "non-selected mutation must be invariant")
    require(fixture["project_findings"][0]["pathway"] == "security", "project finding route drift")
    require(set(selected_summary["open_controls"][0]["target_pathways"]) == {"security", "release"},
            "selected control target drift")
    require(older[0]["summary"]["open_controls"][0]["target_pathways"] == ["data"],
            "older control target drift")

    coverage = fixture["coverage_isolation"]
    require(coverage["selected_summary"]["pathway_coverage"] == {"seen": [], "proved": []},
            "coverage isolation selected summary must be empty")
    require(coverage["older_summary"]["pathway_coverage"]["proved"] == ["govern", "research"],
            "coverage isolation older summary must prove foundations")
    require(coverage["expected_selected_foundations_seen"] == [],
            "older foundation coverage must not reach selected work")
    require(coverage["expected_research_foundation_weight"] == 100
            and coverage["expected_govern_foundation_weight"] == 80,
            "tracked selected foundation weights drift")

    controls = fixture["control_isolation"]
    require(controls["selected_without_control"] == [], "selected no-control baseline must be explicit")
    require(len(controls["selected_with_control"]) == 1, "selected control mutation must be explicit")
    require(controls["expected_selected_control_delta_each_target"] == 50
            and controls["expected_older_control_delta"] == 0,
            "control isolation deltas drift")

    no_active = fixture["no_active"]
    require(no_active == {
        "work_items": [],
        "active_summary": None,
        "work_id": None,
        "has_active_work": False,
        "untracked_foundation_nudge": 8,
        "next_command": "work-start",
    }, "no-active fixture drift")


def verify_ledger_fixture(fixture: dict) -> None:
    required_work_fields = {
        "work_id", "project", "project_name", "goal", "status", "updated_at", "tier",
        "outcome_profile", "risk_overlays", "itinerary",
    }
    require(len(fixture["work_items"]) == 3, "ledger fixture must contain three active work items")
    require(all(required_work_fields <= set(item) for item in fixture["work_items"]),
            "ledger work item is not directly writable")
    ordered = sorted(fixture["work_items"], key=lambda item: item["updated_at"], reverse=True)
    require(ordered[0]["work_id"] == fixture["expected"]["selected_work_id"] == "W-selected",
            "ledger fixture selection is not deterministic")

    run_fields = {"run_id", "work_id", "pathway", "status", "timestamp"}
    require(all(run_fields <= set(item) for item in fixture["pathway_runs"]),
            "ledger run record is not directly writable")
    measurement_fields = {
        "measurement_id", "run_id", "work_id", "pathway", "gate", "kind", "result",
        "timestamp", "evidence_id", "stale_after_days",
    }
    require(all(measurement_fields <= set(item) for item in fixture["pathway_measurements"]),
            "ledger measurement record is not directly writable")
    control_fields = {"control_id", "work_id", "risk", "source_pathway", "target_pathways", "status"}
    require(all(control_fields <= set(item) for item in fixture["controls"]),
            "ledger control record is not directly writable")

    selected_id = fixture["expected"]["selected_work_id"]
    selected_seen = sorted({item["pathway"] for item in fixture["pathway_runs"] if item["work_id"] == selected_id})
    older_seen = sorted({item["pathway"] for item in fixture["pathway_runs"] if item["work_id"] != selected_id})
    require(selected_seen == fixture["expected"]["selected_seen"] == [],
            "ledger selected coverage must remain empty")
    require(older_seen == sorted(fixture["expected"]["older_seen"]),
            "ledger older coverage drift")

    old_measurements = [item for item in fixture["pathway_measurements"] if item["work_id"] != selected_id]
    stale = [item for item in old_measurements if item.get("evidence_id") and item["timestamp"].startswith("2026-01-")]
    missing = [item for item in old_measurements if not item.get("evidence_id")]
    require(len(stale) == fixture["expected"]["older_stale_count"] == 17,
            "ledger older stale count drift")
    require(len(missing) == fixture["expected"]["older_missing_evidence_count"] == 2,
            "ledger older missing-evidence count drift")

    selected_controls = [item["control_id"] for item in fixture["controls"] if item["work_id"] == selected_id]
    older_controls = [item["control_id"] for item in fixture["controls"] if item["work_id"] != selected_id]
    require(selected_controls == fixture["expected"]["selected_control_ids"], "ledger selected control drift")
    require(older_controls == fixture["expected"]["ignored_older_control_ids"], "ledger older control drift")

    selected_cf = [item for item in fixture["pathway_carry_forward"] if item["work_id"] == selected_id]
    older_cf = [item for item in fixture["pathway_carry_forward"] if item["work_id"] != selected_id]
    runtime = runpy.run_path(str(SOURCE_PATH), run_name="selected_work_scoring_runtime")
    carry_forward_is_valid = runtime["carry_forward_is_valid"]
    require(all(carry_forward_is_valid(item) for item in fixture["pathway_carry_forward"]),
            "ledger carry-forward record is not runtime-valid")
    require(selected_cf[0]["carry_forward_id"] == fixture["expected"]["selected_carry_forward_id"],
            "ledger selected carry-forward drift")
    require(older_cf[0]["carry_forward_id"] == fixture["expected"]["ignored_older_carry_forward_id"],
            "ledger older carry-forward drift")

    no_active = fixture["no_active_project"]
    require(no_active["work_items"] == [] and no_active["expected"] == {
        "active_summary": None,
        "work_id": None,
        "has_active_work": False,
        "untracked_foundation_nudge": 8,
        "next_command_contains": "work-start",
    }, "ledger no-active case drift")
    require(fixture["mutations"]["remove_selected_control"]["expected_security_and_release_delta"] == -50,
            "ledger control removal mutation drift")
    require(fixture["mutations"]["move_two_stale_to_selected"]["expected_quality_delta"] == 10,
            "ledger selected stale mutation drift")
    require(fixture["mutations"]["move_two_missing_to_selected"]["expected_quality_delta"] == 8,
            "ledger selected missing mutation drift")


def verify_source_weights(contract: dict) -> None:
    source = SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    scorer = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "score_pathways")
    scorer_text = ast.get_source_segment(source, scorer) or ""
    fields = contract["selected_outcome"]["fields"]
    for fragment in (
        f'bump(t, {fields["open_controls"]["weight_each_target"]}',
        f'bump("quality", {fields["stale_measurements"]["weight_each"]} * stale_count',
        f'bump("quality", {fields["missing_evidence"]["weight_each"]} * missing_evidence_count',
    ):
        require(fragment in scorer_text, f"source weight no longer matches contract: {fragment}")
    require("UNTRACKED_FOUNDATION_NUDGE = 8" in source, "untracked foundation nudge drift")
    severity = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "PATHWAY_SEVERITY_WEIGHT" for target in node.targets)
    )
    severity_value = ast.literal_eval(severity.value)
    require(severity_value.get("critical") == 40, "critical project-finding weight drift")


def verify_live_lineage() -> None:
    items = load_ndjson(INTEL / "work-items.ndjson")
    measurements = load_ndjson(INTEL / "pathway-measurements.ndjson")
    controls = load_ndjson(INTEL / "controls.ndjson")
    active_koho = [
        item for item in items
        if item.get("status", "active") != "closed"
        and (item.get("project") == "/Users/alexhale/Projects/koho" or item.get("project_name") == "koho")
    ]
    active_koho.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    require(active_koho and active_koho[0]["work_id"] == SELECTED_KOHO, "live Koho selected work drift")
    require(stale_count(SELECTED_KOHO, measurements) == 0, "live Koho selected stale count drift")
    for work_id, count in OLDER_KOHO.items():
        require(stale_count(work_id, measurements) == count, f"live Koho older stale count drift: {work_id}")
    selected_open = [
        item for item in controls
        if item.get("work_id") == SELECTED_KOHO and item.get("status", "open") != "resolved"
    ]
    require(any(
        "Supabase PAT" in item.get("risk", "")
        and set(item.get("target_pathways") or []) == {"security", "release"}
        for item in selected_open
    ), "live selected Supabase control missing")
    non_selected_ids = {item["work_id"] for item in active_koho[1:]}
    require(not any(
        item.get("work_id") in non_selected_ids and item.get("status", "open") != "resolved"
        for item in controls
    ), "a non-selected active Koho outcome now has an open control requiring review")


def verify_report() -> None:
    text = REPORT_PATH.read_text(encoding="utf-8")
    for heading in (
        "## Boundary Decision",
        "## Machine-Readable Artifacts",
        "## Lineage",
        "## Field Contract",
        "## Deterministic Record Proof",
        "## Live Record Verification",
        "## Privacy And Compatibility",
        "## Verification",
        "## Summary",
        "## What Changed",
        "## More Relevant",
        "## Less Relevant",
        "## Next Pathway Must Use",
        "## Do Not Do Yet",
        "## Open Decisions",
        "## Active Risk Overlays",
    ):
        require(text.count(heading) == 1, f"missing or duplicate data heading: {heading}")
    for phrase in (
        "Lineage",
        "verification",
        "zero-or-one",
        "directly writable ledger fixture",
        "0 + 9 + 8 = 17",
        "Implementation must implement the singular `active_summary` scorer contract",
        "No schema, migration, ledger rewrite, control promotion, cross-client copy",
    ):
        require(phrase in text, f"data report missing contract phrase: {phrase}")


def main() -> int:
    contract = load_json(CONTRACT_PATH)
    fixture = load_json(FIXTURE_PATH)
    ledger_fixture = load_json(LEDGER_FIXTURE_PATH)
    verify_contract(contract)
    verify_fixture(fixture, contract)
    verify_ledger_fixture(ledger_fixture)
    verify_source_weights(contract)
    verify_live_lineage()
    verify_report()
    diff = subprocess.run(
        ["git", "diff", "--check", "--", str(CONTRACT_PATH), str(FIXTURE_PATH), str(LEDGER_FIXTURE_PATH), str(REPORT_PATH), str(Path(__file__))],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    require(diff.returncode == 0, diff.stdout + diff.stderr)
    print("PASS selected-work pathway-next data verifier")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, OSError, ValueError, StopIteration) as exc:
        print(f"FAIL selected-work pathway-next data verifier: {exc}", file=sys.stderr)
        raise SystemExit(1)
