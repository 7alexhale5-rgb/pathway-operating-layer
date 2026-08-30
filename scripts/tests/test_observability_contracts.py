"""Phase 0 characterization harness for the per-project observability contracts work.

Pins the CURRENT behavior of validate_observability_runtime_receipt and
_validate_observability_json_artifact before the tradebot enums are extracted
to contract files. Gate G1: after extraction, every scenario here must produce
an IDENTICAL error list.

Fixtures are FROZEN LITERALS by design (security constraint 1, threat model
2026-08-30): nothing here reads the engine's OBSERVABILITY_* constants, so a
bad extraction cannot self-validate through fixtures that adapt to it.

Usage:
    python3 test_observability_contracts.py            # assert against goldens
    python3 test_observability_contracts.py --record   # (re)write the goldens

Spec: .planning/2026-08-30-per-project-observability-contracts.md, Phase 0.
Placed in scripts/tests/ per this repo's layout rule (the spec's shorthand
"tests/" path resolves here).
"""

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE_PATH = HERE.parent / "operating-layer.py"
GOLDENS_PATH = HERE / "goldens" / "observability_contracts_goldens.json"

# ---- frozen tradebot schema literals (snapshot 2026-08-30, HEAD 4f96f5f) ----

FROZEN_METRIC_NAMES = [
    "tradebot_component_heartbeat_age_seconds",
    "tradebot_drawdown_ratio",
    "tradebot_market_data_age_seconds",
    "tradebot_order_ack_latency_seconds",
    "tradebot_policy_violations_total",
    "tradebot_reconciliation_mismatches_total",
    "tradebot_risk_decisions_total",
]
FROZEN_METRIC_SAMPLES = [
    {
        "name": "tradebot_component_heartbeat_age_seconds",
        "value": 1,
        "labels": {"component": "AUDIT_LEDGER"},
    },
    {
        "name": "tradebot_drawdown_ratio",
        "value": 0.1,
        "labels": {"mode": "OBSERVE_ONLY"},
    },
    {
        "name": "tradebot_market_data_age_seconds",
        "value": 3,
        "labels": {"asset": "BTC-USD", "source": "SOURCE_UNSELECTED"},
    },
    {
        "name": "tradebot_order_ack_latency_seconds",
        "value": 4,
        "labels": {"venue": "VENUE_UNSELECTED"},
    },
    {
        "name": "tradebot_policy_violations_total",
        "value": 5,
        "labels": {"type": "ARTIFACT"},
    },
    {
        "name": "tradebot_reconciliation_mismatches_total",
        "value": 6,
        "labels": {"asset": "BTC-USD", "class": "BALANCE"},
    },
    {
        "name": "tradebot_risk_decisions_total",
        "value": 7,
        "labels": {"decision": "ABSTAIN", "reason": "AMBIGUOUS_SUBMIT"},
    },
]
FROZEN_CORRELATION_FIELDS = [
    "account_snapshot_seq",
    "asset",
    "client_order_id",
    "cycle_id",
    "decision_id",
    "data_snapshot_hash",
    "event_id",
    "intent_id",
    "manifest_hash",
    "market_event_ts",
    "mode",
    "observed_at",
    "occurred_at",
    "payload_hash",
    "previous_digest",
    "producer_id",
    "producer_key_id",
    "reason_code",
    "risk_decision",
    "risk_policy_hash",
    "sequence",
    "strategy_hash",
    "trace_id",
]
FROZEN_HASH_FIELDS = [
    "previous_digest",
    "payload_hash",
    "manifest_hash",
    "strategy_hash",
    "risk_policy_hash",
    "data_snapshot_hash",
]
FROZEN_QUESTION_ANSWERS = {
    "CURRENT_AUTHORIZED_STAGE_AND_MODE": "AUTHORITY_CONFIRMED_NO_RUNTIME",
    "DECISION_CYCLE_INTENT_AND_CLIENT_ORDER_IDENTIFIERS": "CORRELATION_IDENTIFIERS_RECONSTRUCTED",
    "STRATEGY_DATA_POLICY_AND_MANIFEST_HASHES": "AUTHORITATIVE_HASHES_RECONSTRUCTED",
    "LAST_TRUSTED_MARKET_AND_PRIVATE_FEED_TIMESTAMPS": "TRUSTED_TIMESTAMPS_RECONSTRUCTED",
    "ORDER_UNCERTAINTY_AND_LAST_VENUE_EVIDENCE": "VENUE_ACKNOWLEDGEMENT_REMAINS_UNCERTAIN",
    "RESERVATION_EXPOSURE_AND_LEDGER_MISMATCH_STATE": "WORST_CASE_RESERVATION_RETAINED",
    "WHY_HALT_ENTRIES_LATCHED": "HALT_LATCH_CONFIRMED",
    "WHY_RETRY_FLATTEN_AND_HALT_RELEASE_ARE_PROHIBITED": "PROHIBITED_ACTIONS_CONFIRMED",
    "EXACT_RECONCILIATION_EVIDENCE_STILL_MISSING": "MISSING_RECONCILIATION_EVIDENCE_IDENTIFIED",
    "HUMAN_DISPOSITION_REQUIRED_NEXT": "HUMAN_RECONCILIATION_REQUIRED",
}
FROZEN_QUESTION_EVIDENCE = {
    "CURRENT_AUTHORIZED_STAGE_AND_MODE": ["log_artifact"],
    "DECISION_CYCLE_INTENT_AND_CLIENT_ORDER_IDENTIFIERS": ["log_artifact"],
    "STRATEGY_DATA_POLICY_AND_MANIFEST_HASHES": ["log_artifact"],
    "LAST_TRUSTED_MARKET_AND_PRIVATE_FEED_TIMESTAMPS": [
        "log_artifact",
        "metric_artifact",
    ],
    "ORDER_UNCERTAINTY_AND_LAST_VENUE_EVIDENCE": ["log_artifact", "trace_artifact"],
    "RESERVATION_EXPOSURE_AND_LEDGER_MISMATCH_STATE": [
        "log_artifact",
        "metric_artifact",
    ],
    "WHY_HALT_ENTRIES_LATCHED": ["alert_artifact", "log_artifact"],
    "WHY_RETRY_FLATTEN_AND_HALT_RELEASE_ARE_PROHIBITED": ["alert_artifact"],
    "EXACT_RECONCILIATION_EVIDENCE_STILL_MISSING": ["log_artifact", "metric_artifact"],
    "HUMAN_DISPOSITION_REQUIRED_NEXT": ["alert_artifact"],
}
FROZEN_DRILL_FACTS = {
    "CURRENT_AUTHORIZED_STAGE_AND_MODE": {
        "authorized_stage": "NONE",
        "mode": "SIMULATE_ONLY",
    },
    "DECISION_CYCLE_INTENT_AND_CLIENT_ORDER_IDENTIFIERS": {
        "decision_id": "fixture-decision_id",
        "cycle_id": "fixture-cycle_id",
        "intent_id": "fixture-intent_id",
        "client_order_id": "fixture-client_order_id",
    },
    "STRATEGY_DATA_POLICY_AND_MANIFEST_HASHES": {
        "strategy_hash": "c" * 64,
        "data_snapshot_hash": "c" * 64,
        "risk_policy_hash": "c" * 64,
        "manifest_hash": "c" * 64,
    },
    "ORDER_UNCERTAINTY_AND_LAST_VENUE_EVIDENCE": {
        "order_uncertainty": "ACKNOWLEDGEMENT_UNCERTAIN",
        "last_venue_evidence": "NO_TERMINAL_VENUE_EVIDENCE",
    },
    "RESERVATION_EXPOSURE_AND_LEDGER_MISMATCH_STATE": {
        "reservation_state": "WORST_CASE_RESERVATION_RETAINED",
        "exposure_state": "OPEN_SYNTHETIC_BTC_EXPOSURE",
        "ledger_mismatch_state": "LEDGER_VENUE_MISMATCH_UNRESOLVED",
    },
    "WHY_HALT_ENTRIES_LATCHED": {
        "halt_reason": "STALE_MARKET_DATA_AND_UNCERTAIN_VENUE_ACK",
        "halt_latched": True,
    },
    "WHY_RETRY_FLATTEN_AND_HALT_RELEASE_ARE_PROHIBITED": {
        "retry_prohibited": True,
        "flatten_prohibited": True,
        "halt_release_prohibited": True,
    },
    "EXACT_RECONCILIATION_EVIDENCE_STILL_MISSING": {
        "missing_reconciliation_evidence": ["AUTHORITATIVE_VENUE_ORDER_STATE"],
    },
    "HUMAN_DISPOSITION_REQUIRED_NEXT": {
        "human_disposition": "RETAIN_HALT_AND_RECONCILE",
        "next_action": "RECONCILE_BY_CLIENT_ORDER_ID",
    },
}

SCENARIOS = (
    "valid",
    "wrong_metric_set_receipt",
    "wrong_metric_set_artifact",
    "wrong_event_artifact",
    "missing_artifact",
)


def load_engine():
    spec = importlib.util.spec_from_file_location(
        "opl_engine_characterization", ENGINE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_bytes(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_fixture(base):
    """Build the frozen-literal tradebot receipt + companion artifacts in base."""
    now = datetime.now(timezone.utc)
    observed_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_at = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    runtime_digest = "d" * 64
    environment_id = "characterization-secretless-runtime"
    common = {
        "schema_version": 1,
        "environment_id": environment_id,
        "runtime_digest": runtime_digest,
        "observed_at": observed_at,
    }
    log_record = {field: f"fixture-{field}" for field in FROZEN_CORRELATION_FIELDS}
    log_record.update(
        {
            "event_name": "tradebot.halt.latched",
            "sequence": 1,
            "account_snapshot_seq": 1,
            "trace_id": "a" * 32,
            "asset": "BTC-USD",
            "mode": "SIMULATE_ONLY",
            "risk_decision": "DENY",
            "reason_code": "STALE_DATA",
            "occurred_at": observed_at,
            "market_event_ts": observed_at,
            "observed_at": observed_at,
            **{field: "c" * 64 for field in FROZEN_HASH_FIELDS},
        }
    )
    drill_facts = dict(FROZEN_DRILL_FACTS)
    drill_facts["LAST_TRUSTED_MARKET_AND_PRIVATE_FEED_TIMESTAMPS"] = {
        "market_timestamp": observed_at,
        "private_feed_timestamp": observed_at,
    }
    json_artifacts = {
        "metric_artifact": {
            **common,
            "artifact_type": "metric_evidence",
            "metric_names": list(FROZEN_METRIC_NAMES),
            "samples": [dict(sample) for sample in FROZEN_METRIC_SAMPLES],
        },
        "log_artifact": {
            **common,
            "artifact_type": "structured_log_evidence",
            "correlation_fields": sorted(FROZEN_CORRELATION_FIELDS),
            "records": [log_record],
        },
        "trace_artifact": {
            **common,
            "artifact_type": "trace_evidence",
            "context_validated": True,
            "spans": [
                {"trace_id": "a" * 32, "span_id": "b" * 16, "name": "halt.activate"}
            ],
        },
        "alert_artifact": {
            **common,
            "artifact_type": "alert_execution_evidence",
            "alerts_wired": True,
            "executions": [
                {
                    "alert_id": "stale-feed",
                    "condition": "market data absent",
                    "status": "FIRED",
                    "safe_action": "HALT_ENTRIES_RECONCILE_ONLY",
                }
            ],
        },
        "runbook_drill_artifact": {
            **common,
            "artifact_type": "runbook_drill_evidence",
            "runbook_version": "3am-v1",
            "drill_executed": True,
            "answered_questions": [
                {
                    "question_id": question_id,
                    "answer": FROZEN_QUESTION_ANSWERS[question_id],
                    "facts": drill_facts[question_id],
                    "evidence_refs": list(FROZEN_QUESTION_EVIDENCE[question_id]),
                }
                for question_id in sorted(FROZEN_QUESTION_ANSWERS)
            ],
            "prohibited_actions_taken": [],
            "operator_disposition": "RETAIN_HALT_AND_RECONCILE",
            "recovery_evidence": [],
        },
        "canary_artifact": {
            **common,
            "artifact_type": "anti_gaming_canary_evidence",
            "canary_failed": True,
            "results": {
                "disabled_alert": "FAILED_AS_EXPECTED",
                "missing_signal": "FAILED_AS_EXPECTED",
            },
        },
    }
    artifacts = {}
    for field, payload in json_artifacts.items():
        path = base / f"characterization-{field}.json"
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        artifacts[field] = path
    verifier = base / "characterization-verifier.py"
    verifier.write_text(
        "import hashlib\n"
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        "receipt_path = Path(sys.argv[1])\n"
        "payload = json.loads(receipt_path.read_text(encoding='utf-8'))\n"
        "receipt = payload['observability_receipt']\n"
        "base = receipt_path.resolve().parent\n"
        "for field, expected in receipt['artifact_sha256'].items():\n"
        "    artifact = base / receipt[field]\n"
        "    if artifact.is_symlink() or not artifact.is_file():\n"
        "        sys.exit(8)\n"
        "    if hashlib.sha256(artifact.read_bytes()).hexdigest() != expected:\n"
        "        sys.exit(9)\n"
        "print('OBSERVABILITY_DECISION=CREDIT')\n",
        encoding="utf-8",
    )
    artifacts["verifier_artifact"] = verifier
    runbook = json_artifacts["runbook_drill_artifact"]
    runbook["recovery_evidence"] = [
        {
            "artifact_field": field,
            "sha256": sha256_bytes(artifacts[field]),
        }
        for field in ("metric_artifact", "log_artifact", "alert_artifact")
    ]
    artifacts["runbook_drill_artifact"].write_text(
        json.dumps(runbook) + "\n", encoding="utf-8"
    )
    receipt = {
        "schema_version": 1,
        "receipt_type": "runtime_observability",
        "pathway_result": "PASS",
        "claim_scope": "runtime",
        "work_id": "W-characterization",
        "recommendation_id": "REC-characterization",
        "project": "characterization",
        "target_project": str(base),
        "runtime_digest": runtime_digest,
        "environment_id": environment_id,
        "environment_class": "test",
        "authorized_stage": "NONE",
        "current_verdict": "NO_PROMOTE",
        "runbook_version": "3am-v1",
        "issued_at": observed_at,
        "expires_at": expires_at,
        "verifier_source_sha256": sha256_bytes(verifier),
        "metric_names": list(FROZEN_METRIC_NAMES),
        "log_correlation_fields": sorted(FROZEN_CORRELATION_FIELDS),
        "runtime_present": True,
        "telemetry_present": True,
        "alerts_wired": True,
        "alert_executed": True,
        "incident_drills_run": True,
        "trace_context_validated": True,
        "operator_disposition_recorded": True,
        "recovery_evidence_recorded": True,
        "anti_gaming_canary_failed": True,
        "credits_pathway": True,
        **{field: path.name for field, path in artifacts.items()},
        "artifact_sha256": {
            field: sha256_bytes(path) for field, path in artifacts.items()
        },
    }
    return receipt, artifacts


def run_scenarios(opl, base):
    results = {}

    receipt, artifacts = build_fixture(base)
    results["valid"] = opl.validate_observability_runtime_receipt(receipt, base)

    wrong_receipt = dict(receipt)
    wrong_receipt["metric_names"] = [
        name
        for name in FROZEN_METRIC_NAMES
        if name != "tradebot_component_heartbeat_age_seconds"
    ]
    results["wrong_metric_set_receipt"] = opl.validate_observability_runtime_receipt(
        wrong_receipt, base
    )

    metric_payload = json.loads(
        artifacts["metric_artifact"].read_text(encoding="utf-8")
    )
    metric_payload["metric_names"] = wrong_receipt["metric_names"]
    metric_payload["samples"] = [
        sample
        for sample in metric_payload["samples"]
        if sample["name"] != "tradebot_component_heartbeat_age_seconds"
    ]
    wrong_metric_path = base / "characterization-wrong-metric.json"
    wrong_metric_path.write_text(json.dumps(metric_payload) + "\n", encoding="utf-8")
    results["wrong_metric_set_artifact"] = opl._validate_observability_json_artifact(
        "metric_artifact", wrong_metric_path, receipt
    )

    log_payload = json.loads(artifacts["log_artifact"].read_text(encoding="utf-8"))
    log_payload["records"][0]["event_name"] = "tradebot.unknown.event"
    wrong_event_path = base / "characterization-wrong-event.json"
    wrong_event_path.write_text(json.dumps(log_payload) + "\n", encoding="utf-8")
    results["wrong_event_artifact"] = opl._validate_observability_json_artifact(
        "log_artifact", wrong_event_path, receipt
    )

    artifacts["metric_artifact"].unlink()
    results["missing_artifact"] = opl.validate_observability_runtime_receipt(
        receipt, base
    )

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", action="store_true", help="(re)write the goldens")
    parser.add_argument(
        "proof_receipt",
        nargs="?",
        help="optional pathway-proof receipt (NDJSON) to cross-check against this run",
    )
    args = parser.parse_args()

    opl = load_engine()
    with tempfile.TemporaryDirectory() as tmp:
        results = run_scenarios(opl, Path(tmp))

    if sorted(results) != sorted(SCENARIOS):
        print(f"FAIL: scenario set drifted: {sorted(results)}")
        sys.exit(3)
    if results["valid"] != []:
        print("FAIL: the frozen valid fixture no longer validates cleanly:")
        for error in results["valid"]:
            print(f"  - {error}")
        sys.exit(3)
    for name in SCENARIOS[1:]:
        if results[name] == []:
            print(f"FAIL: scenario {name} unexpectedly produced no errors")
            sys.exit(3)

    if args.record:
        GOLDENS_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDENS_PATH.write_text(
            json.dumps(results, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"recorded goldens for {len(results)} scenarios -> {GOLDENS_PATH}")
        return

    goldens = json.loads(GOLDENS_PATH.read_text(encoding="utf-8"))
    mismatches = 0
    for name in SCENARIOS:
        if results[name] != goldens.get(name):
            mismatches += 1
            print(f"FAIL: {name} error list drifted from golden")
            print(f"  golden: {goldens.get(name)}")
            print(f"  actual: {results[name]}")
    if mismatches:
        sys.exit(3)

    if args.proof_receipt:
        line = (
            Path(args.proof_receipt).read_text(encoding="utf-8").strip().splitlines()[0]
        )
        proof = json.loads(line)
        if proof["gate"] != "characterization-gate":
            print("FAIL: proof receipt gate must be characterization-gate")
            sys.exit(3)
        if proof["scenarios"] != len(SCENARIOS):
            print("FAIL: proof receipt scenario count disagrees with this run")
            sys.exit(3)
        if proof["valid_fixture_errors"] != len(results["valid"]):
            print(
                "FAIL: proof receipt valid-fixture error count disagrees with this run"
            )
            sys.exit(3)

    print(
        f"PASS: {len(SCENARIOS)}/{len(SCENARIOS)} characterization scenarios match goldens"
    )


if __name__ == "__main__":
    main()
