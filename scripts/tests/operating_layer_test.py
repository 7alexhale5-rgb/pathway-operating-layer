#!/usr/bin/env python3
"""
operating_layer_test.py - self-test suite for operating-layer.py.

Stdlib only. Run: python3 ~/.claude/scripts/tests/operating_layer_test.py
Exit 0 = all pass; non-zero = failures.
"""
import ast
import atexit
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path


HERE = Path(__file__).resolve().parent
CLI = (HERE / ".." / "operating-layer.py").resolve()
_TEST_ROOT_PARENT = Path("/private/tmp").resolve()
ROOT = _TEST_ROOT_PARENT / f"operating-layer-test-{uuid.uuid4().hex}"
ROOT.mkdir(mode=0o700)


def _cleanup_owned_test_root(test_root=ROOT):
    if (test_root.parent == _TEST_ROOT_PARENT
            and test_root.name.startswith("operating-layer-test-")
            and test_root.exists()):
        shutil.rmtree(test_root)


atexit.register(_cleanup_owned_test_root)

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


def load_cli(tag):
    """Import operating-layer.py as a module for direct unit calls (the in-process pattern the
    autonomy tests use, so a pure function can be exercised without spawning a subprocess)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"opl_{tag}", CLI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _regularized_incomplete_beta(a, b, x):
    """Stdlib-only I_x(a,b) via the Numerical Recipes continued fraction. Used only by the Jeffreys
    cross-check below, so the suite stays dependency-free (no scipy)."""
    import math
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1 - x))

    def betacf(a, b, x):
        fpmin = 1e-300
        c = 1.0
        d = 1 - (a + b) * x / (a + 1)
        if abs(d) < fpmin:
            d = fpmin
        d = 1 / d
        h = d
        for m in range(1, 300):
            m2 = 2 * m
            aa = m * (b - m) * x / ((a - 1 + m2) * (a + m2))
            d = 1 + aa * d
            if abs(d) < fpmin:
                d = fpmin
            c = 1 + aa / c
            if abs(c) < fpmin:
                c = fpmin
            d = 1 / d
            h *= d * c
            aa = -(a + m) * (a + b + m) * x / ((a + m2) * (a + 1 + m2))
            d = 1 + aa * d
            if abs(d) < fpmin:
                d = fpmin
            c = 1 + aa / c
            if abs(c) < fpmin:
                c = fpmin
            d = 1 / d
            delta = d * c
            h *= delta
            if abs(delta - 1) < 1e-12:
                break
        return h

    if x < (a + 1) / (a + b + 2):
        return front * betacf(a, b, x) / a
    return 1 - front * betacf(b, a, 1 - x) / b


def _jeffreys_lower_bound(k, n, alpha=0.05):
    """Independent cross-check on wilson_lower_bound: the Jeffreys equal-tailed lower bound is the
    alpha/2 quantile of Beta(k+0.5, n-k+0.5). Different prior, same job — if the two methods agree
    on the unlock DECISION, the threshold is not an artifact of one formula. (Brown/Cai/DasGupta.)"""
    if n == 0 or k == 0:
        return 0.0
    a, b, target = k + 0.5, n - k + 0.5, alpha / 2
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if _regularized_incomplete_beta(a, b, mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def append_ndjson(path, rows):
    """Append raw rows to an ndjson file (seed helper: read_ndjson tolerates the format, and the
    next write_ndjson rewrites the whole list, so seeded rows persist)."""
    prefix = ""
    if path.exists():
        cur = path.read_text(encoding="utf-8")
        if cur and not cur.endswith("\n"):
            prefix = "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(prefix + "".join(json.dumps(r) + "\n" for r in rows))


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
    write("projects/agents/hermes/profiles/test-agent/manifest.json", '{"name":"Test Agent","rung":1}\n')

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


def test_agent_cards_reject_symlinked_candidates_and_markers():
    reset()
    write("outside-agent/manifest.json", '{"name":"Outside","marker":"EXTERNAL_AGENT_MARKER"}\n')
    profiles = ROOT / "projects" / "agents" / "hermes" / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / "linked-agent").symlink_to(ROOT / "outside-agent", target_is_directory=True)
    marker = profiles / "linked-marker"
    marker.mkdir()
    (marker / "manifest.json").symlink_to(ROOT / "outside-agent" / "manifest.json")
    write("projects/agents/hermes/profiles/real-agent/manifest.json", '{"name":"Real Agent","rung":1}\n')

    data, proc = run("agent-cards")
    check(proc.returncode == 0, "agent cards handles symlink fixture")
    cards = data.get("records", []) if isinstance(data, dict) else []
    systems = {card["system"] for card in cards}
    check(systems == {"real-agent"}, "agent cards rejects symlinked candidate and manifest marker")
    output = (ROOT / "out" / "operator-intelligence" / "agent-capability-cards.json").read_text(encoding="utf-8")
    check("EXTERNAL_AGENT_MARKER" not in output, "agent cards do not read symlinked external marker content")
    check(not (ROOT / "out" / "agent-capability-cards" / "linked-agent.md").exists(), "agent cards do not write a card for symlinked candidate")


def test_agent_cards_scope_excludes_helper_and_legacy_records():
    reset()
    write("projects/agents/tenants/README.md", "# Helper tenant folder\n")
    write("projects/agents/mcp-servers/README.md", "# Helper MCP folder\n")
    write("codex/automations/legacy-job/automation.toml", 'schedule = "daily"\n')
    write("projects/agents/hermes/profiles/atlas-ceo/manifest.json", '{"name":"Atlas CEO","rung":3}\n')

    data, proc = run("agent-cards")
    check(proc.returncode == 0, "agent cards scope fixture exits 0")
    cards = data.get("records", []) if isinstance(data, dict) else []
    systems = {card["system"] for card in cards}
    check(systems == {"atlas-ceo"}, "agent cards selects only the manifest-backed Hermes profile")
    finding = next((f for f in data.get("findings", []) if f["id"] == "agent-cards-incomplete-readiness"), {})
    evidence = {item.get("source") for item in finding.get("evidence", [])}
    check(evidence == {"atlas-ceo"}, "readiness finding excludes helper and legacy records")


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
    check(start.get("records", [{}])[0].get("itinerary"), "work-start defaults to a non-empty live itinerary")

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
    for pathway in ("govern", "data", "implementation", "quality", "observability", "release", "docs"):
        run("work-cover", ["--work-id", work_id, "--pathway", pathway, "--na", "--reason", "daily-work envelope test does not exercise itinerary proof"])

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
    start, _proc = run("work-start", ["--project", project_path, "--goal", "Close with learning", "--tier", "demoable"])
    work_id = start["work_id"]
    run("work-log", [
        "--work-id", work_id, "--pathway", "quality", "--kind", "verify",
        "--evidence", str(evidence), "--result", "pass", "--gate", "quality-gate",
        "--proof-type", "artifact", "--verified-by", "python3 quality-guard.py", "--verify-cmd", "printf verified",
    ])
    for pathway in ("govern", "implementation"):
        run("work-cover", ["--work-id", work_id, "--pathway", pathway, "--na", "--reason", "not relevant for this close-learning test"])
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

    # 1. No tracked work -> foundation-first: govern recommended, extension pathways still ranked.
    rec, proc = run("pathway-next", ["--project", project_path])
    check(proc.returncode == 0, "pathway-next exits 0")
    check(rec.get("recommended_pathway") == "govern", "untracked project recommends govern foundation gate")
    check(len(rec.get("ranked", [])) == 12 and any(r.get("pathway") == "field" for r in rec.get("ranked", [])),
          "pathway-next ranks the 11 core pathways plus field extension")
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
    run("work-log", ["--work-id", work_id, "--pathway", "govern", "--kind", "decision", "--evidence", str(evidence), "--result", "pass",
                     "--proof-type", "artifact", "--verify-cmd", "printf verified"])
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
    check("--proof-type artifact" in rec2.get("next_command", "") and "--recommendation-id" in rec2.get("next_command", "")
          and "--verify-cmd" in rec2.get("next_command", "") and "--verified-by" not in rec2.get("next_command", ""),
          "tracked next_command asks for executed proof metadata")

    # 3. Central-output-only + secret hygiene.
    after_project_files = sorted(p.relative_to(ROOT / "projects") for p in (ROOT / "projects").rglob("*") if p.is_file())
    check(after_project_files == before_project_files, "pathway-next does not modify project repo files")
    for file in (ROOT / "out").rglob("*"):
        if file.is_file() and file.suffix in {".md", ".html", ".json", ".ndjson"}:
            assert_no_secret_output(file.read_text(errors="ignore"), f"{file.name} redacts secrets in pathway-next outputs")


def test_pathway_next_scores_only_selected_active_work():
    """Outcome scoring follows the selected work ID; portfolio reporting still aggregates.

    This fixture reproduces the live contamination shape: the newest work has no stale or
    missing-evidence measurements, while two older active outcomes own 17 stale and two missing
    records. Direct compute comparisons exclude persistence-only IDs and timestamps.
    """
    fixture_path = (
        HERE.parent.parent
        / ".planning/2026-07-17-selected-work-pathway-next-scoring/data/SELECTED_WORK_SCORING_LEDGER_FIXTURE.json"
    )
    fixture = read_json(fixture_path)

    def seed_fixture(mutator=None):
        reset()
        fixture_root = str(Path(fixture["project"]["path"]).parents[1])
        data = json.loads(json.dumps(fixture).replace(fixture_root, str(ROOT)))
        if mutator:
            mutator(data)
        project = ROOT / "projects" / "fixture-project"
        write("projects/fixture-project/README.md", "# Fixture project\n")
        write("projects/fixture-project/.planning/STATE.md", "# Current\n")
        write("projects/fixture-project/.planning/finding.json", "{}\n")
        write("projects/fixture-project/.planning/selected-docs.md", "# Selected docs\n")
        write("projects/fixture-project/.planning/older-quality.md", "# Older quality\n")
        ledger_files = {
            "work_items": "work-items.ndjson",
            "pathway_runs": "pathway-runs.ndjson",
            "pathway_measurements": "pathway-measurements.ndjson",
            "controls": "controls.ndjson",
            "proofs": "proofs.ndjson",
            "pathway_carry_forward": "pathway-carry-forward.ndjson",
            "findings": "findings.ndjson",
            "learning_candidates": "learning-candidates.ndjson",
        }
        for key, filename in ledger_files.items():
            write(
                f"out/operator-intelligence/{filename}",
                "".join(json.dumps(row) + "\n" for row in data.get(key, [])),
            )
        write("out/operator-intelligence/pathway-trust.json", json.dumps({
            "status": "pass", "summary": "fixture trust passes", "generated_at": fixture["clock"],
        }))
        return project, data

    opl = load_cli("selected_work_scoring")

    def compute(project, work_id=""):
        argv = [
            "pathway-next",
            "--project", str(project),
            "--claude-home", str(ROOT / "claude"),
            "--codex-home", str(ROOT / "codex"),
            "--projects-root", str(ROOT / "projects"),
            "--output-root", str(ROOT / "out"),
            "--since-days", "3650",
        ]
        if work_id:
            argv.extend(["--work-id", work_id])
        args = opl.build_parser().parse_args(argv)
        return opl.compute_pathway_next(args, opl.Paths(args))

    def pathway_score(state, pathway):
        return next(row["score"] for row in state["ranked"] if row["pathway"] == pathway)

    def selected_projection(state):
        keys = (
            "work_id", "ranked", "recommended_pathway", "recommendation_confidence",
            "suggested_autonomy_tier", "autonomy_rationale", "ready_to_close", "contract_tier",
            "latest_carry_forward", "carry_forward_effect", "outcome_profile", "risk_overlays",
            "itinerary", "itinerary_coverage",
        )
        return {key: state[key] for key in keys}

    project, _ = seed_fixture()
    base = compute(project)
    parameters = list(opl.score_pathways.__code__.co_varnames[:opl.score_pathways.__code__.co_argcount])
    check(parameters[4] == "active_summary",
          "selected scoring: score_pathways accepts one active_summary, not an aggregate list")
    check(base.get("work_id") == "W-selected", "selected scoring: newest active work is selected")
    check(base.get("contract_tier") == "production-secure"
          and [row["id"] for row in base.get("risk_overlays", [])] == ["selected-human-gate"],
          "selected scoring: tier and risk overlays come from the selected work only")
    check(pathway_score(base, "research") == 100 and pathway_score(base, "govern") == 80,
          "selected scoring: older foundation coverage does not satisfy selected foundations")
    selected_statuses = {row["pathway"]: row["status"] for row in base["itinerary"]}
    check({"govern", "research"}.issubset(base["itinerary_coverage"]["open"])
          and selected_statuses["govern"] == "required" and selected_statuses["research"] == "required",
          "selected scoring: older foundations do not satisfy the selected itinerary")
    check(pathway_score(base, "quality") == 4,
          "selected scoring: older 17 stale and two missing-evidence rows add zero to quality")
    check(pathway_score(base, "data") == 4,
          "selected scoring: an older data control adds zero to selected data score")
    check(pathway_score(base, "security") == 94 and pathway_score(base, "release") == 54,
          "selected scoring: selected control adds exactly 50 to each target")
    security_reasons = next(row["reasons"] for row in base["ranked"] if row["pathway"] == "security")
    release_reasons = next(row["reasons"] for row in base["ranked"] if row["pathway"] == "release")
    check(any("C-selected-security" in reason for reason in security_reasons)
          and any("C-selected-security" in reason for reason in release_reasons),
          "selected scoring: selected control reason is retained on both target pathways")
    check(any("sec-current-project" in reason for reason in security_reasons),
          "selected scoring: current project finding retains its score and reason")
    check(base.get("latest_carry_forward", {}).get("carry_forward_id") == "CF-selected"
          and "contradictory older baton" not in base.get("carry_forward_effect", ""),
          "selected scoring: a chronologically newer older-work baton cannot replace the selected baton")
    check(base.get("karpathy_card", {}).get("goal") == "Prove selected-work pathway scoring",
          "selected scoring: the recommendation card uses the selected work goal")

    explicitly_older = compute(project, "W-older-nine")
    older_quality_reasons = next(
        row["reasons"] for row in explicitly_older["ranked"] if row["pathway"] == "quality"
    )
    check(explicitly_older.get("work_id") == "W-older-nine"
          and explicitly_older.get("contract_tier") == "live"
          and [row["id"] for row in explicitly_older.get("risk_overlays", [])] == ["older-rollback"],
          "selected scoring: --work-id selects an older active outcome and its contract")
    check(any("9 stale measurement" in reason for reason in older_quality_reasons)
          and not any("17 stale measurement" in reason for reason in older_quality_reasons),
          "selected scoring: explicit selection sees its nine stale rows, never the other eight")
    check(explicitly_older.get("latest_carry_forward", {}).get("carry_forward_id") == "CF-older"
          and explicitly_older.get("karpathy_card", {}).get("goal") == "Older outcome with nine stale records",
          "selected scoring: explicit selection scopes carry-forward and goal to the same work ID")

    def move_explicit_work_to_nested_checkout(data):
        older = next(row for row in data["work_items"] if row["work_id"] == "W-older-nine")
        older["project"] = str(ROOT / "projects" / "fixture-project" / "nested-app")
        older["project_name"] = "nested-app"

    project, _ = seed_fixture(move_explicit_work_to_nested_checkout)
    nested = compute(project, "W-older-nine")
    check(nested.get("work_id") == "W-older-nine"
          and nested.get("latest_carry_forward", {}).get("carry_forward_id") == "CF-older",
          "selected scoring: explicit work may belong to a nested checkout under the project root")

    def selected_requires_quality(data):
        selected = next(row for row in data["work_items"] if row["work_id"] == "W-selected")
        selected["outcome_profile"]["required_pathways"] = ["quality"]

    project, _ = seed_fixture(selected_requires_quality)
    required_quality = compute(project)
    required_quality_reasons = next(
        row["reasons"] for row in required_quality["ranked"] if row["pathway"] == "quality"
    )
    check(pathway_score(required_quality, "quality") == pathway_score(base, "quality") + 12
          and any("requires quality" in reason for reason in required_quality_reasons),
          "selected scoring: older proved coverage does not suppress a selected profile requirement")

    def older_quality_na(data):
        selected_requires_quality(data)
        older = next(row for row in data["work_items"] if row["work_id"] == "W-older-eight")
        next(row for row in older["itinerary"] if row["pathway"] == "quality")["status"] = "na"

    project, _ = seed_fixture(older_quality_na)
    required_quality_with_older_na = compute(project)
    check(pathway_score(required_quality_with_older_na, "quality") == pathway_score(required_quality, "quality"),
          "selected scoring: older N/A coverage does not suppress a selected profile requirement")

    def selected_quality_proved(data):
        selected_requires_quality(data)
        selected = next(row for row in data["work_items"] if row["work_id"] == "W-selected")
        selected["itinerary"].append({
            "pathway": "quality", "status": "proved", "proved_by_run": "R-selected-quality", "reason": "",
        })

    project, _ = seed_fixture(selected_quality_proved)
    covered_quality = compute(project)
    covered_quality_reasons = next(
        row["reasons"] for row in covered_quality["ranked"] if row["pathway"] == "quality"
    )
    check(pathway_score(covered_quality, "quality") == pathway_score(required_quality, "quality") - 12
          and not any("requires quality" in reason for reason in covered_quality_reasons),
          "selected scoring: selected proved coverage suppresses its own profile requirement")

    def without_selected_control(data):
        data["controls"] = [row for row in data["controls"] if row["work_id"] != "W-selected"]

    project, _ = seed_fixture(without_selected_control)
    no_control = compute(project)
    check(pathway_score(no_control, "security") == pathway_score(base, "security") - 50
          and pathway_score(no_control, "release") == pathway_score(base, "release") - 50,
          "selected scoring: removing the selected control removes exactly 50 per target")

    def move_two_stale(data):
        wanted = set(data["mutations"]["move_two_stale_to_selected"]["measurement_ids"])
        for row in data["pathway_measurements"]:
            if row["measurement_id"] in wanted:
                row["work_id"] = "W-selected"

    project, _ = seed_fixture(move_two_stale)
    selected_stale = compute(project)
    stale_reasons = next(row["reasons"] for row in selected_stale["ranked"] if row["pathway"] == "quality")
    check(pathway_score(selected_stale, "quality") == pathway_score(base, "quality") + 10
          and any("2 stale measurement" in reason for reason in stale_reasons),
          "selected scoring: two selected stale rows add exactly 10 and name the count")

    def move_two_missing(data):
        wanted = set(data["mutations"]["move_two_missing_to_selected"]["measurement_ids"])
        for row in data["pathway_measurements"]:
            if row["measurement_id"] in wanted:
                row["work_id"] = "W-selected"

    project, _ = seed_fixture(move_two_missing)
    selected_missing = compute(project)
    missing_reasons = next(row["reasons"] for row in selected_missing["ranked"] if row["pathway"] == "quality")
    check(pathway_score(selected_missing, "quality") == pathway_score(base, "quality") + 8
          and any("2 measurement(s) lack evidence" in reason for reason in missing_reasons),
          "selected scoring: two selected missing-evidence rows add exactly 8 and name the count")

    def remove_all_older_signals(data):
        data["pathway_runs"] = [row for row in data["pathway_runs"] if row["work_id"] == "W-selected"]
        data["pathway_measurements"] = [
            row for row in data["pathway_measurements"] if row["work_id"] == "W-selected"
        ]
        data["controls"] = [row for row in data["controls"] if row["work_id"] == "W-selected"]
        data["pathway_carry_forward"] = [
            row for row in data["pathway_carry_forward"] if row["work_id"] == "W-selected"
        ]

    project, _ = seed_fixture(remove_all_older_signals)
    without_older = compute(project)
    check(selected_projection(without_older) == selected_projection(base),
          "selected scoring: changing only non-selected work leaves normalized output invariant")

    def add_project_learning(data):
        data["learning_candidates"] = [{
            "learning_id": "L-closed-data",
            "work_id": "W-closed",
            "project": "fixture-project",
            "project_path": str(ROOT / "projects" / "fixture-project"),
            "pathways_seen": ["data"],
        }]

    project, _ = seed_fixture(add_project_learning)
    learned = compute(project)
    check(pathway_score(learned, "data") == pathway_score(base, "data") - 3,
          "selected scoring: one closed project outcome preserves the exact bounded learning dampener")

    def add_learning_without_older(data):
        add_project_learning(data)
        remove_all_older_signals(data)

    project, _ = seed_fixture(add_learning_without_older)
    learned_without_older = compute(project)
    check(selected_projection(learned_without_older) == selected_projection(learned),
          "selected scoring: project learning remains identical when older active signals change")

    project, _ = seed_fixture()
    persisted, persisted_proc = run(
        "pathway-next", ["--project", str(project), "--work-id", "W-older-nine"]
    )
    recommendation_rows = [
        json.loads(line) for line in
        (ROOT / "out/operator-intelligence/pathway-recommendations.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    check(persisted_proc.returncode == 0 and len(recommendation_rows) == 1
          and recommendation_rows[0]["recommendation_id"] == persisted["recommendation_id"]
          and recommendation_rows[0]["work_id"] == "W-older-nine"
          and "W-older-nine" in persisted.get("next_command", "")
          and persisted["recommendation_id"] in persisted.get("next_command", ""),
          "selected scoring: explicit selection persists one recommendation and retains selected identity")

    def add_invalid_selection_rows(data):
        data["work_items"].extend([
            {
                "work_id": "W-closed", "project": str(ROOT / "projects" / "fixture-project"),
                "project_name": "fixture-project", "goal": "Closed outcome", "status": "closed",
                "updated_at": "2026-07-18T00:00:04Z", "itinerary": [],
            },
            {
                "work_id": "W-other-project", "project": str(ROOT / "projects" / "other-project"),
                "project_name": "fixture-project", "goal": "Same-name sibling outcome", "status": "active",
                "updated_at": "2026-07-18T00:00:05Z", "itinerary": [],
            },
        ])

    project, _ = seed_fixture(add_invalid_selection_rows)
    recommendations_path = ROOT / "out/operator-intelligence/pathway-recommendations.ndjson"
    for invalid_id in ("W-missing", "W-closed", "W-other-project"):
        invalid, _ = run("pathway-next", ["--project", str(project), "--work-id", invalid_id])
        check({row["id"] for row in invalid.get("findings", [])} == {"pathway-next-work-id-not-active"}
              and invalid.get("records") == [] and not recommendations_path.exists(),
              f"selected scoring: invalid selection {invalid_id} fails closed without a recommendation row")

    project, _ = seed_fixture()
    older_status, _ = run("work-status", ["--work-id", "W-older-nine"])
    portfolio, _ = run("portfolio-next")
    portfolio_row = next(row for row in portfolio["records"] if row["project"] == "fixture-project")
    check(older_status["summary"]["work_item"]["work_id"] == "W-older-nine"
          and len(older_status["summary"]["stale_measurements"]) == 9
          and len(older_status["summary"]["missing_evidence"]) == 1
          and [row["control_id"] for row in older_status["summary"]["open_controls"]] == ["C-older-data"],
          "selected scoring: older work state remains visible in work-status")
    check(portfolio_row["active_work"] == 3 and portfolio_row["stale_measurements"] == 17
          and portfolio_row["open_controls"] == 2,
          "selected scoring: portfolio-next still aggregates all active work")

    empty = ROOT / "projects" / "empty-project"
    write("projects/empty-project/README.md", "# Empty project\n")
    untracked, untracked_proc = run("pathway-next", ["--project", str(empty)])
    untracked_scores = {row["pathway"]: row["score"] for row in untracked["ranked"]}
    check(untracked_proc.returncode == 0 and untracked.get("work_id") is None
          and untracked_scores["research"] == 8 and untracked_scores["govern"] == 8
          and "work-start" in untracked.get("next_command", ""),
          "selected scoring: no-active behavior keeps untracked nudges and work-start routing")


def test_selected_work_scoring_regression_kills_aggregate_mutant():
    """The registered quality gate must reject the exact pre-fix aggregate-scoring seam."""
    import contextlib
    import io
    import runpy
    import tempfile

    replacements = (
        (
            "def score_pathways(paths, project_path, project_name, scoped_findings, active_summary,\n",
            "def score_pathways(paths, project_path, project_name, scoped_findings, work_summaries,\n",
        ),
        (
            """    # Outcome-state signals belong only to the selected active work item. Project findings and
    # closed-outcome learning remain broader inputs below; portfolio aggregation has its own path.
    summary = active_summary or {}
    seen = set(summary.get("pathway_coverage", {}).get("seen", []))
    covered_pathways = set(summary.get("pathway_coverage", {}).get("proved", []))
    covered_pathways.update(
        e.get("pathway") for e in summary.get("itinerary", [])
        if e.get("status") in ("proved", "na")
    )
    open_controls = list(summary.get("open_controls", []))
    stale_count = len(summary.get("stale_measurements", []))
    missing_evidence_count = len(summary.get("missing_evidence", []))
""",
            """    # Mutant: restore the pre-fix aggregation across every active outcome.
    seen = set()
    covered_pathways = set()
    open_controls = []
    stale_count = 0
    missing_evidence_count = 0
    for summary in work_summaries:
        seen.update(summary.get("pathway_coverage", {}).get("seen", []))
        covered_pathways.update(summary.get("pathway_coverage", {}).get("proved", []))
        covered_pathways.update(
            e.get("pathway") for e in summary.get("itinerary", [])
            if e.get("status") in ("proved", "na")
        )
        open_controls.extend(summary.get("open_controls", []))
        stale_count += len(summary.get("stale_measurements", []))
        missing_evidence_count += len(summary.get("missing_evidence", []))
""",
        ),
        (
            "    has_active_work = active_summary is not None\n",
            "    has_active_work = bool(work_summaries)\n",
        ),
        (
            "    active_summary = work_status_summary(paths, work_id) if work_id else None\n",
            "    active_summary = work_status_summary(paths, work_id) if work_id else None\n"
            "    work_summaries = [work_status_summary(paths, item.get(\"work_id\")) for item in work_items]\n",
        ),
        (
            "        paths, project_path, project_name, scoped_findings, active_summary,\n",
            "        paths, project_path, project_name, scoped_findings, work_summaries,\n",
        ),
    )
    required_failures = {
        "selected scoring: score_pathways accepts one active_summary, not an aggregate list",
        "selected scoring: older foundation coverage does not satisfy selected foundations",
        "selected scoring: older 17 stale and two missing-evidence rows add zero to quality",
        "selected scoring: an older data control adds zero to selected data score",
        "selected scoring: two selected stale rows add exactly 10 and name the count",
        "selected scoring: two selected missing-evidence rows add exactly 8 and name the count",
        "selected scoring: changing only non-selected work leaves normalized output invariant",
    }

    with tempfile.TemporaryDirectory(prefix="selected-work-scoring-mutant-") as temp_dir:
        mutant_root = Path(temp_dir)
        mutant_scripts = mutant_root / "repo/scripts"
        mutant_tests_dir = mutant_scripts / "tests"
        mutant_fixture_dir = mutant_root / "repo/.planning/2026-07-17-selected-work-pathway-next-scoring/data"
        mutant_tests_dir.mkdir(parents=True)
        mutant_fixture_dir.mkdir(parents=True)
        mutant_cli = mutant_scripts / "operating-layer.py"
        mutant_tests = mutant_tests_dir / "operating_layer_test.py"
        shutil.copy2(Path(__file__).resolve(), mutant_tests)
        shutil.copy2(
            HERE.parent.parent
            / ".planning/2026-07-17-selected-work-pathway-next-scoring/data/SELECTED_WORK_SCORING_LEDGER_FIXTURE.json",
            mutant_fixture_dir / "SELECTED_WORK_SCORING_LEDGER_FIXTURE.json",
        )

        mutant_source = CLI.read_text(encoding="utf-8")
        replacement_counts = []
        for original, replacement in replacements:
            replacement_counts.append(mutant_source.count(original))
            mutant_source = mutant_source.replace(original, replacement)
        mutant_cli.write_text(mutant_source, encoding="utf-8")

        namespace = runpy.run_path(str(mutant_tests), run_name="selected_work_aggregate_mutant")
        mutant_test = namespace["test_pathway_next_scores_only_selected_active_work"]
        mutant_globals = mutant_test.__globals__
        mutant_globals["ROOT"] = mutant_root / "runtime"
        passes_before = mutant_globals["_passes"]
        failures_before = len(mutant_globals["_failures"])
        with contextlib.redirect_stderr(io.StringIO()):
            mutant_test()
        failures = set(mutant_globals["_failures"][failures_before:])
        executed = mutant_globals["_passes"] - passes_before + len(failures)

    check(replacement_counts == [1] * len(replacements),
          f"selected scoring quality: aggregate mutant rewrites the five exact scoring seams (got {replacement_counts})")
    check(executed == 32,
          f"selected scoring quality: aggregate mutant executes the complete 32-assertion corpus (got {executed})")
    check(required_failures.issubset(failures),
          "selected scoring quality: regression corpus kills the aggregate mutant on all seven original contamination paths")


def test_pathway_carry_forward_logged_and_used_by_next():
    """Semantic continuity: a completed pathway leaves a structured carry-forward baton, and the next
    determine turn exposes it in JSON and the operator report instead of treating the proof as mere
    coverage."""
    reset()
    proj = ROOT / "projects" / "carryproj"
    proj.mkdir(parents=True, exist_ok=True)
    evidence = write("out/operator-artifacts/research-carry.md", """# Research Proof

## Summary
Research says proof/closeout safety is the first implementation slice.

## What Changed
- Govern must pin the P0 proof safety metric.

## More Relevant
- no-op verifier rejection
- empty-itinerary closeout

## Less Relevant
- full RAG framework adoption

## Next Pathway Must Use
- Govern must use this research before setting the metric.

## Do Not Do Yet
- Do not add field before proof safety is stable.

## Open Decisions
- Whether field starts as an overlay or pathway.
""")
    start, _ = run("work-start", ["--project", str(proj), "--goal", "ship full-cycle pathway memory", "--tier", "production-secure"])
    wid = start["work_id"]
    logged, _ = run("work-log", ["--work-id", wid, "--pathway", "research", "--kind", "verify",
                                 "--evidence", str(evidence), "--result", "pass", "--proof-type", "artifact",
                                 "--verify-cmd", "printf verified"])
    cf = logged.get("carry_forward", {})
    check(cf.get("pathway") == "research" and cf.get("artifact_sha256"),
          f"work-log writes a carry-forward record for verified pathway proof (got {cf})")
    carry_path = ROOT / "out" / "operator-intelligence" / "pathway-carry-forward.ndjson"
    check(carry_path.exists() and "Govern must pin the P0 proof safety metric" in carry_path.read_text(encoding="utf-8"),
          "carry-forward ledger persists the semantic baton")

    rec, _ = run("pathway-next", ["--project", str(proj)])
    latest = rec.get("latest_carry_forward", {})
    check(rec.get("recommended_pathway") == "govern",
          f"after research proof, govern is the next open foundation (got {rec.get('recommended_pathway')})")
    check(latest.get("carry_forward_id") == cf.get("carry_forward_id"),
          "pathway-next JSON exposes the latest carry-forward for the active work")
    check("P0 proof safety" in rec.get("carry_forward_effect", ""),
          "pathway-next explains how prior pathway output changed the recommendation")
    report_text = Path(rec["report"]).read_text(encoding="utf-8")
    check("## What Previous Work Changed" in report_text and "full RAG framework adoption" in report_text,
          "pathway-next report renders carry-forward deltas and deferred concerns")

    # A non-conditional baton directive is authoritative once foundations are covered, even when
    # generic production overlays would otherwise score release/security higher.
    opl = load_cli("carrydirective")
    directive = {"next_pathway_must_use": [
        "Implementation must close the code defects without production mutation.",
        "If the next recommendation is design, preserve the verifier boundary.",
    ]}
    check(opl.carry_forward_next_pathways(directive) == ["implementation"],
          "carry-forward recognizes a direct implementation-must-close baton without treating a conditional as current")

    # Integration: close the remaining foundation and record a release baton whose explicit next
    # move is implementation. Production profile/rollback scoring is intentionally stronger than
    # the normal baton bump, so only the continuity override makes the authoritative handoff win.
    run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify",
                     "--evidence", str(evidence), "--result", "pass", "--proof-type", "artifact",
                     "--verify-cmd", "printf verified"])
    release_evidence = write("out/operator-artifacts/release-carry.md", """# Release Verification

## Summary
Release preflight is complete and rollback is verified; implementation is the next slice.

## What Changed
- Pinned the rollback sequence.

## More Relevant
- Close correctness defects.

## Less Relevant
- Production mutation.

## Next Pathway Must Use
- Implementation must close the code defects before another release pass.

## Do Not Do Yet
- Do not deploy.

## Open Decisions
- Choose the deployment window.

## Active Risk Overlays
- rollback
""")
    run("work-log", ["--work-id", wid, "--pathway", "release", "--kind", "verify",
                     "--evidence", str(release_evidence), "--result", "pass", "--proof-type", "artifact",
                     "--verify-cmd", "printf verified"])
    rec2, _ = run("pathway-next", ["--project", str(proj)])
    check(rec2.get("recommended_pathway") == "implementation",
          f"an explicit open implementation baton outranks generic release/security scoring (got {rec2.get('recommended_pathway')})")


def test_carry_forward_deferrals_do_not_trigger_false_risk_overlays():
    """Security continuity must not turn guardrails into active scope.

    A carry-forward baton often says what NOT to do yet ("don't add A2A/production mutation/tenant
    auth until separately proved"). Those words are important constraints, but they are not evidence
    that A2A, production mutation, or tenant auth are currently in scope. The recommender must not
    loop back to an already proved security pathway solely because deferred-risk text mentioned it.
    """
    reset()
    proj = ROOT / "projects" / "deferproj"
    (proj / ".planning").mkdir(parents=True, exist_ok=True)
    (proj / ".planning" / "STATE.md").write_text("# State\nCurrent proof-ledger fixture.\n", encoding="utf-8")
    ev = write("out/operator-artifacts/basic-proof.md", "basic verified artifact\n")
    security_ev = write("out/operator-artifacts/security-deferral.md", """# Security Deferral Proof

## Summary
Security proof completed for the local proof ledger.

## What Changed
- The operator-local verifier boundary is proved for this slice.

## More Relevant
- Preserve hash-bound verifier receipts.

## Less Relevant
- Hosted web auth, tenant RLS, client portal authorization, and production rollout are not part of this local CLI slice.

## Next Pathway Must Use
- The next pathway should use this proof when deciding whether `security` is still open.
- If the next recommendation is design or techdebt, preserve the verifier boundary.
- Any future remote-agent/A2A execution work must re-open `security`.

## Do Not Do Yet
- Do not add MCP write tools, A2A handoffs, external sends, or production mutation around proof logging.
- Do not treat `--verify-cmd` as safe for untrusted remote agents.

## Open Decisions
- Decide later whether remote agents may submit verifier commands.
""")
    start, _ = run("work-start", ["--project", str(proj), "--goal", "ship proof ledger continuity", "--tier", "demoable"])
    wid = start["work_id"]
    for pathway in ("govern", "implementation", "quality"):
        run("work-log", ["--work-id", wid, "--pathway", pathway, "--kind", "verify",
                         "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact",
                         "--verify-cmd", "printf verified"])
    run("work-log", ["--work-id", wid, "--pathway", "security", "--kind", "verify",
                     "--evidence", str(security_ev), "--result", "pass", "--proof-type", "artifact",
                     "--verify-cmd", "printf verified"])

    rec, _ = run("pathway-next", ["--project", str(proj)])
    overlay_ids = {o.get("id") for o in rec.get("risk_overlays", [])}
    false_overlays = {"tenant-authz", "production-mutation", "rollback", "llm-agent-eval", "human-gate"}
    check(not (overlay_ids & false_overlays),
          f"deferred carry-forward risks do not become active overlays (got {sorted(overlay_ids)})")
    check(rec.get("latest_carry_forward", {}).get("pathway") == "security",
          "security deferral baton is the latest carry-forward under test")
    check(rec.get("recommended_pathway") != "security",
          f"already proved security does not loop solely from deferral text (got {rec.get('recommended_pathway')})")
    security_rank = next((r for r in rec.get("ranked", []) if r.get("pathway") == "security"), {})
    check(not any("Risk overlay" in reason or "Carry-forward" in reason for reason in security_rank.get("reasons", [])),
          f"security rank has no false overlay/carry-forward bump (got {security_rank.get('reasons')})")


def test_carry_forward_validation_requires_full_contract():
    opl = load_cli("carrycontract")
    valid = {
        "carry_forward_id": "CF-test",
        "work_id": "W-test",
        "project": "proj",
        "pathway": "research",
        "source_artifact": "/tmp/artifact.md",
        "summary": "summary",
        "what_changed": [],
        "more_relevant": [],
        "less_relevant": [],
        "next_pathway_must_use": [],
        "do_not_do_yet": [],
        "open_decisions": [],
        "active_risk_overlays": [],
        "artifact_sha256": "a" * 64,
        "created_at": "2026-07-05T00:00:00Z",
    }
    check(opl.carry_forward_is_valid(valid) is True, "complete carry-forward contract validates")
    missing = dict(valid)
    missing.pop("next_pathway_must_use")
    check(opl.carry_forward_is_valid(missing) is False, "missing carry-forward fields are invalid")
    wrong_type = dict(valid)
    wrong_type["what_changed"] = "not a list"
    check(opl.carry_forward_is_valid(wrong_type) is False, "carry-forward list fields must be structured lists")


def test_outcome_profiles_risk_overlays_and_field_gate():
    reset()
    proj = ROOT / "projects" / "fieldproj"
    proj.mkdir(parents=True, exist_ok=True)
    ev = write("out/operator-artifacts/field-proof.md", "review packet proof\n")

    start, _ = run("work-start", [
        "--project", str(proj),
        "--goal", "Build client feedback review packet for customer approval",
        "--tier", "demoable",
    ])
    item = start["records"][0]
    pathways = [e["pathway"] for e in item.get("itinerary", [])]
    overlays = {o["id"] for o in item.get("risk_overlays", [])}
    check(item.get("outcome_profile", {}).get("id") == "customer-field-review",
          "client feedback work is classified as customer-field-review")
    check("field" in pathways and "human-gate" in overlays,
          "customer-field-review adds the field pathway through the human-gate overlay")

    wid = start["work_id"]
    for pathway in ("govern", "implementation", "quality"):
        run("work-log", ["--work-id", wid, "--pathway", pathway, "--kind", "verify",
                         "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact",
                         "--verify-cmd", "printf verified"])
    close, _ = run("work-close", ["--work-id", wid])
    open_paths = close.get("records", [{}])[0].get("itinerary_coverage", {}).get("open", [])
    check(close.get("closed") is not True and open_paths == ["field"],
          f"field blocks closeout until real customer/operator validation is proved (open: {open_paths})")
    rec, _ = run("pathway-next", ["--project", str(proj)])
    report_text = Path(rec["report"]).read_text(encoding="utf-8")
    check(rec.get("recommended_pathway") == "field",
          f"pathway-next recommends field when only customer validation remains (got {rec.get('recommended_pathway')})")
    check("## Outcome Profile And Risk Overlays" in report_text and "human-gate" in report_text,
          "pathway-next report renders outcome profile and risk overlays")

    run("work-log", ["--work-id", wid, "--pathway", "field", "--kind", "verify",
                     "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact",
                     "--verify-cmd", "printf verified"])
    closed, _ = run("work-close", ["--work-id", wid])
    check(closed.get("closed") is True, "field proof lets the outcome close after all gates clear")

    prod, _ = run("work-start", [
        "--project", str(proj),
        "--goal", "Run prod database migration for tenant RLS",
        "--tier", "demoable",
    ])
    prod_item = prod["records"][0]
    prod_paths = {e["pathway"] for e in prod_item.get("itinerary", [])}
    prod_overlays = {o["id"] for o in prod_item.get("risk_overlays", [])}
    check({"data", "security", "release"}.issubset(prod_paths),
          f"production mutation overlays auto-insert data/security/release (got {sorted(prod_paths)})")
    check({"tenant-authz", "production-mutation", "rollback"}.issubset(prod_overlays),
          f"prod tenant migration detects the high-risk overlays (got {sorted(prod_overlays)})")


def test_closeout_router_ready_to_close_and_work_close_receipts():
    """Regression: pathway-next must say ready-to-close when the itinerary is fully
    covered (not recommend another work-log), and work-close must return non-null
    work_id / Markdown report / HTML report fields."""
    reset()
    proj = ROOT / "projects" / "closerproj"
    proj.mkdir(parents=True, exist_ok=True)
    ev = write("out/operator-artifacts/closer-proof.md", "closeout proof\n")

    start, _ = run("work-start", [
        "--project", str(proj),
        "--goal", "Ship the closeout router regression fixture",
        "--tier", "demoable",
    ])
    wid = start["work_id"]
    required = [e["pathway"] for e in start["records"][0].get("itinerary", [])
                if e.get("status", "required") == "required"]
    check(len(required) >= 2, f"fixture itinerary has at least two required pathways (got {required})")

    # Cover all but the last required pathway: not ready to close yet.
    for pathway in required[:-1]:
        run("work-log", ["--work-id", wid, "--pathway", pathway, "--kind", "verify",
                         "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact",
                         "--verify-cmd", "printf verified"])
    partial, _ = run("pathway-next", ["--project", str(proj)])
    check(partial.get("ready_to_close") is False,
          "pathway-next is not ready-to-close while a required pathway is still owed")
    check("work-log" in partial.get("next_command", ""),
          "pathway-next still routes to work-log while coverage is open")

    # Cover the last pathway: explicit ready-to-close result routing to work-close.
    run("work-log", ["--work-id", wid, "--pathway", required[-1], "--kind", "verify",
                     "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact",
                     "--verify-cmd", "printf verified"])

    # Covered itinerary is NOT sufficient: an open control keeps the outcome blocked, so
    # pathway-next must not claim ready-to-close (it would route to a refusing work-close).
    blocker, _ = run("work-log", [
        "--work-id", wid, "--pathway", required[0], "--kind", "control", "--evidence", str(ev),
        "--control-risk", "closeout-blocker", "--target-pathways", required[0],
    ])
    control_id = next(r["control_id"] for r in blocker.get("records", []) if r.get("control_id"))
    blocked, _ = run("pathway-next", ["--project", str(proj)])
    check(blocked.get("ready_to_close") is False,
          "open control blocks ready-to-close even with full itinerary coverage")
    run("work-log", ["--work-id", wid, "--pathway", required[0], "--kind", "control-resolution",
                     "--evidence", str(ev), "--control-id", control_id,
                     "--control-status", "resolved", "--result", "pass"])

    recs_before = len((ROOT / "out" / "operator-intelligence" / "pathway-recommendations.ndjson").read_text(encoding="utf-8").splitlines()) if (ROOT / "out" / "operator-intelligence" / "pathway-recommendations.ndjson").exists() else 0
    ready, ready_proc = run("pathway-next", ["--project", str(proj)])
    check(ready_proc.returncode == 0, "pathway-next exits 0 on a fully covered outcome")
    check(ready.get("ready_to_close") is True,
          "pathway-next returns explicit ready_to_close when all itinerary pathways are covered")
    check("work-close" in ready.get("next_command", "") and wid in ready.get("next_command", ""),
          "ready-to-close next_command routes to work-close for the active work item")
    recs_after = len((ROOT / "out" / "operator-intelligence" / "pathway-recommendations.ndjson").read_text(encoding="utf-8").splitlines()) if (ROOT / "out" / "operator-intelligence" / "pathway-recommendations.ndjson").exists() else 0
    check(recs_after == recs_before,
          "ready-to-close pathway-next does not log a phantom pathway recommendation")
    check(ready.get("recommendation_id") == "",
          "ready-to-close returns an empty recommendation_id (nothing logged to reference)")

    closed, closed_proc = run("work-close", ["--work-id", wid])
    check(closed_proc.returncode == 0 and closed.get("closed") is True,
          "work-close closes the fully covered outcome")
    check(closed.get("work_id") == wid, "work-close returns non-null work_id")
    check(bool(closed.get("report")) and Path(closed.get("report", "")).exists(),
          "work-close returns a non-null Markdown report that exists")
    check(bool(closed.get("html")) and Path(closed.get("html", "")).exists(),
          "work-close returns a non-null HTML report that exists")


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
    check("--proof-type artifact" in plan_text and "--recommendation-id" in plan_text and "--verify-cmd" in plan_text and "--verified-by" not in plan_text,
          "pathway-run plan contains proof-ready executed-verifier work-log command")
    plans_path = ROOT / "out" / "operator-intelligence" / "pathway-run-plans.ndjson"
    check(plans_path.exists() and plans_path.read_text(encoding="utf-8").strip(),
          "pathway-run writes run-plan ledger")

    again, _proc = run("pathway-run", ["--project", project_path, "--goal", "Run the next pathway slice"])
    check(again.get("work_id") == res.get("work_id"), "pathway-run reuses active work id")
    after_project_files = sorted(p.relative_to(ROOT / "projects") for p in (ROOT / "projects").rglob("*") if p.is_file())
    check(after_project_files == before_project_files, "pathway-run does not mutate project repo files")


def test_pathway_pilot_tracks_agentic_team_cohort():
    reset()
    write("projects/koho/README.md", "# Koho\n")
    write("projects/prettyfly-os/README.md", "# PrettyFly OS\n")
    before_project_files = sorted(p.relative_to(ROOT / "projects") for p in (ROOT / "projects").rglob("*") if p.is_file())
    res, proc = run("pathway-pilot", [
        "--projects", "koho,prettyfly-os",
        "--goal", "Pilot client feedback review packet for customer approval",
    ])
    check(proc.returncode == 0, "pathway-pilot exits 0")
    check(len(res.get("records", [])) == 2, "pathway-pilot enrolls every requested project")
    check(Path(res.get("pilot_ledger", "")).exists() and Path(res.get("pilot_latest", "")).exists(),
          "pathway-pilot writes persistent pilot ledger and latest snapshot")
    check(Path(res.get("report", "")).exists() and Path(res.get("html", "")).exists(),
          "pathway-pilot writes markdown and html operator artifacts")
    records = res.get("records", [])
    check(all(r.get("team_assignment", {}).get("lead") for r in records),
          "each pilot record names the pathway lead")
    check(all(r.get("team_assignment", {}).get("critic") for r in records),
          "each pilot record names the critic")
    check(all(r.get("review_gate", {}).get("required") is True for r in records),
          "client feedback pilot keeps Alex review gates active")
    check(all(r.get("outcome_profile", {}).get("id") == "customer-field-review" for r in records),
          "pilot goal drives customer-field-review profile")
    latest = read_json(res["pilot_latest"])
    check(latest.get("measurement_snapshot", {}).get("metric") == "recommendation action and proof rate",
          "pilot latest snapshot includes the pathway measurement layer")
    report_text = Path(res["report"]).read_text(encoding="utf-8")
    check("Agentic Dev Team Pilot" in report_text and "Final-State Spec" in report_text,
          "pilot report renders the final-state spec")
    after_project_files = sorted(p.relative_to(ROOT / "projects") for p in (ROOT / "projects").rglob("*") if p.is_file())
    check(after_project_files == before_project_files, "pathway-pilot writes central operator state only")


def test_pathway_pilot_logs_one_recommendation_per_enrollment():
    """Regression (review-pilot-double-recommendation-log): the pilot's dry pass must not
    ledger a recommendation. Before the compute/persist split, enrolling a project with no
    active work logged a pre-work-start row that could never be acted on, corrupting the
    autonomy_gate_rate denominator. Exactly one ledger row per enrolled project, and it is
    the row the pilot record references."""
    reset()
    write("projects/koho/README.md", "# Koho\n")
    write("projects/prettyfly-os/README.md", "# PrettyFly OS\n")
    res, proc = run("pathway-pilot", [
        "--projects", "koho,prettyfly-os",
        "--goal", "Pilot client feedback review packet for customer approval",
    ])
    check(proc.returncode == 0, "pilot single-log: pathway-pilot exits 0")
    records = res.get("records", [])
    check(len(records) == 2, "pilot single-log: both projects enrolled")
    rec_ledger = ROOT / "out" / "operator-intelligence" / "pathway-recommendations.ndjson"
    rows = [json.loads(line) for line in rec_ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    check(len(rows) == len(records),
          f"pilot single-log: recommendations ledger gains exactly one row per enrollment (got {len(rows)} for {len(records)})")
    ledger_ids = {r.get("recommendation_id") for r in rows}
    record_ids = {r.get("recommendation_id") for r in records}
    check(record_ids == ledger_ids and all(record_ids),
          "pilot single-log: every ledgered row is the one the pilot record references")
    check(all(r.get("work_id") for r in rows),
          "pilot single-log: no orphan pre-work-start rows (every row carries a work id)")


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


def test_cockpit_surfaces_trivial_verifier_count():
    """Surface the trivial-verifier receipt where the operator reads it: the cockpit reports how
    many recorded proofs were flagged trivial (a no-op verifier), so a gamed proof is visible."""
    reset()
    write("projects/tvapp/README.md", "# tvapp\n")
    proj = str(ROOT / "projects" / "tvapp")
    ev = write("out/operator-artifacts/tv-proof.md", "proof\n")
    start, _ = run("work-start", ["--project", proj, "--goal", "trivial surfacing"])
    wid = start["work_id"]
    run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--proof-type", "artifact", "--verify-cmd", "true"])
    res, proc = run("cockpit")
    check(proc.returncode == 0, "cockpit exits 0")
    data = read_json(res["cockpit"])
    check(data.get("trivial_verifier_count", 0) >= 1,
          f"cockpit counts trivial-verifier proofs (got {data.get('trivial_verifier_count')})")
    text = Path(res["report"]).read_text(encoding="utf-8")
    check("rivial verifier" in text, "cockpit report surfaces the trivial-verifier count")


def test_pfos_cockpit_snapshot_export_is_browser_safe():
    reset()
    write("projects/app/.git/HEAD", "ref: refs/heads/main\n")
    write("projects/app/README.md", "# App\n")
    evidence = write("out/operator-artifacts/proof.md", "proof body with /home/dev/private/source.ts\n")
    project_path = str(ROOT / "projects" / "app")

    trust, _proc = run("pathway-trust", ["--project", project_path])
    rec, _proc = run("pathway-next", ["--project", project_path])
    run("pathway-run", ["--project", project_path, "--goal", "Build the PFOS cockpit"])
    start, _proc = run("work-start", ["--project", project_path, "--goal", "Prove PFOS cockpit", "--tier", "production-secure"])
    run("work-log", [
        "--work-id", start["work_id"], "--pathway", rec["recommended_pathway"], "--kind", "verify",
        "--evidence", str(evidence), "--result", "pass", "--gate", "pfos-cockpit-gate",
        "--proof-type", "artifact", "--verified-by", "python3 /home/dev/.claude/scripts/quality-guard.py", "--verify-cmd", "printf verified",
        "--recommendation-id", rec["recommendation_id"],
    ])
    for pathway in ("research", "govern", "data", "security", "implementation", "quality", "observability", "techdebt", "release", "docs"):
        run("work-cover", ["--work-id", start["work_id"], "--pathway", pathway, "--na", "--reason", "pfos cockpit export fixture only needs the recommended proof"])

    proofs_path = ROOT / "out" / "operator-intelligence" / "proofs.ndjson"
    proofs = [json.loads(line) for line in proofs_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    proofs.append({
        "proof_id": "P-stale",
        "timestamp": "2020-01-01T00:00:00Z",
        "proof_type": "artifact",
        "evidence_path": "/home/dev/private/raw-evidence.md",
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
        "--reason", "Approve after python3 /home/dev/private/check.py proved it.",
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
        "message": "npm run auth-check failed for /home/dev/.env.local",
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


def test_pathway_audit_is_read_only_explainable_and_below_target_is_not_an_error():
    reset()
    write("projects/consult-ops/README.md", "# ConsultOps\n")
    project_path = str(ROOT / "projects" / "consult-ops")
    audit, proc = run("pathway-audit", ["--project", project_path])
    required = {"overall_score", "pathway_scores", "metric_snapshot", "drift_findings", "highest_value_refinements", "report", "html"}
    check(proc.returncode == 0, "pathway-audit exits zero when its below-target measurement completes")
    check(required.issubset(audit), "pathway-audit returns the governed JSON contract")
    check(audit.get("overall_score", 100) < 92, "pathway-audit reports a below-target score without failing")
    check(Path(audit.get("report", "")).is_file() and Path(audit.get("html", "")).is_file(), "pathway-audit writes Markdown and HTML reports")
    signal = read_json(audit.get("signal"))
    check(signal.get("schema_version") == 1 and "template_mismatch_count" in signal and "canary" in signal,
          "pathway-audit writes a safe local observability signal")
    check(audit.get("drift_findings"), "pathway-audit names missing controls rather than hiding deductions")

    opl = load_cli("audit_contract")
    check(not opl.validate_pathway_audit_payload(audit), "pathway-audit emits a valid typed local data contract")
    malformed = dict(audit)
    malformed["metric_snapshot"] = {**audit["metric_snapshot"], "covered_pathways": 9, "required_pathways": 1}
    check(any("covered pathways" in error for error in opl.validate_pathway_audit_payload(malformed)),
          "pathway-audit rejects impossible coverage in a malformed payload")

    opl = load_cli("audit_drift")
    drift, passes, checks = opl.pathway_audit_document_drift({
        label: {"path": label, "exists": True, "text": ""}
        for label in opl.AUDIT_DOCUMENT_REQUIREMENTS
    })
    check(drift and passes == 0 and checks > 0, "intentionally drifted documentation produces explicit audit drift")
    aligned, aligned_passes, aligned_checks = opl.pathway_audit_document_drift({
        label: {"path": label, "exists": True, "text": " ".join(required)}
        for label, required in opl.AUDIT_DOCUMENT_REQUIREMENTS.items()
    })
    check(not aligned and aligned_passes == aligned_checks, "aligned documentation has no audit drift")


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
        "--proof-type", "artifact", "--verified-by", "python3 tests", "--verify-cmd", "printf verified", "--recommendation-id", recommendation_id,
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
    run("work-log", ["--work-id", demo_wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact", "--verified-by", "test verifier", "--verify-cmd", "printf verified"])
    data, _ = run("work-status", ["--work-id", demo_wid])
    st = {e["pathway"]: e["status"] for e in data["summary"]["itinerary"]}
    check(st["govern"] == "proved", "a real on-disk artifact marks the pathway proved")

    # Fix (GLM): --add must not un-prove an already-proved pathway.
    run("work-cover", ["--work-id", demo_wid, "--pathway", "govern", "--add"])
    data, _ = run("work-status", ["--work-id", demo_wid])
    st = {e["pathway"]: e["status"] for e in data["summary"]["itinerary"]}
    check(st["govern"] == "proved", "work-cover --add preserves earned proof")

    # Regression: a newly revealed required pathway must survive the read-time
    # itinerary recompute, or work-cover reports success once and then silently
    # allows a false closeout on the very next command.
    run("work-cover", ["--work-id", demo_wid, "--pathway", "field", "--add",
                       "--reason", "operator validation surfaced during execution"])
    data, _ = run("work-status", ["--work-id", demo_wid])
    st = {e["pathway"]: e["status"] for e in data["summary"]["itinerary"]}
    check(st.get("field") == "required",
          "work-cover --add preserves a newly required pathway across recompute")
    check("field" in data["summary"]["itinerary_coverage"]["open"],
          "newly required pathway continues to block closeout")

    # Fix (Codex): work-cover input guards.
    data, _ = run("work-cover", ["--work-id", demo_wid, "--pathway", "bogus", "--na", "--reason", "x"])
    check("work-cover-unknown-pathway" in ids(data), "work-cover rejects an unknown pathway name")
    data, _ = run("work-cover", ["--work-id", demo_wid, "--pathway", "quality", "--reason", "x"])
    check("work-cover-needs-one-action" in ids(data), "work-cover requires exactly one of --na/--add")
    data, _ = run("work-cover", ["--work-id", demo_wid, "--pathway", "quality", "--na"])
    check("work-cover-na-needs-reason" in ids(data), "work-cover --na requires a reason")

    # N/A the rest (with reasons) -> close succeeds at full coverage.
    for pathway in ("implementation", "quality", "field"):
        run("work-cover", ["--work-id", demo_wid, "--pathway", pathway, "--na", "--reason", "n/a for this test"])
    data, _ = run("work-close", ["--work-id", demo_wid])
    check(data.get("closed") is True, "work-close succeeds once every pathway is proved or N/A")

    # Fix (Codex + GLM): a tier downgrade retains earned proof.
    run("work-log", ["--work-id", secure_wid, "--pathway", "security", "--kind", "verify", "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact", "--verified-by", "test verifier", "--verify-cmd", "printf verified"])
    run("work-start", ["--project", str(proj), "--goal", "production secure dashboard ui", "--tier", "demoable"])
    data, _ = run("work-status", ["--work-id", secure_wid])
    st = {e["pathway"]: e["status"] for e in data["summary"]["itinerary"]}
    check(st.get("security") == "proved", "tier downgrade retains earned proof (security stays proved)")


def test_proof_add_flips_itinerary_coverage():
    """Regression (coverage join): a verified proof recorded through `proof-add` — not only an
    inline work-log — must close the itinerary join. The pathway flips required->proved and
    coverage stops reporting it as logged_unverified. Before the fix, proof-add never touched the
    itinerary and coverage stalled at covered:0 with every logged pathway stuck at
    logged_unverified, even though a re-executed verifier had exited 0."""
    reset()
    proj = ROOT / "projects" / "proofjoin"
    proj.mkdir(parents=True, exist_ok=True)
    ev = ROOT / "pj-evidence.txt"
    ev.write_text("artifact", encoding="utf-8")
    start, _ = run("work-start", ["--project", str(proj), "--goal", "proof-add join test", "--tier", "demoable"])
    wid = start["work_id"]

    # A run is logged for govern WITHOUT a re-executed verifier -> logged but unverified.
    run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--gate", "govern-gate", "--proof-type", "artifact", "--verified-by", "attested"])
    data, _ = run("work-status", ["--work-id", wid])
    cov = data["summary"]["itinerary_coverage"]
    check(cov["covered"] == 0 and "govern" in cov["logged_unverified"],
          "a logged-but-unverified pathway starts at covered:0 / logged_unverified")

    # proof-add records a genuinely verified proof (re-executed verifier, exit 0) for govern.
    added, _ = run("proof-add", ["--work-id", wid, "--pathway", "govern", "--proof-type", "artifact",
                                 "--evidence", str(ev), "--gate", "govern-gate", "--verify-cmd", "printf verified"])
    check(added.get("itinerary_coverage", {}).get("covered", 0) >= 1,
          "proof-add reports the pathway it just verified as covered")

    # The join is now closed: govern is proved and no longer logged_unverified.
    data, _ = run("work-status", ["--work-id", wid])
    st = {e["pathway"]: e["status"] for e in data["summary"]["itinerary"]}
    cov = data["summary"]["itinerary_coverage"]
    check(st["govern"] == "proved", "proof-add with a real verifier flips the pathway to proved")
    check(cov["covered"] >= 1 and "govern" not in cov["logged_unverified"],
          "coverage credits the verified proof and drops it from logged_unverified")

    # A bare attestation via proof-add must NOT flip a second pathway (verifier bar preserved).
    run("proof-add", ["--work-id", wid, "--pathway", "quality", "--proof-type", "artifact",
                      "--evidence", str(ev), "--gate", "quality-gate", "--verified-by", "trust me"])
    data, _ = run("work-status", ["--work-id", wid])
    st = {e["pathway"]: e["status"] for e in data["summary"]["itinerary"]}
    check(st["quality"] == "required",
          "proof-add with only free-text attestation does NOT prove a pathway (bar preserved)")


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
    run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact", "--verified-by", "pytest -q (green)", "--verify-cmd", "printf verified"])
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
                     "--result", "pass", "--proof-type", "artifact", "--verified-by", "test", "--verify-cmd", "printf verified"])
    rec, _ = run("pathway-next", ["--project", str(proj)])
    check(rec.get("recommended_pathway") == "observability",
          f"an error finding steers the next pick to observability over canonical-first data (got {rec.get('recommended_pathway')})")
    # Confidence must describe the RECOMMENDED pathway, not an out-of-itinerary foundation.
    conf = rec.get("recommendation_confidence", {})
    check("Foundation gate" not in conf.get("why_this", ""),
          f"confidence why_this reflects the recommended pathway, not a foundation (got: {conf.get('why_this','')[:50]})")
    check(conf.get("level") != "low",
          f"an error-finding-backed pick is not low confidence (got {conf.get('level')})")


def test_wilson_lower_bound_gates_small_n():
    """The autonomy gate's keystone stat: a Wilson score lower bound (z=1.96), NOT a Wald point
    estimate. n=1 at 100% must read far below the 0.5 gate (the bug the point estimate caused).
    Thresholds recomputed at z=1.96 — the dossier's unlock table (k>=8 at n=10) was computed at
    z=1.645 and is off by one; at z=1.96 it is n=10->k>=9, n=20->k>=15, n=50->k>=32."""
    opl = load_cli("wilson")
    w = opl.wilson_lower_bound
    check(w(0, 0) == 0.0, "no trials -> 0.0 (nothing proved, fail-closed)")
    check(w(11, 10) == 0.0, "k>n is a corrupted count -> 0.0 (fail closed; a safety gate must never crash)")
    check(w(-1, 10) == 0.0, "k<0 is a corrupted count -> 0.0 (fail closed)")
    check(w(1, 1) < 0.5, f"n=1 at 100% is BELOW the gate (the point-estimate bug) (got {w(1,1):.4f})")
    check(abs(w(1, 1) - 0.2065) < 1e-3, f"wilson_lb(1,1) ~= 0.2065 (got {w(1,1):.4f})")
    check(w(8, 10) < 0.5, f"8/10 does NOT clear the 0.5 gate at z=1.96 (got {w(8,10):.4f})")
    check(w(9, 10) >= 0.5, f"9/10 clears the 0.5 gate at z=1.96 (got {w(9,10):.4f})")
    check(abs(w(9, 10) - 0.5958) < 1e-3, f"wilson_lb(9,10) ~= 0.5958 (got {w(9,10):.4f})")
    check(w(14, 20) < 0.5 and w(15, 20) >= 0.5, "n=20 unlock straddles k=15 at the 0.5 gate")
    check(w(31, 50) < 0.5 and w(32, 50) >= 0.5, "n=50 unlock straddles k=32 at the 0.5 gate")
    check(w(9, 10) > w(8, 10), "more proofs at fixed n raise the lower bound (monotone in k)")
    check(w(80, 100) > w(8, 10), "same 0.8 rate at larger n raises the bound (tighter interval)")


def test_wilson_jeffreys_cross_check():
    """Cross-check the Wilson unlock thresholds against an independent construction (Jeffreys
    interval). Two different small-n confidence methods must agree on the unlock DECISION at every
    boundary, or the threshold is a single-formula artifact. (dossier item 3.)"""
    opl = load_cli("xcheck")
    for k, n in [(1, 1), (7, 10), (8, 10), (9, 10), (10, 10), (14, 20), (15, 20), (31, 50), (32, 50)]:
        wlb, jlb = opl.wilson_lower_bound(k, n), _jeffreys_lower_bound(k, n)
        check((wlb >= 0.5) == (jlb >= 0.5),
              f"Wilson and Jeffreys agree on unlock at k={k}/n={n} (wilson={wlb:.4f}, jeffreys={jlb:.4f})")


def test_autonomy_gate_rate_enforces_min_n_floor():
    """The gate-rate fed to suggest_autonomy_tier is wilson_lower_bound(proved,total) ONLY at
    total>=MIN_AUTONOMY_N (10); below the floor it is 0.0, so no streak of low-n successes can
    unlock execute-safe. This is the 'a hard minimum n is non-negotiable' rule, in code."""
    opl = load_cli("gaterate")
    check(opl.MIN_AUTONOMY_N == 10, "MIN_AUTONOMY_N is 10 (the hard floor)")
    g = opl.autonomy_gate_rate
    check(g(1, 1) == 0.0, "n=1 at 100% -> 0.0 (below the n>=10 floor)")
    check(g(9, 9) == 0.0, "n=9 at 100% -> 0.0 (still below the floor; a streak can't unlock)")
    check(g(0, 0) == 0.0, "no recommendations -> 0.0")
    check(g(11, 10) == 0.0, "corrupted count proved>total -> 0.0 (fail closed past the floor, no crash)")
    check(g(8, 10) == opl.wilson_lower_bound(8, 10), "at n=10 the floor opens; gate-rate is the Wilson LB")
    check(g(8, 10) < 0.5, "n=10 k=8 is past the floor but still below the 0.5 gate")
    check(g(9, 10) >= 0.5, "n=10 k=9 clears both the floor and the 0.5 gate")
    check(g(10, 10) == opl.wilson_lower_bound(10, 10), "above the floor the Wilson LB passes straight through")


def test_suggested_autonomy_tier_gates_on_proof_trust_confidence():
    """Gap C (autonomy unlock): pathway-next computes ONE field — suggested_autonomy_tier —
    so the /pathway loop reads it instead of re-deriving the Tier-2 rule from three signals
    each turn. 'execute-safe' unlocks ONLY when proof rate >= the gate AND trust = pass AND
    the pick is high-confidence; every other combination fails closed to 'recommend'."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("opl_autonomy_under_test", CLI)
    opl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(opl)

    # --- Unit truth table: the pure gate (each signal is load-bearing) ---
    hi, passing = {"level": "high"}, {"status": "pass"}
    check(opl.suggest_autonomy_tier(0.6, passing, hi)["tier"] == "execute-safe",
          "proof>=gate + trust pass + high confidence -> execute-safe")
    check(opl.suggest_autonomy_tier(0.5, passing, hi)["tier"] == "execute-safe",
          "proof exactly at the 0.5 gate clears it (>=, not >)")
    check(opl.suggest_autonomy_tier(0.49, passing, hi)["tier"] == "recommend",
          "proof below gate -> recommend (fail-closed on the metric)")
    check(opl.suggest_autonomy_tier(0.9, {"status": "fail"}, hi)["tier"] == "recommend",
          "trust fail -> recommend even with proof + high confidence")
    check(opl.suggest_autonomy_tier(0.9, passing, {"level": "medium"})["tier"] == "recommend",
          "medium confidence -> recommend (Tier 2 needs high)")
    check(opl.suggest_autonomy_tier(0.9, {}, hi)["tier"] == "recommend",
          "unknown trust -> recommend (fail-closed)")

    # --- Integration: the field is wired into pathway-next and computed from real state ---
    reset()
    proj = ROOT / "projects" / "autoproj"
    (proj / ".planning").mkdir(parents=True, exist_ok=True)
    (proj / "package.json").write_text('{"name":"autoproj"}\n', encoding="utf-8")
    (proj / "src").mkdir(parents=True, exist_ok=True)
    (proj / "src" / "index.ts").write_text("export const x = 1;\n", encoding="utf-8")
    ev = ROOT / "auto-ev.txt"
    ev.write_text("artifact", encoding="utf-8")
    # Three error findings routed to quality -> a high-confidence pick once govern is covered.
    (proj / ".planning" / "findings.json").write_text(
        json.dumps([
            {"id": "q1", "message": "flaky e2e suite", "severity": "error", "pathway": "quality"},
            {"id": "q2", "message": "no coverage gate in CI", "severity": "error", "pathway": "quality"},
            {"id": "q3", "message": "lint disabled on merge", "severity": "error", "pathway": "quality"},
        ]),
        encoding="utf-8")
    # This test exercises the AUTONOMY GATE; pathway-trust's status is wall-clock-timing sensitive
    # (run_trust_command flips pass->warn when a self-check subprocess merely exceeds its time budget
    # under machine load), which is orthogonal here and covered by the trust tests. Run it for setup,
    # then pin the status pathway-next will read so the gate — not the timing — is what's measured.
    run("pathway-trust", ["--project", str(proj)])
    trust_file = ROOT / "out" / "operator-intelligence" / "pathway-trust.json"
    td = json.loads(trust_file.read_text(encoding="utf-8"))
    td["status"] = "pass"
    trust_file.write_text(json.dumps(td), encoding="utf-8")
    start, _ = run("work-start", ["--project", str(proj), "--goal", "harden the quality bar", "--tier", "demoable"])
    wid = start["work_id"]

    # Fresh project: no proof track record yet -> fail-closed to recommend.
    first, _ = run("pathway-next", ["--project", str(proj)])
    check(first.get("suggested_autonomy_tier") == "recommend",
          f"no proof history -> recommend (got {first.get('suggested_autonomy_tier')})")
    check(first.get("recommended_pathway") == "govern",
          f"foundation govern is recommended first (got {first.get('recommended_pathway')})")
    gov_rec = first["recommendation_id"]

    # Prove the govern recommendation. The OLD gate (Wald point estimate) unlocked right here at
    # n=1 / 100% — the bug. The Wilson gate with the n>=10 floor must STILL fail closed.
    run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--gate", "govern-gate", "--proof-type", "artifact",
                     "--verified-by", "python3 tests (green)", "--verify-cmd", "printf verified", "--recommendation-id", gov_rec])

    # govern covered -> quality (3 error findings) is the high-confidence pick; trust passes. The
    # ONLY thing short of execute-safe is the proof track record: n=1 is below MIN_AUTONOMY_N, so
    # the gate-rate is 0.0 and the tier stays recommend. (Pre-fix this single proof wrongly unlocked.)
    second, _ = run("pathway-next", ["--project", str(proj)])
    check(second.get("recommended_pathway") == "quality",
          f"after govern, evidence steers the pick to quality (got {second.get('recommended_pathway')})")
    check(second.get("recommendation_confidence", {}).get("level") == "high",
          f"three error findings make quality high-confidence (got {second.get('recommendation_confidence', {}).get('level')})")
    check(second.get("suggested_autonomy_tier") == "recommend",
          f"n=1 at 100% must NO LONGER unlock — below the n>=10 floor (got {second.get('suggested_autonomy_tier')})")

    # Build a real track record past the floor: seed >=10 prior recommendations, each with a
    # verified (re-executed, exit 0) proof. wilson_lb(proved/total) then clears 0.5; with trust
    # pass + high confidence -> execute-safe. Seeded rows use distinct ids/project so the autoproj
    # pick and itinerary coverage are untouched — the gate metric is global by construction. (This
    # test covers the n>=10 RATE wiring; that ONLY verified proofs count toward proved is covered
    # separately by test_autonomy_metric_counts_only_verified_proofs.)
    intel = ROOT / "out" / "operator-intelligence"
    seed_recs, seed_proofs = [], []
    for i in range(12):
        ts = opl.iso_now()
        rid = f"SEED-xprec-{i:04d}"
        seed_recs.append({"recommendation_id": rid, "project": "seedproj", "pathway": "quality",
                          "work_id": "", "confidence": "high", "timestamp": ts})
        seed_proofs.append({"proof_id": f"SEEDPROOF-{i:04d}", "recommendation_id": rid,
                            "pathway": "quality", "work_id": "", "project": "seedproj",
                            "result": "pass", "verifier_strength": "executed", "exit_code": 0,
                            "verify_command": "pytest -q", "timestamp": ts})
    append_ndjson(intel / "pathway-recommendations.ndjson", seed_recs)
    append_ndjson(intel / "proofs.ndjson", seed_proofs)

    third, _ = run("pathway-next", ["--project", str(proj)])
    check(third.get("recommended_pathway") == "quality",
          f"pick is still the high-confidence quality after seeding (got {third.get('recommended_pathway')})")
    check(third.get("suggested_autonomy_tier") == "execute-safe",
          f">=10 verified proofs + trust pass + high confidence -> execute-safe (got {third.get('suggested_autonomy_tier')})")
    rat = third.get("autonomy_rationale", {})
    check(rat.get("proved_rate", 0) >= 0.5 and rat.get("trust_status") == "pass" and rat.get("confidence_level") == "high",
          f"rationale exposes the three deciding inputs, gate-rate past 0.5 (got {rat})")
    check(rat.get("fresh") is True, "autonomy rationale is computed fresh this determine turn")
    report_text = Path(third["report"]).read_text(encoding="utf-8")
    check("## Suggested Autonomy" in report_text and "execute-safe" in report_text,
          "pathway-next report renders the suggested autonomy tier")


def test_learning_loop_closed_outcomes_reweight_rankings():
    """Gap D (learning loop): closed outcomes reweight future rankings. A pathway the project
    has repeatedly proved-and-closed is dampened — by that track record it is less likely to be
    the current constraint — so the recommender shifts toward pathways the project has not yet
    demonstrated. Measurable as a ranking shift after N closes, and project-scoped (no global bleed)."""
    reset()
    proj = ROOT / "projects" / "learnproj"
    (proj / ".planning").mkdir(parents=True, exist_ok=True)
    (proj / "package.json").write_text('{"name":"learnproj"}\n', encoding="utf-8")
    ev = ROOT / "learn-ev.txt"
    ev.write_text("artifact", encoding="utf-8")

    start, _ = run("work-start", ["--project", str(proj), "--goal", "ship the core slice", "--tier", "demoable"])
    wid = start["work_id"]
    # Cover the govern foundation so the next pick is chosen among non-foundation pathways.
    run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--gate", "govern-gate", "--proof-type", "artifact", "--verified-by", "test", "--verify-cmd", "printf verified"])

    # BEFORE any closes: implementation and quality both sit on the completeness nudge; canonical
    # order puts implementation first. No learning history yet -> the reweight is a no-op.
    before, _ = run("pathway-next", ["--project", str(proj)])
    check(before.get("recommended_pathway") == "implementation",
          f"baseline pick is implementation (canonical-first among tied nudges) (got {before.get('recommended_pathway')})")

    # Simulate prior closes (shape mirrors extract_learning_candidate): 2 learnproj outcomes proved
    # implementation; 3 OTHER-project outcomes proved quality (must NOT bleed into learnproj).
    lc_path = ROOT / "out" / "operator-intelligence" / "learning-candidates.ndjson"
    lc_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"learning_id": f"L-impl-{i}", "work_id": f"W-closed-impl-{i}", "project": "learnproj",
         "project_path": str(proj), "pathways_seen": ["govern", "implementation"]}
        for i in range(2)
    ] + [
        {"learning_id": f"L-other-{i}", "work_id": f"W-other-q-{i}", "project": "otherproj",
         "project_path": str(ROOT / "projects" / "otherproj"), "pathways_seen": ["quality"]}
        for i in range(3)
    ]
    lc_path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    # AFTER: implementation is dampened below quality -> the pick shifts. quality is undampened
    # because its closes belong to a DIFFERENT project (if scoping bled, quality would sink lowest
    # and implementation would win again — so recommended==quality proves both shift AND scoping).
    after, _ = run("pathway-next", ["--project", str(proj)])
    check(after.get("recommended_pathway") == "quality",
          f"after 2 closes proving implementation, the pick shifts to quality (got {after.get('recommended_pathway')})")
    ranked = {r["pathway"]: r for r in after.get("ranked", [])}
    check(any("Demonstrated" in reason for reason in ranked.get("implementation", {}).get("reasons", [])),
          "the dampened pathway carries the learning reason (shift is attributable)")
    check(not any("Demonstrated" in reason for reason in ranked.get("quality", {}).get("reasons", [])),
          "quality is NOT dampened by another project's closes (learning is project-scoped)")
    check(ranked.get("implementation", {}).get("score", 0) < ranked.get("quality", {}).get("score", 0),
          f"implementation now scores below quality (got impl={ranked.get('implementation',{}).get('score')}, "
          f"quality={ranked.get('quality',{}).get('score')})")


def test_tier_calibration_measures_defaults_from_closed_outcomes():
    """Gap E (tier calibration): the heuristic tier->pathway map is a guess; closed outcomes are
    evidence. tier-calibrate measures, per tier, how often each pathway was proved vs marked N/A
    across closed outcomes, and surfaces where the measured need diverges from the hardcoded
    default — as ADVICE only (it never mutates the map; the coverage guarantee forbids silent drops)."""
    reset()
    wi_path = ROOT / "out" / "operator-intelligence" / "work-items.ndjson"
    wi_path.parent.mkdir(parents=True, exist_ok=True)
    # 3 closed "live" outcomes (across different projects — tier defs are global): every default
    # pathway proved EXCEPT docs (always N/A), plus security (NOT in live's default) always proved.
    live_default = ["govern", "data", "implementation", "quality", "observability", "release", "docs"]
    rows = []
    for i in range(3):
        itin = [{"pathway": p, "status": ("na" if p == "docs" else "proved")} for p in live_default]
        itin.append({"pathway": "security", "status": "proved"})
        if i == 0:
            itin.append({"pathway": "security", "status": "proved"})  # duplicate entry — must not double-count
        rows.append({"work_id": f"W-live-{i}", "project_name": f"proj{i}", "status": "closed",
                     "tier": "live", "itinerary": itin})
    # 1 closed "demoable" outcome — below the min-outcomes floor, so it earns NO calibration claim.
    rows.append({"work_id": "W-demo-0", "project_name": "p", "status": "closed", "tier": "demoable",
                 "itinerary": [{"pathway": "govern", "status": "proved"},
                               {"pathway": "implementation", "status": "proved"},
                               {"pathway": "quality", "status": "proved"}]})
    wi_path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    cal, proc = run("tier-calibrate")
    check(proc.returncode == 0, "tier-calibrate exits 0")
    tiers = {t["tier"]: t for t in cal.get("tiers", [])}
    live = tiers.get("live", {})
    check(live.get("closed_outcomes") == 3, f"live tier counts its 3 closed outcomes (got {live.get('closed_outcomes')})")
    drop = {d["pathway"] for d in live.get("drop_candidates", [])}
    add = {a["pathway"] for a in live.get("add_candidates", [])}
    check("docs" in drop, f"docs (N/A in 3/3 live closes) is a drop candidate (got {drop})")
    check("security" in add, f"security (proved 3/3, absent from the default) is an add candidate (got {add})")
    check(live.get("diverges_from_default") is True, "live tier's measured need diverges from the heuristic default")
    check("implementation" not in drop and "implementation" in set(live.get("measured_required", [])),
          "consistently-proved defaults are NOT drop candidates and ARE measured-required")
    # A duplicated itinerary entry (corrupted/hand-edited store) must not push any rate above 1.0.
    check(all(r <= 1.0 for r in live.get("proved_rate", {}).values())
          and all(r <= 1.0 for r in live.get("na_rate", {}).values()),
          f"rates never exceed 1.0 despite a duplicated entry (proved={live.get('proved_rate')})")

    # Falsifiable floor: a tier under the min-outcomes threshold makes NO calibration claim.
    demo = tiers.get("demoable", {})
    check(demo.get("sufficient") is False and not demo.get("drop_candidates") and not demo.get("add_candidates"),
          "a tier below the min-outcomes floor yields no calibration changes (insufficient signal)")
    # The heuristic map is reported verbatim and the advisory artifact is real on disk.
    check(live.get("heuristic_default") == live_default, "tier-calibrate reports the heuristic default verbatim")
    check(Path(cal.get("report", "")).exists(), "tier-calibrate writes an advisory report artifact")


def test_proof_requires_real_verifier_not_freetext():
    """Keystone: a pathway reaches `proved` ONLY via a non-trivial re-executed verifier that exits
    0. Bare free-text --verified-by is attestation, not
    verification — it cannot prove (this is what kills the forgery the world-class audit caught)."""
    reset()
    proj = ROOT / "projects" / "kproj"
    proj.mkdir(parents=True, exist_ok=True)
    ev = ROOT / "k-ev.txt"
    ev.write_text("artifact", encoding="utf-8")
    data, _ = run("work-start", ["--project", str(proj), "--goal", "keystone proof test", "--tier", "demoable"])
    wid = data["work_id"]

    def gov_status():
        d, _ = run("work-status", ["--work-id", wid])
        return {e["pathway"]: e["status"] for e in d["summary"]["itinerary"]}["govern"]

    # 1. FORGERY BLOCKED — junk file + garbage free-text, no real verifier -> stays required.
    run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--proof-type", "artifact", "--verified-by", "lol trust me bro"])
    check(gov_status() == "required", "free-text attestation alone does NOT prove a pathway (forgery blocked)")

    # 2. FAILING VERIFIER BLOCKED — a command that exits non-zero cannot prove.
    run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--proof-type", "artifact", "--verify-cmd", "exit 1"])
    check(gov_status() == "required", "a verifier command that exits non-zero does not prove")

    # 3. BLOCKED OUTCOME STAYS BLOCKED — exit 0 means the verifier ran; it must not launder an
    # explicitly blocked operator result into a passing proof.
    blocked, _ = run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev),
                     "--result", "blocked", "--proof-type", "artifact", "--verify-cmd", "printf verified"])
    check(gov_status() == "required", "an exit-0 verifier does not turn a blocked result into proved")
    blocked_proof = [r for r in blocked.get("records", []) if r.get("verifier_strength")]
    check(bool(blocked_proof) and blocked_proof[0]["exit_code"] == 0,
          "the blocked proof still records its successful verifier receipt")

    # Repair regression: older engines could already have persisted that blocked receipt as
    # `proved`. A deliberate work-cover --add reopens only this demonstrably unsupported entry.
    items_path = ROOT / "out" / "operator-intelligence" / "work-items.ndjson"
    items = [json.loads(line) for line in items_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for item in items:
        if item.get("work_id") != wid:
            continue
        for entry in item.get("itinerary", []):
            if entry.get("pathway") == "govern":
                entry["status"] = "proved"
                entry["proved_by_run"] = "[REDACTED]"  # legacy nested-id redaction defect
    items_path.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in items), encoding="utf-8")
    run("work-cover", ["--work-id", wid, "--pathway", "govern", "--add",
                       "--reason", "blocked receipt does not prove the pathway"])
    check(gov_status() == "required", "work-cover --add repairs a proved entry backed only by a blocked receipt")

    # 4. REAL VERIFIER PROVES — an executed command that exits 0 with observable output flips to proved.
    out, _ = run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--proof-type", "artifact", "--verify-cmd", "printf verified"])
    check(gov_status() == "proved", "a re-executed verifier exiting 0 proves the pathway")
    proof = [r for r in out.get("records", []) if r.get("verifier_strength")]
    check(bool(proof) and proof[0]["verifier_strength"] == "executed" and proof[0]["exit_code"] == 0,
          f"the proof records executed strength + exit code 0 (got {proof[0] if proof else None})")

    # 5. BARE HUMAN ATTESTATION DOES NOT PROVE — a --reviewer NAME is recorded for accountability
    # (with the artifact hash) but is not a verifiable receipt, so it cannot flip to proved on its
    # own. (A dual-critic pass caught --reviewer as the same forgery the keystone killed under a
    # different flag.) Only a re-executed verifier proves; verifiable human sign-off is future work.
    out2, _ = run("work-log", ["--work-id", wid, "--pathway", "quality", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--proof-type", "artifact", "--reviewer", "god"])
    d, _ = run("work-status", ["--work-id", wid])
    qstat = {e["pathway"]: e["status"] for e in d["summary"]["itinerary"]}["quality"]
    sproof = [r for r in out2.get("records", []) if r.get("verifier_strength")]
    check(qstat == "required", "a bare reviewer name does NOT prove (a name is not a verifiable receipt)")
    check(bool(sproof) and sproof[0]["verifier_strength"] == "signed" and bool(sproof[0].get("artifact_sha256")),
          "the reviewer attestation is still recorded (signed strength + artifact hash) for accountability")

    # Explicit pass vocabulary stays backward compatible; ambiguous workflow states do not pass.
    opl = load_cli("proofresults")
    for result in ("pass", "passed: checks green", "pass-spec-only", "present", "GREEN"):
        check(opl.proof_result_is_passing(result) is True, f"{result!r} remains a passing proof result")
    for result in ("blocked", "blocked-pending-owner", "open", "partial", "fail", "STAGED", "[REDACTED]"):
        check(opl.proof_result_is_passing(result) is False, f"{result!r} cannot prove a pathway")
    generated_run_id = "R-W-20260717-example-release-001"
    check(opl.redact_obj({"proved_by_run": generated_run_id})["proved_by_run"] == generated_run_id,
          "nested proved_by_run receipts survive safety redaction")


def test_autonomy_metric_counts_only_verified_proofs():
    """Keystone (independence): the proof rate that gates autonomy counts ONLY verified proofs.
    A free-text attestation cannot raise proved_rate, so execute-safe can't be farmed by self-
    attesting trivial recommendations."""
    reset()
    write("projects/consult-ops/README.md", "# ConsultOps\n")
    evidence = write("out/operator-artifacts/k-proof.md", "proof\n")
    project_path = str(ROOT / "projects" / "consult-ops")

    rec, _ = run("pathway-next", ["--project", project_path])
    rid, pathway = rec["recommendation_id"], rec["recommended_pathway"]
    start, _ = run("work-start", ["--project", project_path, "--goal", "metric independence"])
    wid = start["work_id"]

    # Attested-only proof (free text) — must NOT count toward the autonomy proof rate.
    run("work-log", ["--work-id", wid, "--pathway", pathway, "--kind", "verify", "--evidence", str(evidence),
                     "--result", "pass", "--proof-type", "artifact", "--verified-by", "trust me", "--recommendation-id", rid])
    m_attested, _ = run("pathway-metric", ["--gate-target", "0.5"])
    check(m_attested["metric"]["proved"] == 0,
          f"a free-text attestation does not count as a proved recommendation (got {m_attested['metric']['proved']})")

    # A re-executed verifier (exit 0) — counts.
    run("work-log", ["--work-id", wid, "--pathway", pathway, "--kind", "verify", "--evidence", str(evidence),
                     "--result", "pass", "--proof-type", "artifact", "--verify-cmd", "printf verified", "--recommendation-id", rid])
    m_verified, _ = run("pathway-metric", ["--gate-target", "0.5"])
    check(m_verified["metric"]["proved"] >= 1,
          "a re-executed verifier counts as a proved recommendation")


def test_trivial_verifier_does_not_prove_or_close():
    reset()
    proj = ROOT / "projects" / "trivialblock"
    proj.mkdir(parents=True, exist_ok=True)
    ev = ROOT / "trivial-proof.txt"
    ev.write_text("artifact", encoding="utf-8")
    start, _ = run("work-start", ["--project", str(proj), "--goal", "block trivial verifier", "--tier", "demoable"])
    wid = start["work_id"]

    logged, _ = run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify",
                                 "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact",
                                 "--verify-cmd", "true"])
    proof = next((r for r in logged.get("records", []) if r.get("verifier_strength")), {})
    check(proof.get("trivial_verifier") is True, "the no-op verifier is flagged trivial")
    status, _ = run("work-status", ["--work-id", wid])
    st = {e["pathway"]: e["status"] for e in status["summary"]["itinerary"]}
    check(st["govern"] == "required", "a trivial verifier does not prove the pathway")
    close, _ = run("work-close", ["--work-id", wid])
    check(close.get("closed") is not True, "a trivial verifier cannot make closeout ready")


def test_verifier_receipt_flags_trivial_command():
    """Trivial-verifier receipt (dossier item 2): `--verify-cmd true` exits 0 but proves nothing.
    The proof now carries a receipt — verifier_source_sha256, a stdout byte count, and a
    trivial_verifier flag — so a no-op verifier is detectable. (Denylist + byte-floor here; the
    canary mutant is the keystone, tested separately.)"""
    import hashlib
    reset()
    write("projects/recpt/README.md", "# recpt\n")
    proj = str(ROOT / "projects" / "recpt")
    ev = write("out/operator-artifacts/recpt-proof.md", "proof\n")
    start, _ = run("work-start", ["--project", proj, "--goal", "verifier receipt"])
    wid = start["work_id"]
    proofs_file = ROOT / "out" / "operator-intelligence" / "proofs.ndjson"

    # A no-op verifier: exits 0, empty stdout, denylisted source.
    run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--proof-type", "artifact", "--verify-cmd", "true"])
    p = [json.loads(l) for l in proofs_file.read_text().splitlines() if l.strip()][-1]
    check(p.get("verifier_source_sha256") == hashlib.sha256(b"true").hexdigest(),
          "receipt records the SHA-256 of the verifier command source")
    check(p.get("artifact_sha256") == hashlib.sha256(b"proof\n").hexdigest(),
          "the artifact-hash binding is preserved, not scrubbed to [REDACTED] by the entropy redactor")
    check(p.get("verify_stdout_bytes") == 0, f"`true` produces zero stdout bytes (got {p.get('verify_stdout_bytes')})")
    check(p.get("trivial_verifier") is True, "`true` is flagged trivial (denylist + empty stdout)")

    # Each denylisted form is caught.
    for cmd in [":", "exit 0", "echo ok"]:
        run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev),
                         "--result", "pass", "--proof-type", "artifact", "--verify-cmd", cmd])
        pl = [json.loads(l) for l in proofs_file.read_text().splitlines() if l.strip()][-1]
        check(pl.get("trivial_verifier") is True, f"`{cmd}` is flagged as a trivial verifier")

    # A real-looking verifier: non-denylisted, emits stdout above the byte floor.
    run("work-log", ["--work-id", wid, "--pathway", "quality", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--proof-type", "artifact", "--verify-cmd", "printf verified-output"])
    p2 = [json.loads(l) for l in proofs_file.read_text().splitlines() if l.strip()][-1]
    check(p2.get("verify_stdout_bytes", 0) >= 1, "a real verifier emits stdout above the byte floor")
    check(p2.get("trivial_verifier") is False,
          f"a non-denylisted verifier with real stdout is not flagged trivial (got {p2.get('trivial_verifier')})")

    # An echo PREAMBLE must not hide a real verifier from the canary: only a bare echo is trivial.
    opl = load_cli("trivial_chain")
    check(opl.verifier_command_is_trivial("echo ok") is True, "a bare echo is trivial")
    check(opl.verifier_command_is_trivial("echo start && pytest -q") is False,
          "an echo chained to a real command is NOT trivial (canary must still run)")
    check(opl.verifier_command_is_trivial("echo pretest; ./verify.sh") is False,
          "an echo followed by a semicolon-chained verifier is NOT trivial")


def test_verifier_receipt_canary_mutant_catches_noop_verifier():
    """Canary mutant (dossier item 2, keystone): flip a byte in a changed line and re-run the
    verifier. A real verifier must now FAIL; a no-op that ignores the change still passes and
    self-incriminates -> trivial_verifier. The single highest-leverage anti-gaming check. And the
    working tree must be restored byte-for-byte afterward (no side effects)."""
    import subprocess as sp
    reset()
    proj = ROOT / "projects" / "canaryproj"
    proj.mkdir(parents=True, exist_ok=True)
    def git(*a): sp.run(["git", "-C", str(proj)] + list(a), capture_output=True, text=True)
    git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    (proj / "value.txt").write_text("42\n")
    git("add", "-A"); git("commit", "-q", "-m", "baseline")
    (proj / "value.txt").write_text("100\n")  # the change under verification
    os.chmod(proj / "value.txt", 0o755)  # executable target: restore must keep the mode
    ev = write("out/operator-artifacts/canary-proof.md", "proof\n")
    start, _ = run("work-start", ["--project", str(proj), "--goal", "canary"])
    wid = start["work_id"]
    proofs_file = ROOT / "out" / "operator-intelligence" / "proofs.ndjson"

    # REAL verifier: greps the changed line AND prints it (clears the byte floor).
    run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--proof-type", "artifact", "--project", str(proj),
                     "--verify-cmd", "grep 100 value.txt"])
    real = [json.loads(l) for l in proofs_file.read_text().splitlines() if l.strip()][-1]
    check(real.get("canary_mutant_failed") is True,
          f"a real verifier FAILS when the changed line is mutated (got {real.get('canary_mutant_failed')})")
    check(real.get("trivial_verifier") is False,
          f"a real verifier is not flagged trivial (got {real.get('trivial_verifier')})")
    check(real.get("canary_target") == "value.txt"
          and real.get("canary_target_source") == "verifier_reference"
          and real.get("canary_target_reason") == "verifier_named_changed_file",
          "a verifier-named changed file records safe automatic provenance")

    # Opaque verifier: no named changed file means no mutation and no false trivial demotion.
    run("work-log", ["--work-id", wid, "--pathway", "quality", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--proof-type", "artifact", "--project", str(proj),
                     "--verify-cmd", "printf checked"])
    unavailable = [json.loads(l) for l in proofs_file.read_text().splitlines() if l.strip()][-1]
    check(unavailable.get("canary_mutant_failed") is None and unavailable.get("trivial_verifier") is False,
          "an opaque verifier has no mutation result and is not falsely demoted")
    check(unavailable.get("canary_target") is None
          and unavailable.get("canary_target_source") == "unavailable"
          and unavailable.get("canary_target_reason") == "no_relevant_changed_file",
          "an opaque verifier records the unavailable receipt shape")

    # FAKE verifier: an explicit relevant target restores the strict no-op check.
    run("work-log", ["--work-id", wid, "--pathway", "observability", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--proof-type", "artifact", "--project", str(proj),
                     "--verify-cmd", "printf checked", "--canary-target", str(proj / "value.txt")])
    fake = [json.loads(l) for l in proofs_file.read_text().splitlines() if l.strip()][-1]
    check(fake.get("canary_mutant_failed") is False and fake.get("trivial_verifier") is True,
          "an explicit relevant target still flags a verifier that ignores the mutation")
    check(fake.get("canary_target") == "value.txt"
          and fake.get("canary_target_source") == "explicit"
          and fake.get("canary_target_reason") == "explicit_changed_regular_file",
          "an absolute explicit input persists only a repository-relative target")

    check((proj / "value.txt").read_text() == "100\n",
          "canary restores the mutated file byte-for-byte (no working-tree side effects)")
    check((proj / "value.txt").stat().st_mode & 0o777 == 0o755,
          "canary preserves the target's permission bits (mkstemp 0600 must not survive the swap)")


def test_redact_obj_exempts_only_real_sha256_digests():
    """Digest exemption requires BOTH a digest-named key (*_sha256/_digest/_hash/_fingerprint)
    AND a 64-hex value (review-redact-hex64-value-exemption): a *_sha256 key holding a non-digest
    secret fails the value check, and a hex-encoded 256-bit secret (openssl rand -hex 32) under
    any other key fails the key check and is scrubbed by the entropy pattern."""
    opl = load_cli("redact")
    hex_secret = "d" * 64  # same shape as `openssl rand -hex 32`
    out = opl.redact_obj({"artifact_sha256": "a" * 64,
                          "note_sha256": "sk-proj-LEAKED-secret-value-0001",
                          "session_key": hex_secret,
                          "body": "password=hunter2"})
    check(out["artifact_sha256"] == "a" * 64, "a real 64-hex digest under a digest-named key is preserved")
    check("sk-proj-" not in out["note_sha256"] and "LEAKED" not in out["note_sha256"],
          "a *_sha256 key holding a non-digest secret is still redacted")
    check(hex_secret not in out["session_key"],
          "a 64-hex secret under a non-digest key is scrubbed (key+value conjunction)")
    check("hunter2" not in out["body"], "ordinary secret values are unaffected by the exemption")


def test_redaction_covers_bearer_and_provider_prefixed_credentials():
    """Provider keys are often shorter than the entropy fallback, especially in test/dev tiers."""
    reset()
    opl = load_cli("provider_redaction")
    xai_key = "xai-abcdefghijklmnopqrstuvwx123456"
    github_token = "github_pat_abcdefghijklmnopqrstuvwx123456"
    bearer = "Authorization: Bearer bearer_abcdefghijklmnopqrstuvwx123456"
    aws_key = "AKIAIOSFODNN7EXAMPLE"
    google_key = "AIzaSyDUMMYKEYabcdefghijklmnopqrstu1234"
    slack_token = "REDACTED-SLACK-TOKEN"
    stripe_key = "sk_live_abcdefghijklmnop1234"
    raw = (f"{bearer}\nXAI_API_KEY={xai_key}\ngithub={github_token}\n"
           f"aws {aws_key} google {google_key}\nslack {slack_token} stripe {stripe_key}\n")
    redacted = opl.redact(raw)
    check(xai_key not in redacted and github_token not in redacted and "bearer_" not in redacted,
          "provider-prefixed and bearer credentials are redacted in memory")
    check(all(v not in redacted for v in (aws_key, google_key, slack_token, stripe_key)),
          "AWS/Google/Slack/Stripe credential shapes below the entropy floor are redacted")
    output = ROOT / "out" / "operator-intelligence" / "redaction-provider-fixture.json"
    opl.write_json(output, {"payload": raw})
    persisted = output.read_text(encoding="utf-8")
    check(xai_key not in persisted and github_token not in persisted and "bearer_" not in persisted,
          "provider-prefixed and bearer credentials are redacted before persistence")


def test_release_receipt_distinguishes_preview_production_rollback_and_send():
    opl = load_cli("release_receipt")
    preview = {
        "preview_status": "ready", "canary_status": "not-run", "production_status": "not-deployed",
        "rollback_status": "ready", "external_send_state": "not-sent", "feature_flag_state": "disabled",
        "deploy_artifact": "preview-plan.md", "verification_artifact": "preview-check.json",
        "rollback_artifact": "rollback-plan.md", "human_approval": "",
    }
    check(not opl.validate_release_receipt(preview), "preview-ready receipt passes without production mutation")
    missing_rollback = {**preview, "production_status": "deployed", "rollback_status": "ready", "human_approval": "Alex approved"}
    check(any("rollback" in error for error in opl.validate_release_receipt(missing_rollback)),
          "production receipt without rollback rehearsal is rejected")
    send_ready = {**preview, "external_send_state": "send-ready", "claimed_external_send": True}
    check(any("send-ready" in error for error in opl.validate_release_receipt(send_ready))
          and not opl.release_receipt_supports_send(send_ready),
          "send-ready cannot be claimed as sent")
    production = {**preview, "production_status": "deployed", "rollback_status": "rehearsed", "human_approval": "Alex approved", "external_send_state": "sent"}
    check(not opl.validate_release_receipt(production) and opl.release_receipt_supports_send(production),
          "production receipt needs approval and rollback evidence before it can claim sent")


def test_verifier_templates_reject_hollow_artifacts_and_accept_complete_contracts():
    opl = load_cli("verifier_templates")
    required = {"govern", "research", "data", "security", "design", "implementation", "quality", "field", "observability", "techdebt", "release", "docs"}
    check(set(opl.VERIFIER_TEMPLATES) == required, "every core pathway and field has a verifier template")
    baton = "\n".join([
        "## Summary\n- checked", "## What Changed\n- changed", "## More Relevant\n- relevant",
        "## Less Relevant\n- deferred", "## Next Pathway Must Use\n- use this",
        "## Do Not Do Yet\n- no mutation", "## Open Decisions\n- none", "## Active Risk Overlays\n- rollback",
    ])
    for pathway, spec in opl.VERIFIER_TEMPLATES.items():
        hollow = opl.check_verifier_template(pathway, "")
        complete = opl.check_verifier_template(pathway, baton + "\n" + "\n".join(spec["required_artifact_terms"]))
        check(not hollow["valid"] and complete["valid"], f"{pathway} template rejects hollow artifacts and accepts its contract")


def test_audit_proof_integrity_uses_active_outcomes_and_reports_history():
    opl = load_cli("audit_proof_scope")
    active = {"work_id": "active", "verifier_strength": "executed", "exit_code": 0, "trivial_verifier": False, "canary_mutant_failed": None, "result": "pass"}
    historical = {"work_id": "old", "verifier_strength": "attested", "exit_code": None, "trivial_verifier": False, "canary_mutant_failed": None, "result": "pass"}
    snapshot = opl.audit_proof_integrity_snapshot([active, historical], ["active"])
    check(snapshot["scope"] == "active outcomes" and snapshot["verified_count"] == 1 and snapshot["proof_count"] == 1,
          "audit proof integrity measures current active outcomes")
    check(snapshot["historical_unverified_count"] == 1,
          "audit retains historical unverified proof hygiene as a separate signal")


def test_canary_mutant_is_symlink_safe():
    """Safety (Codex High): the canary must never follow a symlink in the changed set and mutate an
    external target. A symlinked changed file is refused (None) and outside files stay untouched."""
    import subprocess as sp
    reset()
    opl = load_cli("canarysafe")
    proj = ROOT / "canarysafe"
    proj.mkdir(parents=True, exist_ok=True)
    outside = ROOT / "OUTSIDE.txt"
    outside.write_text("DO NOT TOUCH\n")
    def git(*a): sp.run(["git", "-C", str(proj)] + list(a), capture_output=True, text=True)
    git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    (proj / "link").symlink_to(outside)
    git("add", "-A"); git("commit", "-q", "-m", "base")
    # Re-point the tracked symlink -> a changed line whose target is an external file.
    (proj / "link").unlink()
    (ROOT / "OTHER.txt").write_text("other\n")
    (proj / "link").symlink_to(ROOT / "OTHER.txt")
    res = opl.run_canary_mutant("printf ok", str(proj), canary_target="link")
    check(res is None, "canary refuses a symlinked changed file (returns None, no external write)")
    check(outside.read_text() == "DO NOT TOUCH\n", "the original symlink target is never mutated")


def test_canary_explicit_target_rejects_outside_and_unchanged_files():
    """Explicit targets are strict, not an escape hatch: neither an outside file nor an unchanged
    in-repository file may be mutated or persisted as a canary target."""
    import subprocess as sp
    reset()
    repo = ROOT / "canary-boundary"
    repo.mkdir(parents=True, exist_ok=True)
    outside = ROOT / "OUTSIDE-EXPLICIT.txt"
    outside.write_text("DO NOT TOUCH\n", encoding="utf-8")
    def git(*a): sp.run(["git", "-C", str(repo)] + list(a), capture_output=True, text=True)
    git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    (repo / "value.txt").write_text("42\n", encoding="utf-8")
    (repo / "unchanged.txt").write_text("stable\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-q", "-m", "base")
    (repo / "value.txt").write_text("100\n", encoding="utf-8")
    ev = write("out/operator-artifacts/canary-boundary-proof.md", "proof\n")
    start, _ = run("work-start", ["--project", str(repo), "--goal", "canary explicit boundaries"])
    wid = start["work_id"]
    proofs_file = ROOT / "out" / "operator-intelligence" / "proofs.ndjson"
    common = ["--work-id", wid, "--proof-type", "artifact", "--result", "pass", "--evidence", str(ev),
              "--verify-cmd", "printf checked"]

    run("proof-add", common + ["--pathway", "quality", "--canary-target", str(outside)])
    outside_proof = [json.loads(l) for l in proofs_file.read_text().splitlines() if l.strip()][-1]
    check(outside_proof.get("canary_target") is None
          and outside_proof.get("canary_target_source") == "unavailable"
          and outside_proof.get("canary_target_reason") == "explicit_target_outside_verification_checkout",
          "an outside explicit target is unavailable and carries no persisted path")
    check(str(outside) not in json.dumps(outside_proof), "an outside absolute target is not leaked into the proof receipt")
    check(outside.read_text(encoding="utf-8") == "DO NOT TOUCH\n", "an outside explicit target is never mutated")

    run("proof-add", common + ["--pathway", "observability", "--canary-target", "unchanged.txt"])
    unchanged_proof = [json.loads(l) for l in proofs_file.read_text().splitlines() if l.strip()][-1]
    check(unchanged_proof.get("canary_target") is None
          and unchanged_proof.get("canary_target_source") == "unavailable"
          and unchanged_proof.get("canary_target_reason") == "explicit_target_not_changed_regular_file",
          "an unchanged explicit target is unavailable rather than falling back to a changed file")
    check(unchanged_proof.get("canary_mutant_failed") is None and unchanged_proof.get("trivial_verifier") is False,
          "unavailable explicit targets do not produce false trivial-verifier results")
    check((repo / "unchanged.txt").read_text(encoding="utf-8") == "stable\n",
          "an unchanged explicit target is never mutated")


def test_canary_mutant_resolves_repo_root_from_subdir():
    """Correctness (GLM): git diff paths are repo-root-relative. When the verifier cwd is a SUBDIR
    of the repo, the canary must resolve the changed file against the repo root, not the subdir."""
    import subprocess as sp
    reset()
    opl = load_cli("canarysub")
    repo = ROOT / "subrepo"
    (repo / "sub").mkdir(parents=True, exist_ok=True)
    def git(*a): sp.run(["git", "-C", str(repo)] + list(a), capture_output=True, text=True)
    git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    (repo / "value.txt").write_text("42\n")
    git("add", "-A"); git("commit", "-q", "-m", "base")
    (repo / "value.txt").write_text("100\n")  # changed file at the repo ROOT
    res = opl.run_canary_mutant("grep 100 ../value.txt", str(repo / "sub"))
    check(res is True, f"canary resolves the repo-root changed file from a subdir cwd (got {res})")
    check((repo / "value.txt").read_text() == "100\n", "the repo-root file is restored after the canary")


def test_canary_selects_relevant_target_in_dirty_registered_checkout():
    """Regression: unrelated dirty files must no longer be selected before a verifier-named changed
    file. Opaque commands remain unavailable, while an explicit target retains the strict no-op
    check. The registered project identity stays intact throughout."""
    import subprocess as sp
    reset()
    dirty = ROOT / "projects" / "canarydirty"
    dirty.mkdir(parents=True, exist_ok=True)
    def git(*a): sp.run(["git", "-C", str(dirty)] + list(a), capture_output=True, text=True)
    git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    (dirty / "unrelated.yml").write_text("jobs: e2e\n")
    (dirty / "value.txt").write_text("42\n")
    git("add", "-A"); git("commit", "-q", "-m", "baseline")
    (dirty / "value.txt").write_text("100\n")  # the artifact change, committed (merged PR)
    git("add", "-A"); git("commit", "-q", "-m", "artifact")
    (dirty / "unrelated.yml").write_text("jobs: e2e-stale\n")  # broad unrelated dirt on the checkout
    ev = write("out/operator-artifacts/dirty-canary-proof.md", "proof\n")
    start, _ = run("work-start", ["--project", str(dirty), "--goal", "dirty checkout canary"])
    wid = start["work_id"]
    proofs_file = ROOT / "out" / "operator-intelligence" / "proofs.ndjson"
    common = ["--work-id", wid, "--gate", "canary-gate", "--proof-type", "artifact",
              "--result", "pass", "--evidence", str(ev)]

    run("proof-add", common + ["--pathway", "govern", "--verify-cmd", "grep 100 value.txt"])
    named = [json.loads(l) for l in proofs_file.read_text().splitlines() if l.strip()][-1]
    check(named.get("canary_mutant_failed") is True and named.get("trivial_verifier") is False,
          "a dirty registered checkout selects the verifier-named changed file")
    check(named.get("canary_target") == "value.txt" and named.get("canary_target_source") == "verifier_reference",
          "automatic selection records only the relevant repository-relative file")

    run("proof-add", common + ["--pathway", "quality", "--verify-cmd", "printf checked"])
    opaque = [json.loads(l) for l in proofs_file.read_text().splitlines() if l.strip()][-1]
    check(opaque.get("canary_mutant_failed") is None and opaque.get("trivial_verifier") is False,
          "unrelated dirty files do not demote an opaque verifier")

    run("proof-add", common + ["--pathway", "observability", "--verify-cmd", "printf checked",
                                "--canary-target", str(dirty / "value.txt")])
    explicit = [json.loads(l) for l in proofs_file.read_text().splitlines() if l.strip()][-1]
    check(explicit.get("canary_mutant_failed") is False and explicit.get("trivial_verifier") is True,
          "an explicit relevant target preserves strict no-op detection")
    check(explicit.get("canary_target") == "value.txt" and not explicit.get("canary_target", "").startswith("/"),
          "an absolute explicit target is normalized before persistence")
    check(named.get("project_path") == str(dirty),
          "the proof's recorded identity still belongs to the work item's registered project")
    opl = load_cli("canaryexplicit")
    check(opl.proof_is_verified(named) is True, "the relevant re-run proof clears proof_is_verified")
    check((dirty / "unrelated.yml").read_text() == "jobs: e2e-stale\n",
          "the dirty checkout's unrelated file is never mutated")


def test_canary_run_guard_skips_trivial_and_slow_verifiers():
    """The canary re-runs the verifier, so it must NOT run when the cheap checks already proved
    trivial, nor when the first verify run was slow (a multi-minute suite must not be doubled)."""
    opl = load_cli("canaryguard")
    check(opl._should_run_canary(False, 0.5) is True, "fast, non-trivial verifier -> run the canary")
    check(opl._should_run_canary(True, 0.5) is False, "already-trivial verifier -> skip the canary")
    check(opl._should_run_canary(False, opl.CANARY_MAX_VERIFY_SECONDS + 1) is False,
          "a verifier slower than the budget -> skip the canary (no doubled runtime)")


def test_proof_canary_observability_report():
    """The local report distinguishes strict results from legacy history and never reprints targets
    or verifier commands, including invalid values supplied in historical input."""
    import subprocess as sp
    reset()
    ledger = ROOT / "proof-canary-observability.ndjson"
    report_path = ROOT / "proof-canary-observability.json"
    rows = [
        {"canary_mutant_failed": True, "verify_command": "secret command"},
        {"canary_mutant_failed": False, "verify_command": "secret command"},
        {
            "canary_target": None,
            "canary_target_source": "unavailable",
            "canary_target_reason": "no_relevant_changed_file",
            "canary_mutant_failed": None,
        },
        {
            "canary_target": "src/check.py",
            "canary_target_source": "explicit",
            "canary_target_reason": "explicit_changed_regular_file",
            "canary_mutant_failed": True,
        },
        {
            "canary_target": "src/check.py",
            "canary_target_source": "verifier_reference",
            "canary_target_reason": "verifier_named_changed_file",
            "canary_mutant_failed": False,
        },
        {
            "canary_target": "/secret/target.py",
            "canary_target_source": "explicit",
            "canary_target_reason": "bad_target",
            "canary_mutant_failed": False,
        },
    ]
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows) + "not-json\n", encoding="utf-8")
    observer = CLI.parent / "proof-canary-observability.py"
    proc = sp.run([sys.executable, str(observer), "--proofs", str(ledger), "--out", str(report_path)],
                  capture_output=True, text=True)
    check(proc.returncode == 0, f"proof-canary observability exits 0 (stderr={proc.stderr!r})")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    counts = report["counts"]
    check(report["status"] == "alert", "ignored strict or legacy canaries raise an alert")
    check(counts["legacy_receipts"] == 2 and counts["legacy_canary_passed"] == 1,
          "legacy true outcomes remain visible without invented provenance")
    check(counts["legacy_canary_ignored"] == 1, "legacy false outcomes remain visible for review")
    check(counts["target_unavailable"] == 1, "unavailable target/result pair is counted separately")
    check(counts["strict_probe_passed"] == 1 and counts["strict_probe_ignored"] == 1,
          "provenance-backed strict results retain their true/false distinction")
    check(counts["invalid_provenance"] == 1 and counts["malformed_rows"] == 1,
          "unsafe target provenance and malformed input are visible without crashing")
    serialized = json.dumps(report)
    check("secret command" not in serialized and "/secret/target.py" not in serialized,
          "the report excludes verifier commands and canary target paths")


def test_cohens_kappa_inter_rater_agreement():
    """Evaluation harness (dossier item 1): Cohen's kappa validates a single judge against the human
    label set before any precision claim is scaled. Hand-computed values pin the formula."""
    opl = load_cli("cohens")
    k = opl.cohens_kappa
    check(abs(k([1, 1, 0, 0], [1, 1, 0, 0]) - 1.0) < 1e-9, "identical raters -> kappa 1.0")
    check(abs(k([1, 1, 1, 0], [1, 1, 0, 0]) - 0.5) < 1e-9, "one disagreement of four -> kappa 0.5")
    check(k([], []) == 0.0, "no items -> 0.0 (nothing to measure)")
    check(k([1, 0, 1, 0], [0, 1, 0, 1]) < 0, "systematic disagreement -> negative kappa (worse than chance)")


def test_fleiss_kappa_multi_rater_agreement():
    """Fleiss' kappa measures agreement ACROSS the jury (n raters). Counts matrix = items x
    categories. Hand-computed cases pin the formula."""
    opl = load_cli("fleiss")
    f = opl.fleiss_kappa
    check(abs(f([[3, 0], [3, 0], [0, 3]]) - 1.0) < 1e-9, "unanimous on every item -> kappa 1.0")
    check(abs(f([[2, 1], [1, 2], [3, 0]]) - 0.0) < 1e-9, "agreement equal to chance -> kappa 0.0")
    check(f([]) == 0.0, "no items -> 0.0")
    check(f([[3, 0], [1, 0]]) == 0.0, "inconsistent raters-per-item -> 0.0 (cannot compute Fleiss)")
    check(f([[2, 1], [1]]) == 0.0, "ragged rows -> 0.0 (no crash)")


def test_kappa_reliability_thresholds():
    """The dossier's go/no-go: kappa<0.4 unreliable, 0.4-0.6 moderate, >=0.6 trustworthy enough
    to scale a precision claim."""
    opl = load_cli("kappathresh")
    r = opl.kappa_reliability
    check(r(0.3) == "unreliable", "kappa<0.4 is unreliable (do not scale precision claims)")
    check(r(0.5) == "moderate", "0.4<=kappa<0.6 is moderate")
    check(r(0.7) == "trustworthy", "kappa>=0.6 is trustworthy enough to scale")


def test_jury_collapses_same_family_votes():
    """The keystone of the jury (dossier item 1): correlated same-family judges collapse to ONE
    effective vote — a jury of one vendor's models is still one judge."""
    opl = load_cli("jury")
    j = opl.jury_verdict
    out = j([{"family": "anthropic", "verdict": "correct"},
             {"family": "openai", "verdict": "correct"},
             {"family": "google", "verdict": "wrong"}])
    check(out["verdict"] == "correct" and out["distinct_families"] == 3 and out["family_diverse"] is True,
          "3 distinct families, 2-1 -> correct verdict + diverse")
    same = j([{"family": "anthropic", "verdict": "correct"},
              {"family": "anthropic", "verdict": "correct"},
              {"family": "anthropic", "verdict": "wrong"}])
    check(same["distinct_families"] == 1 and same["effective_votes"] == 1 and same["family_diverse"] is False,
          "a jury of one vendor's models is still one judge (effective_votes=1, not diverse)")
    tie = j([{"family": "anthropic", "verdict": "correct"}, {"family": "openai", "verdict": "wrong"}])
    check(tie["verdict"] is None, "an even split across families yields no majority verdict")
    plurality = j([{"family": "anthropic", "verdict": "correct"}, {"family": "openai", "verdict": "correct"},
                   {"family": "google", "verdict": "wrong"}, {"family": "meta", "verdict": "late"}])
    check(plurality["verdict"] is None, "2 of 4 families is a plurality, not a majority -> no verdict")
    unknownfam = j([{"family": "anthropic", "verdict": "correct"}, {"family": "unknown", "verdict": "correct"},
                    {"family": "?", "verdict": "wrong"}])
    check(unknownfam["family_diverse"] is False, "unknown/unlabeled families do not count toward jury diversity")


def test_position_swap_and_rubric_fingerprint():
    """Bias controls: position-swap requires both orders to agree (else position bias, no verdict);
    the rubric fingerprint pins rubric + model ids so judge/rubric drift is detectable."""
    opl = load_cli("biasctl")
    check(opl.position_swap_resolve("A", "A") == "A", "both orders agree -> the agreed verdict stands")
    check(opl.position_swap_resolve("A", "B") is None, "orders disagree -> position bias, no verdict")
    fp1 = opl.rubric_fingerprint("rubric v1", ["claude-x", "gpt-y"])
    fp2 = opl.rubric_fingerprint("rubric v1", ["gpt-y", "claude-x"])
    fp3 = opl.rubric_fingerprint("rubric v2", ["claude-x", "gpt-y"])
    check(fp1 == fp2 and len(fp1) == 64, "fingerprint is order-independent over model ids, 64-hex")
    check(fp1 != fp3, "a rubric change changes the fingerprint (drift detection)")


def test_pathway_evaluate_records_independent_verdicts_and_precision():
    """Breaks circular validation: pathway-evaluate records an INDEPENDENT judge's verdict on each
    recommendation (correct/wrong/...), and --summary reports precision (correct/total) — the first
    non-self signal that the picks are actually good, not just that the tool tracked its own work."""
    reset()
    write("projects/consult-ops/README.md", "# ConsultOps\n")
    proj = str(ROOT / "projects" / "consult-ops")
    rec, _ = run("pathway-next", ["--project", proj])
    rid, pathway = rec["recommendation_id"], rec["recommended_pathway"]

    out, proc = run("pathway-evaluate", ["--recommendation-id", rid, "--project", "consult-ops",
                    "--pathway", pathway, "--verdict", "correct", "--judge", "glm-5.2",
                    "--counterfactual", pathway, "--note", "matches the senior-engineer pick"])
    check(proc.returncode == 0, "pathway-evaluate exits 0")
    check(any(r.get("verdict") == "correct" for r in out.get("records", [])), "pathway-evaluate records the verdict")

    # A bad verdict is rejected (only the known verdict vocabulary is accepted).
    bad, _ = run("pathway-evaluate", ["--project", "consult-ops", "--pathway", "docs", "--verdict", "meh", "--judge", "x"])
    check("pathway-evaluate-bad-verdict" in ids(bad), "an unknown verdict is rejected")

    # Second (independent) verdict: wrong.
    run("pathway-evaluate", ["--project", "consult-ops", "--pathway", "docs", "--verdict", "wrong",
                             "--judge", "glm-5.2", "--counterfactual", "security", "--note", "missed the real blocker"])
    summ, _ = run("pathway-evaluate", ["--summary"])
    m = summ["summary"]
    check(m["total"] == 2 and m["correct"] == 1, f"summary counts the recorded verdicts (got {m})")
    check(abs(m["precision"] - 0.5) < 1e-9, f"precision = correct/total (got {m['precision']})")
    check(m.get("family_diverse") is False and str(m.get("precision_claim_status", "")).startswith("unvalidated"),
          "two same-family judges -> precision is an UNVALIDATED claim, not a 3-family jury")
    check(m["external_projects_judged"] >= 1, "external (non-self) projects are counted")
    check(Path(summ.get("report", "")).exists(), "pathway-evaluate --summary writes a report artifact")


def test_recommender_engages_findings_over_foundation_on_untracked_project():
    """Recommender fix for the 0/3 external-precision failure: on an UNTRACKED project that carries
    real findings, pathway-next must engage the findings, not bury them under a foundation gate
    (govern/research). And confidence must be LOW when there is zero project signal — never the
    content-free medium that the foundation-gate score inflation used to produce."""
    reset()
    # A) untracked project WITH real findings -> the finding's pathway wins, not govern/research.
    proj = ROOT / "projects" / "findproj"
    (proj / ".planning").mkdir(parents=True, exist_ok=True)
    (proj / "package.json").write_text('{"name":"findproj"}\n', encoding="utf-8")
    (proj / ".planning" / "findings.json").write_text(json.dumps([
        {"id": "sec1", "message": "anon read exposed on a tenant table", "severity": "error", "pathway": "security"},
        {"id": "sec2", "message": "service-role key shipped in the client bundle", "severity": "error", "pathway": "security"},
    ]), encoding="utf-8")
    rec, _ = run("pathway-next", ["--project", str(proj)])
    check(rec.get("recommended_pathway") == "security",
          f"an untracked project with error findings recommends the finding's pathway, not a foundation gate (got {rec.get('recommended_pathway')})")
    check(rec.get("recommendation_confidence", {}).get("level") != "low",
          "a finding-backed pick is not low confidence")

    # B) untracked project with NO signal -> confidence is LOW (never the content-free medium default).
    bare = ROOT / "projects" / "bareproj"
    bare.mkdir(parents=True, exist_ok=True)
    (bare / "README.md").write_text("# bare\n", encoding="utf-8")
    rec2, _ = run("pathway-next", ["--project", str(bare)])
    check(rec2.get("recommendation_confidence", {}).get("level") == "low",
          f"zero project signal must yield LOW confidence, never medium (got {rec2.get('recommendation_confidence', {}).get('level')})")


def test_learning_dampener_never_suppresses_a_pathway_with_live_findings():
    """Learning-loop safety (audit P1): a pathway proved-and-closed before is dampened — UNLESS it
    carries a live finding/control THIS turn. An always-needed pathway like security with a current
    warning must never be pushed down the ranking by past closures."""
    reset()
    proj = ROOT / "projects" / "secproj"
    (proj / ".planning").mkdir(parents=True, exist_ok=True)
    (proj / "package.json").write_text('{"name":"secproj"}\n', encoding="utf-8")
    (proj / ".planning" / "findings.json").write_text(json.dumps([
        {"id": "sec-warn", "message": "anon policy too broad on a tenant table", "severity": "warn", "pathway": "security"},
    ]), encoding="utf-8")
    # 3 prior closes proved BOTH security and docs (both are dampening candidates, -9 each).
    lc = ROOT / "out" / "operator-intelligence" / "learning-candidates.ndjson"
    lc.parent.mkdir(parents=True, exist_ok=True)
    lc.write_text("".join(json.dumps({
        "learning_id": f"L-{i}", "work_id": f"W-{i}", "project": "secproj",
        "project_path": str(proj), "pathways_seen": ["security", "docs"]}) + "\n" for i in range(3)), encoding="utf-8")
    rec, _ = run("pathway-next", ["--project", str(proj)])
    ranked = {r["pathway"]: r for r in rec.get("ranked", [])}
    sec_dampened = any("Demonstrated" in x for x in ranked.get("security", {}).get("reasons", []))
    docs_dampened = any("Demonstrated" in x for x in ranked.get("docs", {}).get("reasons", []))
    check(not sec_dampened, "security (carries a live finding) is NOT dampened by past closures")
    check(docs_dampened, "docs (no live finding) IS still dampened — the guard is selective, not a blanket off-switch")


def main():
    tests = [
        test_source_integrity_no_duplicate_module_level_names,
        test_test_runner_integrity_detects_unregistered_tests,
        test_intel_detection_and_clean,
        test_tools_detection_and_clean,
        test_portfolio_evidence_ai_boundary_agent_cards,
        test_agent_cards_reject_symlinked_candidates_and_markers,
        test_agent_cards_scope_excludes_helper_and_legacy_records,
        test_all_smoke_outputs_parse_and_redact,
        test_improve_and_compare_control_loop,
        test_daily_work_envelope_and_pathway_cooperation,
        test_daily_work_stale_measurement_detection,
        test_work_close_extracts_learning_candidate,
        test_pathway_trust_report_and_pathway_next_metadata,
        test_pathway_next_recommendation_and_cohesion,
        test_pathway_next_scores_only_selected_active_work,
        test_selected_work_scoring_regression_kills_aggregate_mutant,
        test_pathway_carry_forward_logged_and_used_by_next,
        test_carry_forward_deferrals_do_not_trigger_false_risk_overlays,
        test_carry_forward_validation_requires_full_contract,
        test_outcome_profiles_risk_overlays_and_field_gate,
        test_closeout_router_ready_to_close_and_work_close_receipts,
        test_pathway_run_creates_plan_and_preserves_project,
        test_pathway_pilot_tracks_agentic_team_cohort,
        test_pathway_pilot_logs_one_recommendation_per_enrollment,
        test_portfolio_next_ranks_riskier_project_first,
        test_rule_map_names_enforced_and_prose_only_rules,
        test_cockpit_writes_one_page_operator_surface,
        test_cockpit_surfaces_trivial_verifier_count,
        test_pfos_cockpit_snapshot_export_is_browser_safe,
        test_ingest_review_closes_loop,
        test_ingest_review_schema_contract,
        test_ingest_review_malformed_and_empty,
        test_stale_review_gate,
        test_pathway_metric,
        test_pathway_audit_is_read_only_explainable_and_below_target_is_not_an_error,
        test_proof_registry_and_proved_metric,
        test_project_scoping_no_substring_bleed,
        test_pathway_execution_profile_invariants,
        test_itinerary_coverage_guarantee,
        test_proof_add_flips_itinerary_coverage,
        test_proof_requires_verifier_not_just_presence,
        test_recommendation_confidence_reflects_evidence,
        test_recommendation_follows_evidence_within_itinerary,
        test_wilson_lower_bound_gates_small_n,
        test_wilson_jeffreys_cross_check,
        test_autonomy_gate_rate_enforces_min_n_floor,
        test_suggested_autonomy_tier_gates_on_proof_trust_confidence,
        test_learning_loop_closed_outcomes_reweight_rankings,
        test_tier_calibration_measures_defaults_from_closed_outcomes,
        test_proof_requires_real_verifier_not_freetext,
        test_autonomy_metric_counts_only_verified_proofs,
        test_trivial_verifier_does_not_prove_or_close,
        test_verifier_receipt_flags_trivial_command,
        test_verifier_receipt_canary_mutant_catches_noop_verifier,
        test_redact_obj_exempts_only_real_sha256_digests,
        test_redaction_covers_bearer_and_provider_prefixed_credentials,
        test_release_receipt_distinguishes_preview_production_rollback_and_send,
        test_verifier_templates_reject_hollow_artifacts_and_accept_complete_contracts,
        test_audit_proof_integrity_uses_active_outcomes_and_reports_history,
        test_canary_mutant_is_symlink_safe,
        test_canary_explicit_target_rejects_outside_and_unchanged_files,
        test_canary_mutant_resolves_repo_root_from_subdir,
        test_canary_selects_relevant_target_in_dirty_registered_checkout,
        test_canary_run_guard_skips_trivial_and_slow_verifiers,
        test_proof_canary_observability_report,
        test_cohens_kappa_inter_rater_agreement,
        test_fleiss_kappa_multi_rater_agreement,
        test_kappa_reliability_thresholds,
        test_jury_collapses_same_family_votes,
        test_position_swap_and_rubric_fingerprint,
        test_pathway_evaluate_records_independent_verdicts_and_precision,
        test_recommender_engages_findings_over_foundation_on_untracked_project,
        test_learning_dampener_never_suppresses_a_pathway_with_live_findings,
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
