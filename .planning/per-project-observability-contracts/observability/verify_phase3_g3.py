#!/usr/bin/env python3
"""Run the focused, non-ledger Phase 3 G3 Agents observability proof."""

import argparse
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
ENGINE = REPO / "scripts" / "operating-layer.py"
EVIDENCE = Path(__file__).resolve().parent / "OBSERVABILITY.md"
RECEIPT = EVIDENCE.with_suffix(".json")
CONTRACT = REPO / "contracts" / "observability" / "agents.json"
AGENTS = Path("/Users/alexhale/Projects/agents")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def load_engine():
    spec = importlib.util.spec_from_file_location("pathway_phase3_g3", ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git_status(path):
    return subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def main():
    engine = load_engine()
    envelope = json.loads(RECEIPT.read_text(encoding="utf-8"))
    receipt = envelope["observability_receipt"]
    expected = {
        "work_id": receipt["work_id"],
        "recommendation_id": receipt["recommendation_id"],
        "project": "agents",
        "target_project": str(AGENTS.resolve()),
    }
    contract_state = engine.resolve_observability_contract(AGENTS)
    require(not contract_state["errors"] and contract_state["key"] == "agents",
            "Agents contract did not resolve cleanly")

    loaded = engine.observability_receipt_from_evidence(
        EVIDENCE, expected, contract_state=contract_state)
    require(not loaded["errors"] and loaded["credit_scope"] == "runtime",
            f"valid G3 receipt was refused: {loaded['errors']}")

    violating = copy.deepcopy(receipt)
    violating["metric_names"][0] = "undeclared_specialist_metric"
    violation_errors = engine.validate_observability_runtime_receipt(
        violating, RECEIPT.parent, expected, contract_state=contract_state)
    require(any("exact canonical metric_names" in error for error in violation_errors),
            "a receipt violating the Agents metric contract was not refused")

    runbook = json.loads(
        (RECEIPT.parent / receipt["runbook_drill_artifact"]).read_text(encoding="utf-8"))
    log = json.loads(
        (RECEIPT.parent / receipt["log_artifact"]).read_text(encoding="utf-8"))
    trace = json.loads(
        (RECEIPT.parent / receipt["trace_artifact"]).read_text(encoding="utf-8"))
    alert = json.loads(
        (RECEIPT.parent / receipt["alert_artifact"]).read_text(encoding="utf-8"))
    require(not engine._validate_observability_drill_correlations(
        runbook, log, trace, alert, receipt, contract_state),
        "contract-driven Agents drill did not correlate")
    tampered_log = copy.deepcopy(log)
    tampered_log["records"][0]["failure_mode"] = "TWO_FAILURES_ONLY"
    require(engine._validate_observability_drill_correlations(
        runbook, tampered_log, trace, alert, receipt, contract_state),
        "a log violating the contract-declared drill incident was not refused")

    before_agents = git_status(AGENTS)
    args = argparse.Namespace(
        evidence=str(EVIDENCE),
        work_id=receipt["work_id"],
        pathway="observability",
        gate="phase3-g3",
        kind="verify",
        result="pass",
        stale_after_days=14,
        verified_by="",
        recommendation_id=receipt["recommendation_id"],
        verify_cmd=f"{sys.executable} {RECEIPT.parent / receipt['verifier_artifact']} {RECEIPT}",
        reviewer="",
        proof_type="artifact",
        canary_target=None,
        project=str(AGENTS),
    )
    proof, warning = engine.build_proof_record(
        args,
        work_item={
            "work_id": receipt["work_id"],
            "project": str(AGENTS),
            "project_name": "agents",
        },
    )
    after_agents = git_status(AGENTS)
    require(after_agents == before_agents, "focused G3 proof changed the Agents checkout")
    require(warning is None, f"focused G3 proof produced a warning: {warning}")
    require(engine.proof_is_verified(proof), "focused G3 proof_is_verified is false")
    require(proof.get("observability_credit_scope") == "runtime",
            "focused G3 proof did not receive runtime scope")
    require(proof.get("canary_mutant_failed") is True,
            "focused G3 seven-artifact mutation canary did not fail as expected")
    require(proof.get("observability_contract_key") == "agents",
            "focused G3 proof did not bind the Agents contract")
    require(not proof.get("observability_receipt_errors"),
            f"focused G3 proof has receipt errors: {proof.get('observability_receipt_errors')}")
    print(
        "PASS: Phase 3 G3 focused Agents receipt verified; "
        "scope=runtime proof_is_verified=true canary=7/7 violating_receipt=refused "
        "agents_checkout=unchanged ledger_credit=not_written"
    )


if __name__ == "__main__":
    main()
