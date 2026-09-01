#!/usr/bin/env python3
"""Verify the focused Agents specialist-fleet runtime receipt without repo writes."""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


AGENTS_ROOT = Path("/Users/alexhale/Projects/agents")
PERF = AGENTS_ROOT / "scripts" / "subagent-perf.py"
WATCH = AGENTS_ROOT / "scripts" / "subagent-perf-watch.sh"
LEDGER = AGENTS_ROOT / "_meta" / "subagent-performance.ndjson"
UPSTREAM_VERIFIER = AGENTS_ROOT / "scripts" / "verify_observability_watch.py"
HISTORICAL_RECEIPT = AGENTS_ROOT / ".planning" / "receipts" / "observability.ndjson"
HISTORICAL_ALERT = (
    AGENTS_ROOT
    / "_inbox"
    / "ops-lead"
    / "2026-08-30T021520Z-79130-subagent-perf-alert.md"
)
TRAP_TRANSCRIPT = (
    AGENTS_ROOT
    / "hermes"
    / "subagents"
    / "redactor"
    / "trap-run-2026-08-30T132555Z.md"
)
ARTIFACT_FIELDS = (
    "metric_artifact",
    "log_artifact",
    "trace_artifact",
    "alert_artifact",
    "runbook_drill_artifact",
    "canary_artifact",
    "verifier_artifact",
)
SOURCE_FILES = {
    "ledger": LEDGER,
    "perf": PERF,
    "watch": WATCH,
    "upstream_verifier": UPSTREAM_VERIFIER,
    "historical_receipt": HISTORICAL_RECEIPT,
    "historical_alert": HISTORICAL_ALERT,
    "trap_transcript": TRAP_TRANSCRIPT,
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message):
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(3)


def require(condition, message):
    if not condition:
        fail(message)


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"cannot read {path.name}: {exc}")
    require(isinstance(value, dict), f"{path.name} must be a JSON object")
    return value


def load_ledger():
    rows = []
    for number, line in enumerate(LEDGER.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except ValueError:
            fail(f"ledger line {number} is not JSON")
        require(
            isinstance(row, dict)
            and {"ts", "subagent", "eval", "result"}.issubset(row)
            and row["result"] in {"pass", "fail"},
            f"ledger line {number} violates the performance schema",
        )
        rows.append(row)
    return rows


def ledger_metrics(rows):
    ordered = sorted(rows, key=lambda row: row["ts"])
    by_specialist = {}
    for row in ordered:
        by_specialist.setdefault(row["subagent"], []).append(row)
    trailing = []
    for evaluations in by_specialist.values():
        streak = 0
        for row in reversed(evaluations):
            if row["result"] != "fail":
                break
            streak += 1
        trailing.append(streak)
    passes = sum(row["result"] == "pass" for row in rows)
    return len(rows), passes / len(rows), max(trailing, default=0)


def run_report(ledger=None):
    command = [sys.executable, str(PERF), "report"]
    if ledger is not None:
        command.extend(["--ledger", str(ledger)])
    return subprocess.run(
        command,
        cwd=str(AGENTS_ROOT),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def main():
    require(len(sys.argv) == 2, "usage: verify_agents_runtime_receipt.py RECEIPT.json")
    receipt_path = Path(sys.argv[1]).expanduser().resolve()
    envelope = read_json(receipt_path)
    receipt = envelope.get("observability_receipt")
    require(isinstance(receipt, dict), "receipt envelope is missing observability_receipt")
    base = receipt_path.parent

    declared = receipt.get("artifact_sha256")
    require(isinstance(declared, dict) and set(declared) == set(ARTIFACT_FIELDS),
            "receipt artifact map is incomplete")
    artifacts = {}
    for field in ARTIFACT_FIELDS:
        candidate = base / str(receipt.get(field) or "")
        require(
            candidate.parent == base and candidate.is_file() and not candidate.is_symlink(),
            f"{field} is not a regular companion artifact",
        )
        require(digest(candidate) == declared[field], f"{field} digest changed")
        artifacts[field] = candidate

    metric = read_json(artifacts["metric_artifact"])
    log = read_json(artifacts["log_artifact"])
    trace = read_json(artifacts["trace_artifact"])
    alert = read_json(artifacts["alert_artifact"])
    runbook = read_json(artifacts["runbook_drill_artifact"])
    canary = read_json(artifacts["canary_artifact"])

    source_digests = metric.get("source_sha256")
    require(isinstance(source_digests, dict) and set(source_digests) == set(SOURCE_FILES),
            "metric evidence does not bind the complete Agents source set")
    before = {name: digest(path) for name, path in SOURCE_FILES.items()}
    require(before == source_digests, "the read-only Agents source snapshot drifted")

    rows = load_ledger()
    total, pass_rate, fail_streak = ledger_metrics(rows)
    samples = {sample.get("name"): sample.get("value") for sample in metric.get("samples", [])}
    require(samples.get("specialist_evaluations_total") == total,
            "evaluation total does not match the live ledger")
    require(samples.get("specialist_pass_rate_ratio") == pass_rate,
            "pass rate does not match the live ledger")
    require(samples.get("specialist_fail_streak") == fail_streak,
            "fail streak does not match the live ledger")

    live = run_report()
    require(live.returncode == metric.get("live_report_rc") == 0,
            "live specialist report is not clean")
    require(hashlib.sha256(live.stdout.encode()).hexdigest() == metric.get("live_report_sha256"),
            "live specialist report output changed")

    with tempfile.TemporaryDirectory(prefix="pathway-agents-g3-") as temp_dir:
        isolated_root = Path(temp_dir)
        drill_ledger = isolated_root / "_meta" / "subagent-performance.ndjson"
        drill_ledger.parent.mkdir(parents=True)
        drill_ledger.write_text(LEDGER.read_text(encoding="utf-8"), encoding="utf-8")
        observed_at = str(log.get("observed_at") or "")
        with drill_ledger.open("a", encoding="utf-8") as handle:
            for index in range(3):
                handle.write(json.dumps({
                    "ts": observed_at,
                    "subagent": "pathway-g3-drill",
                    "eval": "regression",
                    "result": "fail",
                    "detail": f"fresh read-only G3 drill {index + 1}/3",
                }, separators=(",", ":")) + "\n")
        drill = run_report(drill_ledger)
        isolated_scripts = isolated_root / "scripts"
        isolated_scripts.mkdir()
        isolated_perf = isolated_scripts / PERF.name
        isolated_watch = isolated_scripts / WATCH.name
        shutil.copyfile(PERF, isolated_perf)
        shutil.copyfile(WATCH, isolated_watch)
        require(digest(isolated_perf) == before["perf"]
                and digest(isolated_watch) == before["watch"],
                "isolated alert path is not byte-identical to Agents")
        watch_execution = subprocess.run(
            ["bash", str(isolated_watch), "--ledger", str(drill_ledger)],
            cwd=isolated_root,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        isolated_alerts = list((isolated_root / "_inbox" / "ops-lead").glob(
            "*-subagent-perf-alert.md"
        ))
        isolated_alert_text = (
            isolated_alerts[0].read_text(encoding="utf-8")
            if len(isolated_alerts) == 1 else ""
        )
        require(drill.returncode == 3 and "pathway-g3-drill" in drill.stdout
                and "FIRE-REVIEW" in drill.stdout, "fresh fail-streak drill did not fire")
        require(hashlib.sha256(drill.stdout.encode()).hexdigest()
                == trace.get("drill_stdout_sha256"), "fresh drill transcript changed")
        require(watch_execution.returncode == 3
                and "subagent-perf-watch: ALERT rc=3" in watch_execution.stdout
                and len(isolated_alerts) == 1
                and "source: scripts/subagent-perf-watch.sh" in isolated_alert_text
                and "severity: FIRE-REVIEW fail-streak" in isolated_alert_text
                and "pathway-g3-drill" in isolated_alert_text,
                "byte-identical isolated watcher did not write the fired alert")

    execution = (alert.get("executions") or [{}])[0]
    require(alert.get("alerts_wired") is True and execution.get("status") == "FIRED",
            "alert execution evidence is not fired")
    watcher_execution = alert.get("watcher_execution") or {}
    require(watcher_execution == {
        "mode": "BYTE_IDENTICAL_TEMP_REPO",
        "exit_code": 3,
        "delivery_surface": "isolated temporary ops-lead inbox",
        "source_checkout_mutated": False,
    }, "alert evidence does not describe the isolated watcher execution")
    require("subagent-perf.py" in WATCH.read_text(encoding="utf-8")
            and "_inbox/ops-lead" in WATCH.read_text(encoding="utf-8"),
            "watch no longer routes the performance signal to the ops inbox")
    require("FIRE-REVIEW" in HISTORICAL_ALERT.read_text(encoding="utf-8"),
            "historical alert lost the fail-streak signal")
    require(runbook.get("drill_executed") is True
            and runbook.get("prohibited_actions_taken") == [],
            "runbook drill is incomplete or claims unsafe actions")
    require(canary.get("results") == {
        "disabled_alert": "FAILED_AS_EXPECTED",
        "missing_signal": "FAILED_AS_EXPECTED",
    }, "anti-gaming canary evidence is incomplete")

    after = {name: digest(path) for name, path in SOURCE_FILES.items()}
    require(after == before, "the verifier observed an Agents source mutation")

    receipt_sha256 = digest(receipt_path)
    markers = {
        "OBSERVABILITY_DECISION": "CREDIT",
        "OBSERVABILITY_GATE": "PASS",
        "PATHWAY_RESULT": "PASS",
        "RUNTIME_STATUS": "PRESENT",
        "TELEMETRY_STATUS": "PRESENT",
        "ALERT_STATUS": "WIRED",
        "RUNBOOK_STATUS": "DRILLED",
        "CANARY_STATUS": "FAILED_AS_EXPECTED",
        "AUTHORIZED_STAGE": receipt["authorized_stage"],
        "CURRENT_VERDICT": receipt["current_verdict"],
        "WORK_ID": receipt["work_id"],
        "RECOMMENDATION_ID": receipt["recommendation_id"],
        "ENVIRONMENT_ID": receipt["environment_id"],
        "OBSERVABILITY_RECEIPT_SHA256": receipt_sha256,
    }
    for key, value in markers.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
