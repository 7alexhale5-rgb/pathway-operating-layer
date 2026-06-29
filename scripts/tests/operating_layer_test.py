#!/usr/bin/env python3
"""
operating_layer_test.py - self-test suite for operating-layer.py.

Stdlib only. Run: python3 ~/.claude/scripts/tests/operating_layer_test.py
Exit 0 = all pass; non-zero = failures.
"""
import ast
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
CLI = (HERE / ".." / "operating-layer.py").resolve()
ROOT = Path("/private/tmp/operating-layer-test")

_passes = 0
_failures = []


def check(cond, label):
    global _passes
    if cond:
        _passes += 1
    else:
        _failures.append(label)
        sys.stderr.write(f"FAIL: {label}\n")


def reset():
    if ROOT.exists():
        shutil.rmtree(ROOT)
    (ROOT / "claude").mkdir(parents=True)
    (ROOT / "codex").mkdir(parents=True)
    (ROOT / "projects").mkdir(parents=True)
    (ROOT / "out").mkdir(parents=True)
    (ROOT / "claude" / "hooks").mkdir()
    (ROOT / "claude" / "logs").mkdir()
    (ROOT / "claude" / "sensory-memory").mkdir()
    (ROOT / "codex" / "hooks").mkdir()
    (ROOT / "codex" / "skills").mkdir()
    (ROOT / "codex" / "plugins" / "cache").mkdir(parents=True)


def write(path, text):
    full = ROOT / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(text, encoding="utf-8")
    return full


def touch_old(path, days=90):
    full = ROOT / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text("old evidence\n", encoding="utf-8")
    old = time.time() - days * 86400
    os.utime(full, (old, old))
    return full


def base_cmd(subcommand, extra=None):
    cmd = [
        sys.executable,
        str(CLI),
        subcommand,
        "--claude-home", str(ROOT / "claude"),
        "--codex-home", str(ROOT / "codex"),
        "--projects-root", str(ROOT / "projects"),
        "--output-root", str(ROOT / "out"),
        "--since-days", "3650",
        "--json",
    ]
    if extra:
        cmd.extend(extra)
    return cmd


def run(subcommand, extra=None):
    proc = subprocess.run(base_cmd(subcommand, extra), capture_output=True, text=True, timeout=120)
    try:
        data = json.loads(proc.stdout or "{}")
    except Exception:
        data = None
    return data, proc


def ids(data):
    return {f["id"] for f in data.get("findings", [])} if isinstance(data, dict) else set()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def assert_no_secret_output(text, label):
    lowered = text.lower()
    check("sk-proj-" not in text and "password=hunter2" not in lowered and "api_key=abc" not in lowered, label)


def _unregistered_test_names(namespace, tests):
    """Return module-level test_* callables missing from an explicit runner list."""
    registered = {getattr(t, "__name__", None) for t in tests}
    discovered = {
        name for name, obj in namespace.items()
        if name.startswith("test_") and callable(obj)
    }
    return sorted(name for name in discovered if name not in registered)


def test_intel_detection_and_clean():
    reset()
    write(
        "claude/hooks/ingest.log",
        "\n".join([
            "2026-06-27T10:00:00Z [track] stop: ingest http=500 cwd=/tmp/app session=s1 password=hunter2",
            "2026-06-27T10:01:00Z [track] stop: ingest http=400 invalid_payload cwd=/tmp/app session=s2",
            "2026-06-27T10:02:00Z [track] stop: ingest http=000000 cwd=/tmp/app session=s3",
            "",
        ]),
    )
    write("codex/hooks/ingest.log", "2026-06-27T10:00:00Z [track] stop: ingest http=200\n")
    write("claude/logs/1pct-violations.log", '{"ts":"2026-06-27T10:00:00Z","flags":["ready-to-proceed"]}\n')
    write("claude/sensory-memory/groq-failures.log", "2026-06-27T10:00:00Z model_not_found moonshotai/kimi\n")
    write("codex/session_index.jsonl", '{"updated_at":"2026-06-27T10:00:00Z","thread_name":"Review workflow audit"}\n')
    data, proc = run("intel")
    check(proc.returncode == 0, "intel bad fixture exits 0")
    got = ids(data)
    check("opintel-artifact-ingest-http-500-claude" in got, "intel detects http 500 artifact ingest failures")
    check("opintel-artifact-ingest-http-400-invalid-payload-claude" in got, "intel detects invalid payload artifact ingest failures")
    check("opintel-artifact-ingest-http-000000-claude" in got, "intel detects transport/no-response artifact ingest failures")
    check("opintel-false-pause-hits" in got, "intel detects false pause hits")
    check("opintel-provider-model-drift" in got, "intel detects provider drift")
    assert_no_secret_output(proc.stdout, "intel redacts secret-like log content")

    reset()
    write("codex/session_index.jsonl", '{"updated_at":"2026-06-27T10:00:00Z","thread_name":"Ordinary work"}\n')
    data, _proc = run("intel")
    check(not any(i.startswith("opintel-artifact-ingest") for i in ids(data)), "intel clean fixture avoids ingest FP")
    check("opintel-provider-model-drift" not in ids(data), "intel clean fixture avoids provider FP")


def test_tools_detection_and_clean():
    reset()
    write("claude/skills/foo/SKILL.md", "---\nname: duplicate\n---\n")
    write("codex/skills/foo/SKILL.md", "---\nname: duplicate\n---\n")
    write("claude/skills/close-day/SKILL.md", "---\nname: close-day\n---\n")
    write("codex/config.toml", '[mcp_servers.figma]\nauth = "missing"\n')
    data, _proc = run("tools")
    got = ids(data)
    check("tools-duplicate-skill-families" in got, "tools detects duplicate skill family")
    check("tools-auth-broken" in got, "tools detects broken auth marker")
    check("tools-legacy-skills" in got, "tools detects legacy skill")
    registry = read_json(ROOT / "out" / "operator-intelligence" / "tool-registry.json")
    duplicate_records = [r for r in registry if r["id"] == "duplicate"]
    check(all("canonical_id" in r and "source_root" in r and "risk_rank" in r for r in duplicate_records), "tools records carry canonicalization fields")
    check(any(r["copy_role"].startswith("canonical") for r in duplicate_records), "tools marks canonical duplicate copy")
    check(any(r["copy_role"] == "custom-copy" for r in duplicate_records), "tools marks noncanonical custom duplicate copy")

    reset()
    write("claude/skills/one/SKILL.md", "---\nname: one\n---\n")
    data, _proc = run("tools")
    check("tools-duplicate-skill-families" not in ids(data), "tools clean fixture avoids duplicate FP")
    check("tools-auth-broken" not in ids(data), "tools clean fixture avoids auth FP")


def test_portfolio_evidence_ai_boundary_agent_cards():
    reset()
    write("projects/app/README.md", "# App\n")
    write("projects/app-copy/README.md", "# App copy\n")
    write("projects/local-ai-kit/README.md", "# LAIK\nlocal AI runtime\n")
    write("projects/local-ai-kit/CLAUDE.md", "MCP tools allowed. No eval yet.\n")
    touch_old("projects/app/evals/backtest-results.md", days=100)
    write("projects/agents/hermes/README.md", "# Hermes\nMCP tools allowed.\n")

    data, _proc = run("portfolio")
    check("portfolio-unresolved-canonical-checkout" in ids(data), "portfolio detects unresolved canonical checkout")

    data, _proc = run("evidence")
    check("evidence-stale-records" in ids(data), "evidence detects stale evidence")

    data, _proc = run("ai-contract")
    got = ids(data)
    check("ai-contract-missing-eval" in got, "ai-contract detects missing eval")
    check("ai-contract-missing-kill-switch" in got, "ai-contract detects missing kill switch")
    check("ai-contract-low-readiness-score" in got, "ai-contract detects low readiness score")
    contracts = read_json(ROOT / "out" / "operator-intelligence" / "ai-contracts.json")
    laik = next(c for c in contracts if c["system"] == "local-ai-kit")
    check(isinstance(laik["readiness_score"], int), "ai contract emits numeric readiness score")
    check(laik["readiness_status"] == "not ready", "ai contract marks low fixture not ready")

    data, _proc = run("agent-cards")
    check("agent-cards-incomplete-readiness" in ids(data), "agent cards detect incomplete readiness")
    cards = read_json(ROOT / "out" / "operator-intelligence" / "agent-capability-cards.json")
    check(cards and "readiness_score" in cards[0], "agent cards include readiness score")

    proc = subprocess.run(
        base_cmd("boundary", ["--check-write", str(ROOT / "projects" / "koho-yehovah" / "file.md")]),
        capture_output=True,
        text=True,
        timeout=60,
    )
    result = json.loads(proc.stdout)
    check(result["allowed"] is False, "boundary check-write detects cross-client ambiguity")

    data, _proc = run("boundary")
    check("boundary-cross-client-ambiguous-project" not in ids(data), "boundary project scan avoids path-only FP")


def test_all_smoke_outputs_parse_and_redact():
    reset()
    write("claude/hooks/ingest.log", "2026-06-27T10:00:00Z stop: ingest http=400 api_key=abc123\n")
    write("claude/skills/foo/SKILL.md", "---\nname: duplicate\n---\n")
    write("codex/skills/foo/SKILL.md", "---\nname: duplicate\n---\n")
    write("projects/app/README.md", "# App\n")
    touch_old("projects/app/.runs/smoke.txt", days=91)
    data, proc = run("all")
    check(proc.returncode == 0, "all smoke exits 0")
    check(data and Path(data["report"]).exists(), "all smoke writes markdown report")
    check(data and Path(data["html"]).exists(), "all smoke writes html report")
    check((ROOT / "out" / "operator-intelligence" / "findings.ndjson").exists(), "all writes findings ndjson")
    check((ROOT / "out" / "operator-intelligence" / "tool-registry.json").exists(), "all writes tool registry")
    check((ROOT / "out" / "operator-intelligence" / "portfolio-registry.yaml").exists(), "all writes portfolio yaml")
    check((ROOT / "out" / "operator-intelligence" / "evidence-registry.ndjson").exists(), "all writes evidence ndjson")
    check((ROOT / "out" / "operator-intelligence" / "improvement-queue.json").exists(), "all writes improvement queue")
    check((ROOT / "out" / "operator-intelligence" / "compare.json").exists(), "all writes compare json")
    check(any((ROOT / "out" / "operator-intelligence" / "history").glob("*-findings.ndjson")), "all writes findings history snapshot")
    check(Path(data["planning_proof"]["markdown"]).exists(), "all writes planning consumption proof")
    json.loads((ROOT / "out" / "operator-intelligence" / "tool-registry.json").read_text())
    json.loads((ROOT / "out" / "operator-intelligence" / "improvement-queue.json").read_text())
    json.loads((ROOT / "out" / "operator-intelligence" / "compare.json").read_text())
    for line in (ROOT / "out" / "operator-intelligence" / "findings.ndjson").read_text().splitlines():
        json.loads(line)
    assert_no_secret_output((ROOT / "out" / "operator-artifacts").read_text() if False else proc.stdout, "all stdout redacts secrets")
    for file in (ROOT / "out").rglob("*"):
        if file.is_file() and file.suffix in {".md", ".html", ".json", ".jsonl", ".yaml"}:
            assert_no_secret_output(file.read_text(errors="ignore"), f"{file.name} redacts secrets")


def test_improve_and_compare_control_loop():
    reset()
    write("projects/app/README.md", "# App\n")
    write("claude/sensory-memory/groq-failures.log", "2026-06-27T10:00:00Z model_not_found stale/model\n")
    data, proc = run("all")
    check(proc.returncode == 0 and data, "control loop first all exits 0")

    write("claude/hooks/ingest.log", "2026-06-27T10:05:00Z stop: ingest http=500 cwd=/tmp/app session=s4\n")
    data, proc = run("all")
    check(proc.returncode == 0 and data, "control loop second all exits 0")

    improve, proc = run("improve")
    check(proc.returncode == 0, "improve exits 0")
    records = improve.get("records", [])
    check(records and records[0]["score"] >= records[-1]["score"], "improve returns ranked queue")
    check(any("artifact-ingest" in r["id"] or "provider-model-drift" in r["id"] for r in records[:3]), "improve prioritizes radar/provider findings")

    compare, proc = run("compare")
    check(proc.returncode == 0, "compare exits 0")
    summary = compare.get("summary", {})
    check(summary.get("added", 0) + summary.get("worsened", 0) > 0, "compare detects added or worsened findings")
    check(Path(compare["report"]).exists() and Path(compare["html"]).exists(), "compare writes markdown and html report")


def test_daily_work_envelope_and_pathway_cooperation():
    reset()
    write("projects/operating-layer/README.md", "# Operating Layer\n")
    evidence = write("out/operator-artifacts/proof.md", "proof without secrets\n")
    before_project_files = sorted(p.relative_to(ROOT / "projects") for p in (ROOT / "projects").rglob("*") if p.is_file())

    start, proc = run("work-start", ["--project", str(ROOT / "projects" / "operating-layer"), "--goal", "Fix Codex artifact ingest invalid payloads"])
    check(proc.returncode == 0, "work-start exits 0")
    work_id = start.get("work_id")
    check(work_id and work_id.startswith("W-"), "work-start creates stable work id")

    start2, _proc = run("work-start", ["--project", str(ROOT / "projects" / "operating-layer"), "--goal", "Fix Codex artifact ingest invalid payloads"])
    check(start2.get("work_id") == work_id, "work-start repeats stable work id")
    items = (ROOT / "out" / "operator-intelligence" / "work-items.ndjson").read_text().splitlines()
    check(len(items) == 1, "work-start upserts instead of duplicating work item")

    log1, proc = run("work-log", [
        "--work-id", work_id,
        "--pathway", "research",
        "--kind", "source-matrix",
        "--gate", "capability-map",
        "--evidence", str(evidence),
        "--result", "pass",
    ])
    check(proc.returncode == 0 and log1.get("run_id", "").startswith(f"R-{work_id}-research"), "work-log records research run")

    log2, _proc = run("work-log", [
        "--work-id", work_id,
        "--pathway", "security",
        "--kind", "control",
        "--evidence", str(evidence),
        "--control-risk", "pii-boundary",
        "--target-pathways", "release,docs",
    ])
    controls = [r for r in log2.get("records", []) if r.get("control_id")]
    check(controls and controls[0]["control_id"].startswith("C-security-pii-boundary"), "work-log creates pathway control")
    control_id = controls[0]["control_id"]

    status, _proc = run("work-status", ["--work-id", work_id])
    summary = status["summary"]
    check(control_id in [c["control_id"] for c in summary["open_controls"]], "later pathway status sees prior pathway control")
    check("security" in summary["pathway_coverage"]["seen"], "status reports pathway coverage")

    run("work-log", [
        "--work-id", work_id,
        "--pathway", "release",
        "--kind", "control-resolution",
        "--evidence", str(evidence),
        "--control-id", control_id,
        "--control-status", "resolved",
        "--result", "pass",
    ])
    run("work-log", [
        "--work-id", work_id,
        "--pathway", "quality",
        "--kind", "smoke",
        "--evidence", str(evidence),
        "--result", "pass",
    ])

    close, _proc = run("work-close", ["--work-id", work_id])
    check(close.get("closed") is True, "work-close closes ready work item")
    daily, proc = run("work-daily")
    check(proc.returncode == 0, "work-daily exits 0")
    check((ROOT / "out" / "operator-intelligence" / "daily-work-dashboard.json").exists(), "work-daily writes dashboard json")
    check(Path(daily["report"]).exists() and Path(daily["html"]).exists(), "work-daily writes markdown and html")

    after_project_files = sorted(p.relative_to(ROOT / "projects") for p in (ROOT / "projects").rglob("*") if p.is_file())
    check(after_project_files == before_project_files, "daily work commands do not modify project repo files")
    for file in (ROOT / "out").rglob("*"):
        if file.is_file() and file.suffix in {".md", ".html", ".json", ".jsonl", ".yaml", ".ndjson"}:
            assert_no_secret_output(file.read_text(errors="ignore"), f"{file.name} redacts secrets in daily work outputs")


def test_daily_work_stale_measurement_detection():
    reset()
    write("projects/operating-layer/README.md", "# Operating Layer\n")
    start, _proc = run("work-start", ["--project", str(ROOT / "projects" / "operating-layer"), "--goal", "Stale measurement test"])
    work_id = start["work_id"]
    stale = {
        "measurement_id": "M-stale",
        "run_id": "R-stale",
        "work_id": work_id,
        "pathway": "quality",
        "gate": "smoke",
        "kind": "test",
        "result": "pass",
        "timestamp": "2026-01-01T00:00:00Z",
        "evidence_id": "E-stale",
        "evidence_path": str(ROOT / "out" / "old.md"),
        "stale_after_days": 1,
    }
    path = ROOT / "out" / "operator-intelligence" / "pathway-measurements.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stale) + "\n", encoding="utf-8")
    status, _proc = run("work-status", ["--work-id", work_id])
    check(status["summary"]["stale_measurements"], "work-status detects stale measurement")
    check(status["summary"]["closeout_readiness"] == "not_ready", "stale measurement blocks closeout readiness")


def test_work_close_extracts_learning_candidate():
    reset()
    write("projects/consult-ops/README.md", "# ConsultOps\n")
    evidence = write("out/operator-artifacts/close-proof.md", "verified proof\n")
    project_path = str(ROOT / "projects" / "consult-ops")
    start, _proc = run("work-start", ["--project", project_path, "--goal", "Close with learning"])
    work_id = start["work_id"]
    run("work-log", [
        "--work-id", work_id, "--pathway", "quality", "--kind", "verify",
        "--evidence", str(evidence), "--result", "pass", "--gate", "quality-gate",
        "--proof-type", "artifact", "--verified-by", "python3 quality-guard.py",
    ])
    closed, proc = run("work-close", ["--work-id", work_id])
    check(proc.returncode == 0 and closed.get("closed") is True, "work-close closes ready work")
    learning = closed.get("learning", {})
    check(learning.get("work_id") == work_id and learning.get("proof_that_mattered") == str(evidence),
          "work-close extracts proof-backed learning candidate")
    check("possible_global_rule" in learning and "quality" in learning.get("possible_global_rule", ""),
          "learning candidate includes possible global rule")
    ledger = ROOT / "out" / "operator-intelligence" / "learning-candidates.ndjson"
    check(ledger.exists() and work_id in ledger.read_text(encoding="utf-8"),
          "learning candidate is persisted outside MEMORY.md")
    check(Path(closed.get("learning_report", "")).exists() and Path(closed.get("learning_html", "")).exists(),
          "work-close writes learning markdown and html")


def test_pathway_trust_report_and_pathway_next_metadata():
    reset()
    write("projects/consult-ops/package.json", '{"name":"consult-ops"}\n')
    write("projects/consult-ops/src/index.ts", "export const x = 1;\n")
    project_path = str(ROOT / "projects" / "consult-ops")

    trust, proc = run("pathway-trust", ["--project", project_path])
    check(proc.returncode == 0, "pathway-trust exits 0")
    check(trust.get("status") == "pass", f"pathway-trust status pass (got {trust.get('status')})")
    check(Path(trust.get("report", "")).exists() and Path(trust.get("html", "")).exists(),
          "pathway-trust writes markdown and html")
    trust_json = ROOT / "out" / "operator-intelligence" / "pathway-trust.json"
    check(trust_json.exists(), "pathway-trust writes operator-intelligence JSON")

    rec, _proc = run("pathway-next", ["--project", project_path])
    check(rec.get("pathway_trust", {}).get("status") == "pass",
          "pathway-next includes latest pathway-trust status")
    check(rec.get("recommendation_confidence", {}).get("level") in {"high", "medium", "low"},
          "pathway-next includes recommendation confidence level")
    report_text = Path(rec["report"]).read_text(encoding="utf-8")
    check("## Pathway Trust" in report_text and "Status:** `pass`" in report_text,
          "pathway-next report renders trust status")
    check("## Recommendation Confidence" in report_text and "Why this, why not runner-up" in report_text,
          "pathway-next report renders confidence and counterfactual")


def test_pathway_next_recommendation_and_cohesion():
    reset()
    write("projects/consult-ops/README.md", "# ConsultOps\n")
    evidence = write("out/operator-artifacts/pn-proof.md", "proof without secrets\n")
    project_path = str(ROOT / "projects" / "consult-ops")
    before_project_files = sorted(p.relative_to(ROOT / "projects") for p in (ROOT / "projects").rglob("*") if p.is_file())

    # 1. No tracked work -> foundation-first: research recommended, 11 ranked pathways.
    rec, proc = run("pathway-next", ["--project", project_path])
    check(proc.returncode == 0, "pathway-next exits 0")
    check(rec.get("recommended_pathway") == "research", "untracked project recommends research foundation gate")
    check(len(rec.get("ranked", [])) == 11, "pathway-next ranks all 11 pathways")
    check({f["id"] for f in rec.get("findings", [])} == {"pathway-next-recommendation"}, "pathway-next emits recommendation finding")
    check(Path(rec["report"]).exists() and Path(rec["html"]).exists(), "pathway-next writes markdown and html")
    check("work-start" in rec.get("next_command", ""), "untracked project proposes work-start to open shared id")
    check("recommendation_id" in rec, "pathway-next emits stable recommendation_id")
    conf = rec.get("recommendation_confidence", {})
    check(conf.get("runner_up_pathway") and isinstance(conf.get("top_evidence"), list),
          "pathway-next confidence names runner-up and top evidence")

    # Resolve by bare project name against projects-root.
    by_name, _proc = run("pathway-next", ["--project", "consult-ops"])
    check(by_name.get("project") == "consult-ops", "pathway-next resolves project by bare name")

    # 1b. Project-local ingestion: a .planning audit finding routes to its pathway.
    write("projects/consult-ops/.planning/audit.json", json.dumps({
        "findings": [
            {"id": "rls-open", "severity": "high", "message": "anon read exposure", "pathway": "security"},
            {"id": "vague", "severity": "low", "message": "noop"},
        ]
    }))
    # Re-baseline after fixture writes; the tool must not mutate project files from here.
    before_project_files = sorted(p.relative_to(ROOT / "projects") for p in (ROOT / "projects").rglob("*") if p.is_file())
    rec_local, _proc = run("pathway-next", ["--project", project_path])
    check(rec_local.get("signal_sources", {}).get("project_local", 0) >= 2,
          "pathway-next ingests project-local findings (audit + missing STATE.md)")
    sec = next((s for s in rec_local["ranked"] if s["pathway"] == "security"), {})
    check(sec.get("score", 0) >= 8, "explicit-pathway local finding boosts its target pathway")
    gov = next((s for s in rec_local["ranked"] if s["pathway"] == "govern"), {})
    check(any("STATE.md" in r for r in gov.get("reasons", [])), "missing STATE.md surfaces as a govern signal")

    # 2. Satisfy foundation gates, then a downstream control re-ranks the target pathway.
    start, _proc = run("work-start", ["--project", project_path, "--goal", "Prove ConsultOps next-pathway routing"])
    work_id = start.get("work_id")
    run("work-log", ["--work-id", work_id, "--pathway", "research", "--kind", "dossier", "--evidence", str(evidence), "--result", "pass"])
    run("work-log", ["--work-id", work_id, "--pathway", "govern", "--kind", "decision", "--evidence", str(evidence), "--result", "pass"])
    run("work-log", [
        "--work-id", work_id, "--pathway", "security", "--kind", "control", "--evidence", str(evidence),
        "--control-risk", "rls-gap", "--target-pathways", "data",
    ])

    rec2, _proc = run("pathway-next", ["--project", project_path])
    check(rec2.get("recommended_pathway") == "data", "open control re-ranks target pathway to the top")
    top = rec2["ranked"][0]
    check(any("rls-gap" in r for r in top["reasons"]), "recommendation cites the originating control as evidence")
    check(rec2.get("work_id") == work_id, "tracked project reuses shared work id")
    check("work-log" in rec2.get("next_command", "") and work_id in rec2.get("next_command", ""), "next_command logs against shared work id")
    check("--proof-type artifact" in rec2.get("next_command", "") and "--recommendation-id" in rec2.get("next_command", ""),
          "tracked next_command asks for proof metadata")

    # 3. Central-output-only + secret hygiene.
    after_project_files = sorted(p.relative_to(ROOT / "projects") for p in (ROOT / "projects").rglob("*") if p.is_file())
    check(after_project_files == before_project_files, "pathway-next does not modify project repo files")
    for file in (ROOT / "out").rglob("*"):
        if file.is_file() and file.suffix in {".md", ".html", ".json", ".ndjson"}:
            assert_no_secret_output(file.read_text(errors="ignore"), f"{file.name} redacts secrets in pathway-next outputs")


def test_pathway_run_creates_plan_and_preserves_project():
    reset()
    write("projects/consult-ops/README.md", "# ConsultOps\n")
    project_path = str(ROOT / "projects" / "consult-ops")
    before_project_files = sorted(p.relative_to(ROOT / "projects") for p in (ROOT / "projects").rglob("*") if p.is_file())

    res, proc = run("pathway-run", ["--project", project_path, "--goal", "Run the next pathway slice"])
    check(proc.returncode == 0, "pathway-run exits 0")
    check(res.get("work_id"), "pathway-run creates or reuses a work id")
    check(res.get("recommendation_id"), "pathway-run links to a recommendation")
    check(Path(res.get("report", "")).exists() and Path(res.get("html", "")).exists(),
          "pathway-run writes markdown and html run plan")
    plan_text = Path(res["report"]).read_text(encoding="utf-8")
    check("## Skill And Guard" in plan_text and "## Required Proof Before Closeout" in plan_text,
          "pathway-run plan names skill/guard and required proof")
    check("--proof-type artifact" in plan_text and "--recommendation-id" in plan_text,
          "pathway-run plan contains proof-ready work-log command")
    plans_path = ROOT / "out" / "operator-intelligence" / "pathway-run-plans.ndjson"
    check(plans_path.exists() and plans_path.read_text(encoding="utf-8").strip(),
          "pathway-run writes run-plan ledger")

    again, _proc = run("pathway-run", ["--project", project_path, "--goal", "Run the next pathway slice"])
    check(again.get("work_id") == res.get("work_id"), "pathway-run reuses active work id")
    after_project_files = sorted(p.relative_to(ROOT / "projects") for p in (ROOT / "projects").rglob("*") if p.is_file())
    check(after_project_files == before_project_files, "pathway-run does not mutate project repo files")


def test_portfolio_next_ranks_riskier_project_first():
    reset()
    write("projects/safe/.git/HEAD", "ref: refs/heads/main\n")
    write("projects/safe/README.md", "# Safe\n")
    write("projects/safe/.runs/smoke.txt", "ok\n")
    write("projects/risky/.git/HEAD", "ref: refs/heads/main\n")
    write("projects/risky/README.md", "# Risky\n")
    safe_path = str(ROOT / "projects" / "safe")
    risky_path = str(ROOT / "projects" / "risky")
    nested_path = str(ROOT / "projects" / "group" / "nested")

    start, _proc = run("work-start", ["--project", risky_path, "--goal", "Resolve risk"])
    run("work-log", [
        "--work-id", start["work_id"], "--pathway", "security", "--kind", "control",
        "--control-risk", "auth gap", "--target-pathways", "security",
    ])
    write("projects/group/nested/README.md", "# Nested\n")
    nested, _proc = run("work-start", ["--project", nested_path, "--goal", "Resolve nested risk"])
    run("work-log", [
        "--work-id", nested["work_id"], "--pathway", "security", "--kind", "control",
        "--control-risk", "auth gap", "--target-pathways", "security",
    ])
    run("work-log", [
        "--work-id", nested["work_id"], "--pathway", "quality", "--kind", "control",
        "--control-risk", "missing proof", "--target-pathways", "quality",
    ])
    res, proc = run("portfolio-next")
    check(proc.returncode == 0, "portfolio-next exits 0")
    check(res.get("top_project") == "nested", "portfolio-next includes nested active work and ranks riskier project first")
    top = res.get("records", [])[0]
    check(top.get("open_controls", 0) >= 1 and top.get("active_work") == 1,
          "portfolio-next explains active work and open controls")
    check(Path(res.get("queue", "")).exists() and Path(res.get("report", "")).exists() and Path(res.get("html", "")).exists(),
          "portfolio-next writes json, markdown, and html")


def test_rule_map_names_enforced_and_prose_only_rules():
    reset()
    res, proc = run("rule-map")
    check(proc.returncode == 0, "rule-map exits 0")
    records = res.get("records", [])
    enforced = [r for r in records if r.get("enforcement_status") == "enforced"]
    prose_only = [r for r in records if r.get("enforcement_status") == "prose-only" and r.get("criticality") == "critical"]
    check(enforced, "rule-map names at least one enforced rule")
    check(prose_only, "rule-map names at least one critical prose-only gap")
    check(all(r.get("backing_paths") for r in enforced), "rule-map never claims enforcement without backing paths")
    check(Path(res.get("rule_map", "")).exists() and Path(res.get("report", "")).exists() and Path(res.get("html", "")).exists(),
          "rule-map writes json, markdown, and html")


def test_cockpit_writes_one_page_operator_surface():
    reset()
    write("projects/app/.git/HEAD", "ref: refs/heads/main\n")
    write("projects/app/README.md", "# App\n")
    run("portfolio-next")
    run("rule-map")
    run("pathway-metric")
    res, proc = run("cockpit")
    check(proc.returncode == 0, "cockpit exits 0")
    check(Path(res.get("cockpit", "")).exists() and Path(res.get("report", "")).exists() and Path(res.get("html", "")).exists(),
          "cockpit writes json, markdown, and html")
    text = Path(res["report"]).read_text(encoding="utf-8")
    check("## What Is Happening" in text and "## What Matters" in text and "## What To Do Next" in text,
          "cockpit answers happening, matters, and next move")
    data = read_json(res["cockpit"])
    source_paths = data.get("source_paths", {})
    check(all(Path(p).exists() for p in source_paths.values() if p), "cockpit source links point to existing files")


def test_pfos_cockpit_snapshot_export_is_browser_safe():
    reset()
    write("projects/app/.git/HEAD", "ref: refs/heads/main\n")
    write("projects/app/README.md", "# App\n")
    evidence = write("out/operator-artifacts/proof.md", "proof body with /Users/alexhale/private/source.ts\n")
    project_path = str(ROOT / "projects" / "app")

    trust, _proc = run("pathway-trust", ["--project", project_path])
    rec, _proc = run("pathway-next", ["--project", project_path])
    run("pathway-run", ["--project", project_path, "--goal", "Build the PFOS cockpit"])
    start, _proc = run("work-start", ["--project", project_path, "--goal", "Prove PFOS cockpit"])
    run("work-log", [
        "--work-id", start["work_id"], "--pathway", rec["recommended_pathway"], "--kind", "verify",
        "--evidence", str(evidence), "--result", "pass", "--gate", "pfos-cockpit-gate",
        "--proof-type", "artifact", "--verified-by", "python3 /Users/alexhale/.claude/scripts/quality-guard.py",
        "--recommendation-id", rec["recommendation_id"],
    ])

    proofs_path = ROOT / "out" / "operator-intelligence" / "proofs.ndjson"
    proofs = [json.loads(line) for line in proofs_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    proofs.append({
        "proof_id": "P-stale",
        "timestamp": "2020-01-01T00:00:00Z",
        "proof_type": "artifact",
        "evidence_path": "/Users/alexhale/private/raw-evidence.md",
        "work_id": start["work_id"],
        "pathway": "quality",
        "result": "pass",
        "stale_after_days": 1,
        "verified_by": "npx vitest run tests/lib/pathway/*",
        "recommendation_id": "REC-old",
        "project": "app",
        "project_path": project_path,
    })
    proofs_path.write_text("\n".join(json.dumps(p) for p in proofs) + "\n", encoding="utf-8")
    current_proof_id = proofs[0]["proof_id"]

    approved, approved_proc = run("pathway-decision", [
        "--action", "approve", "--project", project_path, "--pathway", rec["recommended_pathway"],
        "--recommendation-id", rec["recommendation_id"],
        "--reason", "Approve after python3 /Users/alexhale/private/check.py proved it.",
    ])
    check(approved_proc.returncode == 0 and approved.get("decision", {}).get("action") == "approve",
          "pathway-decision records approval")
    assigned, assigned_proc = run("pathway-decision", [
        "--action", "assign", "--project", "app", "--pathway", rec["recommended_pathway"],
        "--agent", "codex", "--reason", "Codex owns the next implementation proof.",
    ])
    check(assigned_proc.returncode == 0 and assigned.get("decision", {}).get("agent") == "codex",
          "pathway-decision records assignment")
    closed, closed_proc = run("pathway-decision", [
        "--action", "closeout", "--project", "app", "--pathway", rec["recommended_pathway"],
        "--work-id", start["work_id"], "--proof-id", current_proof_id,
        "--reason", "Current proof supports closeout.",
    ])
    check(closed_proc.returncode == 0 and closed.get("decision", {}).get("proof_id") == current_proof_id,
          "pathway-decision records proof-backed closeout intent")

    findings_path = ROOT / "out" / "operator-intelligence" / "findings.ndjson"
    findings_path.write_text(json.dumps({
        "id": "tools-auth-broken",
        "workflow": "tools",
        "severity": "warn",
        "message": "npm run auth-check failed for /Users/alexhale/.env.local",
    }) + "\n", encoding="utf-8")

    run("portfolio-next")
    run("rule-map")
    run("pathway-metric", ["--gate-target", "0.8"])
    res, proc = run("pfos-cockpit")
    check(proc.returncode == 0, "pfos-cockpit exits 0")
    check(Path(res.get("pfos_cockpit", "")).exists() and Path(res.get("report", "")).exists() and Path(res.get("html", "")).exists(),
          "pfos-cockpit writes json, markdown, and html")

    snapshot = read_json(res["pfos_cockpit"])
    text = json.dumps(snapshot)
    check(snapshot.get("schema_version") == 3, "pfos-cockpit emits schema v3")
    check(snapshot.get("recommendation", {}).get("why_this"), "pfos-cockpit includes recommendation rationale")
    check(snapshot.get("alex_queue") is not None and snapshot.get("autonomous_queue"), "pfos-cockpit builds Alex and autonomous queues")
    check(snapshot.get("evidence_ledger") and {e.get("status") for e in snapshot["evidence_ledger"]} >= {"current", "stale"},
          "pfos-cockpit marks current and stale proof summaries")
    check(snapshot.get("portfolio_queue"), "pfos-cockpit includes safe portfolio queue")
    check(any(d.get("action") == "closeout" for d in snapshot.get("approval_history", [])),
          "pfos-cockpit exports approval history")
    check(snapshot.get("decision_memory"), "pfos-cockpit exports decision memory")
    check(any(a.get("agent") == "codex" for a in snapshot.get("agent_assignments", [])),
          "pfos-cockpit exports agent assignments")
    check(any(c.get("work_id") == start["work_id"] and c.get("status") == "ready" for c in snapshot.get("closeout_queue", [])),
          "pfos-cockpit exports proof-backed closeout readiness")
    check(snapshot.get("health", {}).get("tool_warnings"), "pfos-cockpit includes tool warning labels")
    check("/Users/" not in text and "/private/tmp/" not in text, "pfos-cockpit strips private absolute paths")
    check("source_paths" not in text and "raw-evidence.md" in text and "proof body" not in text,
          "pfos-cockpit excludes source paths and raw evidence bodies")
    check("python3" not in text and "npx vitest" not in text and "npm run" not in text and "proof_command" not in text,
          "pfos-cockpit strips raw command strings and mutation command fields")
    check(snapshot.get("trust", {}).get("status") == trust.get("status"), "pfos-cockpit carries trust status")

    reset()
    empty, empty_proc = run("pfos-cockpit")
    check(empty_proc.returncode == 0, "pfos-cockpit handles missing ledgers")
    empty_snapshot = read_json(empty["pfos_cockpit"])
    check(empty_snapshot.get("alex_queue") == [] and empty_snapshot.get("evidence_ledger") == [] and empty_snapshot.get("approval_history") == [],
          "pfos-cockpit missing ledgers degrade to empty queues")


def test_ingest_review_closes_loop():
    reset()
    write("projects/consult-ops/README.md", "# ConsultOps\n")
    project_path = str(ROOT / "projects" / "consult-ops")
    out_file = ROOT / "projects" / "consult-ops" / ".planning" / "review" / "latest-findings.json"

    # Prefix routing: one finding per mapped guard prefix + a non-finding that must be skipped.
    review_json = {
        "verdict": "FIX_THEN_SHIP",
        "findings": [
            {"id": "sec-rls-disabled", "severity": "high", "title": "anon read exposure"},
            {"id": "mig-drop-table", "severity": "high", "title": "drop table"},
            {"id": "gov-no-ledger", "severity": "warn", "title": "no ledger"},
            {"id": "rel-no-deploy-rails", "severity": "warn", "title": "no rails"},
            {"id": "impl-no-spec", "severity": "warn", "title": "no spec"},
            {"id": "q-no-coverage-gate", "severity": "warn", "title": "no gate"},
            {"id": "obs-no-instrumentation", "severity": "warn", "title": "no otel"},
            {"id": "td-stale-deps", "severity": "info", "title": "stale"},
            {"id": "ff-no-lock", "severity": "warn", "title": "no foundation lock"},
            {"id": "rs-no-dossier", "severity": "warn", "title": "no dossier"},
            {"not": "a finding"},
        ],
    }
    review_path = write("out/review-input.json", json.dumps(review_json))

    res, proc = run("ingest-review", ["--project", project_path, "--input", str(review_path)])
    check(proc.returncode == 0, "ingest-review exits 0")
    check(res.get("finding_count") == 10, "ingest-review writes all findings and skips non-findings")
    check(out_file.exists(), "ingest-review writes .planning/review/latest-findings.json")
    written = read_json(out_file)
    tag = {f["id"]: f["pathway"] for f in written["findings"]}
    expected = {
        "sec-rls-disabled": "security", "mig-drop-table": "data", "gov-no-ledger": "govern",
        "rel-no-deploy-rails": "release", "impl-no-spec": "implementation",
        "q-no-coverage-gate": "quality", "obs-no-instrumentation": "observability",
        "td-stale-deps": "techdebt", "ff-no-lock": "research", "rs-no-dossier": "research",
    }
    check(all(tag.get(k) == v for k, v in expected.items()), "guard id prefixes route to correct pathways")

    # Overwrite, not append: a second ingest with one finding replaces the file.
    review2 = write("out/review-input-2.json", json.dumps({"findings": [{"id": "sec-one", "severity": "warn", "title": "x"}]}))
    res2, _proc = run("ingest-review", ["--project", project_path, "--input", str(review2)])
    check(res2.get("finding_count") == 1 and len(read_json(out_file)["findings"]) == 1, "second ingest overwrites (no append)")

    # External signal: re-ingest the full set, then pathway-next sees it and security ranks high.
    run("ingest-review", ["--project", project_path, "--input", str(review_path)])
    rec, _proc = run("pathway-next", ["--project", project_path])
    check(rec.get("signal_sources", {}).get("project_local", 0) >= 10, "pathway-next ingests review findings from .planning")
    sec = next((s for s in rec["ranked"] if s["pathway"] == "security"), {})
    check(sec.get("score", 0) >= 8, "ingested high-severity security finding raises security in the ranking")

    # Stdin path (review-stack pipes the pool, no --input file).
    stdin_payload = json.dumps({"findings": [{"id": "sec-stdin", "severity": "warn", "title": "via stdin"}]})
    proc_stdin = subprocess.run(base_cmd("ingest-review", ["--project", project_path]),
                                input=stdin_payload, capture_output=True, text=True, timeout=60)
    stdin_res = json.loads(proc_stdin.stdout or "{}")
    check(stdin_res.get("finding_count") == 1, "ingest-review reads the finding pool from stdin")

    # Emergency escalation: a cluster of error findings out-ranks the govern foundation gate.
    write("projects/consult-ops/.planning/review/latest-findings.json", json.dumps({"findings": [
        {"id": "sec-a", "severity": "high", "title": "p0 one", "pathway": "security"},
        {"id": "sec-b", "severity": "high", "title": "p0 two", "pathway": "security"},
        {"id": "sec-c", "severity": "high", "title": "p0 three", "pathway": "security"},
    ]}))
    rec_fire, _proc = run("pathway-next", ["--project", project_path])
    sec_s = next((s["score"] for s in rec_fire["ranked"] if s["pathway"] == "security"), 0)
    gov_s = next((s["score"] for s in rec_fire["ranked"] if s["pathway"] == "govern"), 0)
    check(sec_s > gov_s, "3 error findings out-rank the govern foundation gate (no masking of live fires)")

    # Secret hygiene on the written client-repo file.
    secret_in = write("out/review-secret.json", json.dumps({"findings": [
        {"id": "sec-leak", "severity": "high", "title": "token sk-proj-abc123def456ghi789jkl012mno in code"}
    ]}))
    run("ingest-review", ["--project", project_path, "--input", str(secret_in)])
    assert_no_secret_output(out_file.read_text(errors="ignore"), "ingest-review redacts secrets in written file")


def test_stale_review_gate():
    reset()
    write("projects/consult-ops/README.md", "# ConsultOps\n")
    project_path = str(ROOT / "projects" / "consult-ops")
    review_dir = "projects/consult-ops/.planning/review/latest-findings.json"
    sec_finding = {"id": "sec-rls", "severity": "high", "title": "anon read", "pathway": "security"}

    # Stale review (20 days old): findings must NOT be ingested; a stale-review finding appears.
    old_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 20 * 86400))
    write(review_dir, json.dumps({"generated_at": old_ts, "source": "review-stack", "findings": [sec_finding]}))
    rec_stale, _proc = run("pathway-next", ["--project", project_path])
    sec_stale = next((s["score"] for s in rec_stale["ranked"] if s["pathway"] == "security"), 0)
    reasons = " ".join(r for s in rec_stale["ranked"] for r in s.get("reasons", []))
    check(sec_stale < 40, "stale review's security finding is not ingested (no +40)")
    check("stale-review" in reasons, "stale review surfaces a stale-review finding")

    # Fresh review (now): findings ARE ingested.
    new_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write(review_dir, json.dumps({"generated_at": new_ts, "source": "review-stack", "findings": [sec_finding]}))
    rec_fresh, _proc = run("pathway-next", ["--project", project_path])
    sec_fresh = next((s["score"] for s in rec_fresh["ranked"] if s["pathway"] == "security"), 0)
    check(sec_fresh >= 40, "fresh review's security finding is ingested (+40)")


def test_pathway_metric():
    reset()
    write("projects/consult-ops/README.md", "# ConsultOps\n")
    evidence = write("out/operator-artifacts/m-proof.md", "proof\n")
    project_path = str(ROOT / "projects" / "consult-ops")

    # A recommendation with no follow-up -> rate 0, gate fails.
    run("pathway-next", ["--project", project_path])
    m0, proc = run("pathway-metric", ["--gate-target", "0.5"])
    check(proc.returncode == 0, "pathway-metric exits 0")
    check(m0["metric"]["total_recommendations"] >= 1, "pathway-metric counts recommendations")
    check(m0["metric"]["acted_on"] == 0 and m0["metric"]["rate"] == 0.0, "no follow-up -> rate 0.0")
    check(m0["metric"]["gate_pass"] is False, "rate below target fails the gate")

    # Act on it: a matching work-log (same project + pathway) makes it acted-on.
    pathway = m0["records"][0]["pathway"]
    start, _proc = run("work-start", ["--project", project_path, "--goal", "act on the recommendation"])
    work_id = start["work_id"]
    run("work-log", ["--work-id", work_id, "--pathway", pathway, "--kind", "verify", "--evidence", str(evidence), "--result", "pass"])
    m1, _proc = run("pathway-metric", ["--gate-target", "0.5"])
    check(m1["metric"]["acted_on"] >= 1 and m1["metric"]["rate"] > 0, "matching work-log marks the recommendation acted-on")
    check(pathway in m1["metric"]["by_pathway"], "pathway-metric breaks the rate down by pathway")


def test_proof_registry_and_proved_metric():
    reset()
    write("projects/consult-ops/README.md", "# ConsultOps\n")
    evidence = write("out/operator-artifacts/proof.md", "proof\n")
    second_evidence = write("out/operator-artifacts/proof-2.md", "second proof\n")
    project_path = str(ROOT / "projects" / "consult-ops")

    rec, _proc = run("pathway-next", ["--project", project_path])
    recommendation_id = rec["recommendation_id"]
    pathway = rec["recommended_pathway"]
    metric0, _proc = run("pathway-metric", ["--gate-target", "0.5"])
    check(metric0["metric"]["proved"] == 0 and metric0["metric"]["proved_rate"] == 0.0,
          "unproved recommendation has proved_rate 0")

    missing, _proc = run("proof-add", [
        "--project", project_path, "--pathway", pathway, "--proof-type", "artifact",
        "--evidence", str(ROOT / "out" / "missing.md"),
    ])
    check("proof-add-missing-evidence" in ids(missing), "proof-add rejects missing evidence")

    start, _proc = run("work-start", ["--project", project_path, "--goal", "prove recommendation"])
    work_id = start["work_id"]
    logged, _proc = run("work-log", [
        "--work-id", work_id, "--pathway", pathway, "--kind", "verify",
        "--evidence", str(evidence), "--result", "pass", "--gate", f"{pathway}-gate",
        "--proof-type", "artifact", "--verified-by", "python3 tests", "--recommendation-id", recommendation_id,
    ])
    check(any(r.get("proof_id") for r in logged.get("records", [])), "work-log writes linked proof metadata")
    proofs_path = ROOT / "out" / "operator-intelligence" / "proofs.ndjson"
    proofs = [json.loads(line) for line in proofs_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    check(any(p.get("recommendation_id") == recommendation_id and p.get("verified_by") == "python3 tests" for p in proofs),
          "proof ledger links proof to recommendation and verifier")

    added, _proc = run("proof-add", [
        "--project", project_path, "--pathway", pathway, "--proof-type", "report",
        "--evidence", str(second_evidence), "--verified-by", "manual review",
    ])
    check(Path(added.get("report", "")).exists() and Path(added.get("html", "")).exists(),
          "proof-add writes markdown and html proof report")

    metric1, _proc = run("pathway-metric", ["--gate-target", "0.5"])
    check(metric1["metric"]["acted_on"] >= 1 and metric1["metric"]["proved"] >= 1,
          "pathway-metric distinguishes acted-on and proved recommendations")
    check(metric1["metric"]["proved_rate"] > 0 and "proof_gate_pass" in metric1["metric"],
          "pathway-metric emits proved_rate and proof gate")


def test_project_scoping_no_substring_bleed():
    # Regression for the GLM-caught P0: project 'ops' must not match '/x/consult-ops/y'.
    reset()
    write("projects/ops/README.md", "# ops\n")
    write("projects/consult-ops/README.md", "# consult-ops\n")
    findings = [
        {"id": "sec-belongs-to-ops", "workflow": "security", "severity": "error", "message": "m",
         "evidence": [{"path": str(ROOT / "projects" / "ops" / "x.py")}]},
        {"id": "sec-belongs-to-consultops", "workflow": "security", "severity": "error", "message": "m",
         "evidence": [{"path": str(ROOT / "projects" / "consult-ops" / "y.py")}]},
    ]
    fpath = ROOT / "out" / "operator-intelligence" / "findings.ndjson"
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text("\n".join(json.dumps(f) for f in findings) + "\n", encoding="utf-8")

    rec, _proc = run("pathway-next", ["--project", str(ROOT / "projects" / "ops")])
    check(rec["signal_sources"]["operating_layer"] == 1, "project 'ops' scopes only its own finding, not consult-ops's (no substring bleed)")


def test_ingest_review_schema_contract():
    # The persisted finding schema is a CONTRACT. The behavior tests check counts
    # and pathway tags but not WHICH fields survive — so a silent rename like
    # file -> filepath would make every /pathway finding unlocatable while staying
    # green. This pins the exact normalized shape. (Real-use motivation 2026-06-27.)
    reset()
    write("projects/consult-ops/README.md", "# ConsultOps\n")
    project_path = str(ROOT / "projects" / "consult-ops")
    rich = {"source": "review-stack", "findings": [{
        "id": "sec-rls-disabled",
        "severity": "critical",
        "message": "x" * 400,                         # over the 240 cap
        "file": "supabase/migrations/008.sql",
        "line": 158,
        "confidence": "high",
        "locations": ["a.sql:1", "b.sql:2"],          # rich fields the guard emits
        "remediation": "Re-enable RLS with a tenant policy.",
        "standard": "OWASP-A01",
    }]}
    pool = write("out/pool.json", json.dumps(rich))
    run("ingest-review", ["--project", project_path, "--input", str(pool)])
    persisted = read_json(ROOT / "projects" / "consult-ops" / ".planning" / "review" / "latest-findings.json")
    f = persisted["findings"][0]
    # Actionability: a finding must stay locatable (file + line) after ingest.
    check(f.get("file") == "supabase/migrations/008.sql", "ingest preserves file (finding stays locatable)")
    check(f.get("line") == 158, "ingest preserves line")
    # Severity must not be silently downgraded out of the high tier.
    check(f.get("severity") in ("critical", "error", "high"), "ingest keeps a critical finding in the high-severity tier")
    check(f.get("pathway") == "security", "ingest tags pathway from the id prefix")
    # Documented truncation, not a silent surprise.
    check(len(f.get("message", "")) <= 240, "ingest caps message at 240 chars")
    # Schema lock: exactly these keys. A dropped/renamed field fails the build.
    check(set(f.keys()) == {"id", "message", "severity", "pathway", "file", "line", "confidence", "source"},
          f"ingest output schema is locked (got {sorted(f.keys())})")


def test_ingest_review_malformed_and_empty():
    # Real review pools can be truncated, empty, or corrupt. Ingest must degrade
    # to an explicit finding, never crash — a crash here silently zeroes a
    # project's signal and /pathway reverts to foundation defaults unnoticed.
    reset()
    write("projects/consult-ops/README.md", "# ConsultOps\n")
    project_path = str(ROOT / "projects" / "consult-ops")

    bad = write("out/bad.json", "{not valid json")
    data, proc = run("ingest-review", ["--project", project_path, "--input", str(bad)])
    check(proc.returncode == 0, "ingest-review survives malformed JSON without crashing")
    surfaced = {x.get("id") for x in ((data or {}).get("findings") or []) + ((data or {}).get("records") or [])}
    check("ingest-review-bad-json" in surfaced, "malformed JSON yields an explicit bad-json finding")

    empty = write("out/empty.json", json.dumps({"findings": []}))
    data2, proc2 = run("ingest-review", ["--project", project_path, "--input", str(empty)])
    check(proc2.returncode == 0 and (data2 or {}).get("finding_count", -1) == 0,
          "empty findings list ingests to zero records cleanly")


def _duplicate_module_level_names(source):
    """Names bound 2+ times at the literal module top level (the SEVERITY_WEIGHT
    shadowing class GLM caught). Only scans tree.body, so try/except import
    fallbacks and `if`-guarded re-binds are not flagged."""
    tree = ast.parse(source)
    counts = {}

    def bump(name):
        counts[name] = counts.get(name, 0) + 1

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bump(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    bump(tgt.id)
                elif isinstance(tgt, (ast.Tuple, ast.List)):
                    for elt in tgt.elts:
                        if isinstance(elt, ast.Name):
                            bump(elt.id)
        elif isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
            bump(node.target.id)
    return {name: n for name, n in counts.items() if n > 1}


def test_source_integrity_no_duplicate_module_level_names():
    # The guard must actually work: a planted duplicate is detected, singles are not.
    planted = _duplicate_module_level_names("A = 1\nB = 2\nA = 3\n")
    check(planted.get("A") == 2, "duplicate-name guard detects a planted module-level dup")
    check("B" not in planted, "guard does not false-flag a single assignment")
    # Legitimate try/except import fallbacks and if-guarded re-binds must NOT be flagged.
    benign = (
        "try:\n    import foo as bar\nexcept ImportError:\n    bar = None\n"
        "X = 1\nif True:\n    X = 2\n"
    )
    check(_duplicate_module_level_names(benign) == {}, "guard ignores try/except + conditional re-binding")
    # Regression: operating-layer.py must have no shadowed module-level constants/defs.
    real_dups = _duplicate_module_level_names(CLI.read_text(encoding="utf-8"))
    check(real_dups == {}, f"operating-layer.py has no duplicate module-level names (found: {real_dups})")


def test_test_runner_integrity_detects_unregistered_tests():
    def test_registered():
        return None

    def test_missing():
        return None

    fake_namespace = {
        "test_registered": test_registered,
        "test_missing": test_missing,
        "helper": lambda: None,
    }
    check(_unregistered_test_names(fake_namespace, [test_registered]) == ["test_missing"],
          "runner integrity detects a planted unregistered test")
    check(_unregistered_test_names(fake_namespace, [test_registered, test_missing]) == [],
          "runner integrity passes when all planted tests are registered")


def test_pathway_execution_profile_invariants():
    """Every pathway carries a doctrine + execution profile; no drift; card returns copies."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("operating_layer_mod", str(CLI))
    ol = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ol)
    for p in ol.PATHWAY_ORDER:
        check(p in ol.PATHWAY_DOCTRINE, f"{p} present in PATHWAY_DOCTRINE")
        prof = ol.PATHWAY_EXECUTION.get(p, {})
        check(bool(prof.get("stack")), f"{p} has a non-empty execution stack")
        check(bool(prof.get("tools")), f"{p} has non-empty execution tools")
    check(set(ol.PATHWAY_EXECUTION) == set(ol.PATHWAY_ORDER),
          "PATHWAY_EXECUTION keys exactly match PATHWAY_ORDER (no profile drift)")
    check(ol.PATHWAY_DOCTRINE["docs"]["skill"] == "doc-coauthoring",
          "docs pathway routes to doc-coauthoring, not a commit/ship skill")
    card = ol.karpathy_card("research", "proj", "")
    card["execution_stack"].append("__probe__")
    check("__probe__" not in ol.PATHWAY_EXECUTION["research"]["stack"],
          "karpathy_card returns a copy of execution_stack (module config not mutable via card)")


def test_itinerary_coverage_guarantee():
    """Coverage-by-construction: tier sizing, the close gate, proof-requires-a-real-
    artifact, and the work-cover guards — including the fixes from the Codex + GLM
    dual second-model review (fake-evidence P0, --add proof preservation, tier-downgrade
    retention, input validation)."""
    reset()
    proj = ROOT / "projects" / "itin-proj"
    proj.mkdir(parents=True, exist_ok=True)
    ev = ROOT / "real-evidence.txt"
    ev.write_text("artifact", encoding="utf-8")

    # Tier sizes the itinerary; a UI goal pulls in design.
    data, _ = run("work-start", ["--project", str(proj), "--goal", "production secure dashboard ui", "--tier", "production-secure"])
    secure_wid = data["work_id"]
    secure_itin = [e["pathway"] for e in data["records"][0]["itinerary"]]
    check({"govern", "security", "research", "design"} <= set(secure_itin) and len(secure_itin) == 11,
          "production-secure + UI goal seeds the full itinerary including design")

    data, _ = run("work-start", ["--project", str(proj), "--goal", "tiny backend slice only", "--tier", "demoable"])
    demo_wid = data["work_id"]
    demo_itin = [e["pathway"] for e in data["records"][0]["itinerary"]]
    check(demo_itin == ["govern", "implementation", "quality"], "demoable seeds exactly govern/implementation/quality")

    # The close gate refuses while pathways are still open.
    data, _ = run("work-close", ["--work-id", secure_wid])
    check(data.get("closed") is not True, "work-close is refused while itinerary pathways remain open")

    # P0 (Codex): a fake/nonexistent evidence path must NOT mark a pathway proved.
    run("work-log", ["--work-id", demo_wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ROOT / "nope.txt"), "--result", "pass"])
    data, _ = run("work-status", ["--work-id", demo_wid])
    st = {e["pathway"]: e["status"] for e in data["summary"]["itinerary"]}
    check(st["govern"] == "required", "fake/nonexistent evidence path does not mark a pathway proved")

    # A real on-disk artifact + a named verifier proves it (Gap A sufficiency bar).
    run("work-log", ["--work-id", demo_wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact", "--verified-by", "test verifier"])
    data, _ = run("work-status", ["--work-id", demo_wid])
    st = {e["pathway"]: e["status"] for e in data["summary"]["itinerary"]}
    check(st["govern"] == "proved", "a real on-disk artifact marks the pathway proved")

    # Fix (GLM): --add must not un-prove an already-proved pathway.
    run("work-cover", ["--work-id", demo_wid, "--pathway", "govern", "--add"])
    data, _ = run("work-status", ["--work-id", demo_wid])
    st = {e["pathway"]: e["status"] for e in data["summary"]["itinerary"]}
    check(st["govern"] == "proved", "work-cover --add preserves earned proof")

    # Fix (Codex): work-cover input guards.
    data, _ = run("work-cover", ["--work-id", demo_wid, "--pathway", "bogus", "--na", "--reason", "x"])
    check("work-cover-unknown-pathway" in ids(data), "work-cover rejects an unknown pathway name")
    data, _ = run("work-cover", ["--work-id", demo_wid, "--pathway", "quality", "--reason", "x"])
    check("work-cover-needs-one-action" in ids(data), "work-cover requires exactly one of --na/--add")
    data, _ = run("work-cover", ["--work-id", demo_wid, "--pathway", "quality", "--na"])
    check("work-cover-na-needs-reason" in ids(data), "work-cover --na requires a reason")

    # N/A the rest (with reasons) -> close succeeds at full coverage.
    for pathway in ("implementation", "quality"):
        run("work-cover", ["--work-id", demo_wid, "--pathway", pathway, "--na", "--reason", "n/a for this test"])
    data, _ = run("work-close", ["--work-id", demo_wid])
    check(data.get("closed") is True, "work-close succeeds once every pathway is proved or N/A")

    # Fix (Codex + GLM): a tier downgrade retains earned proof.
    run("work-log", ["--work-id", secure_wid, "--pathway", "security", "--kind", "verify", "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact", "--verified-by", "test verifier"])
    run("work-start", ["--project", str(proj), "--goal", "production secure dashboard ui", "--tier", "demoable"])
    data, _ = run("work-status", ["--work-id", secure_wid])
    st = {e["pathway"]: e["status"] for e in data["summary"]["itinerary"]}
    check(st.get("security") == "proved", "tier downgrade retains earned proof (security stays proved)")


def test_proof_requires_verifier_not_just_presence():
    """Gap A (world-class bar): a pathway is `proved` only by a NAMED verifier (a proof
    record) plus a real artifact. A bare evidence file is presence, not sufficiency."""
    reset()
    proj = ROOT / "projects" / "suff-proj"
    proj.mkdir(parents=True, exist_ok=True)
    ev = ROOT / "suff-evidence.txt"
    ev.write_text("artifact", encoding="utf-8")
    data, _ = run("work-start", ["--project", str(proj), "--goal", "sufficiency bar test", "--tier", "demoable"])
    wid = data["work_id"]

    # Bare evidence, NO named verifier -> records a run but does NOT prove the pathway.
    run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev), "--result", "pass"])
    data, _ = run("work-status", ["--work-id", wid])
    st = {e["pathway"]: e["status"] for e in data["summary"]["itinerary"]}
    check(st["govern"] == "required", "a bare evidence file with no named verifier does not prove a pathway")

    # Same artifact WITH a named verifier -> proves it.
    run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact", "--verified-by", "pytest -q (green)"])
    data, _ = run("work-status", ["--work-id", wid])
    st = {e["pathway"]: e["status"] for e in data["summary"]["itinerary"]}
    check(st["govern"] == "proved", "a real artifact plus a named verifier proves the pathway")


def test_recommendation_confidence_reflects_evidence():
    """Gap B: confidence reflects EVIDENCE strength, not only score separation. A pick
    backed by a real live signal is not 'low' even when a runner-up sits close; a pick
    carrying only scaffolding reasons (foundation gate / lowest-coverage) stays 'low' on
    a small gap."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("opl_under_test", CLI)
    opl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(opl)
    trust_pass = {"status": "pass"}

    # Small gap (3), but the top pick carries a real finding -> not low.
    ranked_evidence = [
        {"pathway": "security", "score": 5, "reasons": ["warn finding [local:x]: anon read exposed"]},
        {"pathway": "data", "score": 2, "reasons": []},
    ]
    lvl = opl.recommendation_confidence(ranked_evidence, True, trust_pass)["level"]
    check(lvl != "low", f"an evidence-backed pick with a small gap is not low (got {lvl})")

    # Same small gap, but only scaffolding reasons -> stays low (no false confidence).
    ranked_scaffold = [
        {"pathway": "research", "score": 5, "reasons": ["Foundation gate: no verified research dossier"]},
        {"pathway": "govern", "score": 2, "reasons": []},
    ]
    lvl2 = opl.recommendation_confidence(ranked_scaffold, True, trust_pass)["level"]
    check(lvl2 == "low", f"a pick with only scaffolding reasons stays low on a small gap (got {lvl2})")

    # Three real signals -> high (when nothing is missing).
    ranked_strong = [
        {"pathway": "security", "score": 12, "reasons": ["error finding a", "error finding b", "warn finding c"]},
        {"pathway": "data", "score": 10, "reasons": []},
    ]
    lvl3 = opl.recommendation_confidence(ranked_strong, True, trust_pass)["level"]
    check(lvl3 == "high", f"three real signals lift confidence to high (got {lvl3})")


def test_recommendation_follows_evidence_within_itinerary():
    """Gap B part 2: within the open-required itinerary, the next pick follows live
    evidence (a routed finding) rather than fixed canonical order — once foundations are
    covered. An error finding on a late-canonical pathway wins over canonical-first."""
    reset()
    proj = ROOT / "projects" / "evproj"
    (proj / ".planning").mkdir(parents=True, exist_ok=True)
    (proj / "package.json").write_text('{"name":"evproj"}\n', encoding="utf-8")
    ev = ROOT / "ev.txt"
    ev.write_text("artifact", encoding="utf-8")
    # An error finding routed to observability (a late-canonical pathway in the live tier).
    (proj / ".planning" / "findings.json").write_text(
        json.dumps([{"id": "obs-gap", "message": "critical journeys carry no traces",
                     "severity": "error", "pathway": "observability"}]),
        encoding="utf-8")
    data, _ = run("work-start", ["--project", str(proj), "--goal", "evidence ordering test", "--tier", "live"])
    wid = data["work_id"]
    # Cover the foundation (govern) so foundations no longer force the pick.
    run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--proof-type", "artifact", "--verified-by", "test"])
    rec, _ = run("pathway-next", ["--project", str(proj)])
    check(rec.get("recommended_pathway") == "observability",
          f"an error finding steers the next pick to observability over canonical-first data (got {rec.get('recommended_pathway')})")
    # Confidence must describe the RECOMMENDED pathway, not an out-of-itinerary foundation.
    conf = rec.get("recommendation_confidence", {})
    check("Foundation gate" not in conf.get("why_this", ""),
          f"confidence why_this reflects the recommended pathway, not a foundation (got: {conf.get('why_this','')[:50]})")
    check(conf.get("level") != "low",
          f"an error-finding-backed pick is not low confidence (got {conf.get('level')})")


def main():
    tests = [
        test_source_integrity_no_duplicate_module_level_names,
        test_test_runner_integrity_detects_unregistered_tests,
        test_intel_detection_and_clean,
        test_tools_detection_and_clean,
        test_portfolio_evidence_ai_boundary_agent_cards,
        test_all_smoke_outputs_parse_and_redact,
        test_improve_and_compare_control_loop,
        test_daily_work_envelope_and_pathway_cooperation,
        test_daily_work_stale_measurement_detection,
        test_work_close_extracts_learning_candidate,
        test_pathway_trust_report_and_pathway_next_metadata,
        test_pathway_next_recommendation_and_cohesion,
        test_pathway_run_creates_plan_and_preserves_project,
        test_portfolio_next_ranks_riskier_project_first,
        test_rule_map_names_enforced_and_prose_only_rules,
        test_cockpit_writes_one_page_operator_surface,
        test_pfos_cockpit_snapshot_export_is_browser_safe,
        test_ingest_review_closes_loop,
        test_ingest_review_schema_contract,
        test_ingest_review_malformed_and_empty,
        test_stale_review_gate,
        test_pathway_metric,
        test_proof_registry_and_proved_metric,
        test_project_scoping_no_substring_bleed,
        test_pathway_execution_profile_invariants,
        test_itinerary_coverage_guarantee,
        test_proof_requires_verifier_not_just_presence,
        test_recommendation_confidence_reflects_evidence,
        test_recommendation_follows_evidence_within_itinerary,
    ]
    missing = _unregistered_test_names(globals(), tests)
    check(not missing, f"all module-level test_* callables are registered in main() (missing: {missing})")
    if _failures:
        sys.stderr.write(f"\n{len(_failures)} failure(s), {_passes} pass(es)\n")
        return 1
    for test in tests:
        test()
    if _failures:
        sys.stderr.write(f"\n{len(_failures)} failure(s), {_passes} pass(es)\n")
        return 1
    print(f"{_passes}/{_passes} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
