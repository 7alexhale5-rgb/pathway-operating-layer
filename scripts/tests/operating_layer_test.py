#!/usr/bin/env python3
"""
operating_layer_test.py - self-test suite for operating-layer.py.

Stdlib only. Run: python3 ~/.claude/scripts/tests/operating_layer_test.py
Exit 0 = all pass; non-zero = failures.
"""
import ast
import atexit
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path


HERE = Path(__file__).resolve().parent
CLI = (HERE / ".." / "operating-layer.py").resolve()
REPO = HERE.parent.parent
APPROVAL_GUARD = REPO / "hooks" / "approval-issue-guard.py"
APPROVAL_GUARD_VERIFIER = REPO / "scripts" / "verify-approval-issue-guard.py"
APPROVAL_HELPER_SOURCE = REPO / "security" / "pathway-approval"
INSTALLER = REPO / "install.sh"
APPROVAL_GUARD_DENIAL = (
    "DENIED: live approval authority is OS-owned. Review the exact helper command, "
    "then run it with fresh sudo authentication in Alex's normal Terminal.\n"
)
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
    ROOT.chmod(0o700)
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


def passing_verifier_cmd(*args, name="pass.py"):
    verifier = write(
        f"out/test-verifiers/{name}",
        "print('GENERIC_TEST_VERIFIER=PASS')\n",
    )
    return " ".join(
        shlex.quote(value)
        for value in [sys.executable, "-B", str(verifier), *(str(arg) for arg in args)]
    )


def failing_verifier_cmd(name="fail.py"):
    verifier = write(
        f"out/test-verifiers/{name}",
        "print('GENERIC_TEST_VERIFIER=FAIL')\nraise SystemExit(7)\n",
    )
    return " ".join(shlex.quote(value) for value in (sys.executable, "-B", str(verifier)))


def text_guard_verifier_cmd(target, expected, name="text-guard.py"):
    verifier = write(
        f"out/test-verifiers/{name}",
        "from pathlib import Path\n"
        "import sys\n"
        "if Path(sys.argv[1]).read_text(encoding='utf-8').strip() != sys.argv[2]:\n"
        "    raise SystemExit(7)\n"
        "print('GENERIC_TEST_VERIFIER=PASS')\n",
    )
    return " ".join(
        shlex.quote(str(value))
        for value in (sys.executable, "-B", verifier, target, expected)
    )


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


def run_approval_guard(payload, env=None, raw=False):
    hook_env = os.environ.copy()
    if env:
        hook_env.update(env)
    hook_input = payload if raw else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(APPROVAL_GUARD)],
        input=hook_input,
        capture_output=True,
        text=True,
        timeout=5,
        env=hook_env,
    )


def assert_no_secret_output(text, label):
    lowered = text.lower()
    check("sk-proj-" not in text and "password=hunter2" not in lowered and "api_key=abc" not in lowered, label)



def test_observability_contract_loader_fails_closed_and_gates_schema():
    reset()
    opl = load_cli("observability_contract_loader")
    contracts_dir = opl.observability_contracts_dir()
    check(contracts_dir is not None and contracts_dir.is_dir(),
          "the engine resolves a contained contracts/observability directory")
    check(opl.OBSERVABILITY_DEFAULT_CONTRACT_ERRORS == [],
          "the shipped rainman-thorp contract passes the schema gate")
    contract, errors = opl.load_observability_contract_file(contracts_dir / "rainman-thorp.json")
    check(not errors and contract.get("project_key") == "rainman-thorp",
          "the rainman-thorp contract loads with its project_key intact")
    check(opl.OBSERVABILITY_RUNTIME_VERIFIER_TRUST_STATE == "TRUSTED_VERIFIER_NOT_CONFIGURED"
          and opl.OBSERVABILITY_TRUSTED_VERIFIER_SHA256 == frozenset(),
          "an empty trusted-sha list derives the unconfigured trust state")

    _, errors = opl.load_observability_contract_file(ROOT / "projects" / "absent-contract.json")
    check(errors == ["observability_contract_not_registered"],
          "a missing contract file refuses with the registration error")

    def gate(mutated):
        return opl.validate_observability_contract(mutated)

    mutated = dict(contract); mutated.pop("metric_names")
    check(any("missing required key metric_names" in error for error in gate(mutated)),
          "a contract missing a required enum key is refused (no .get defaults)")
    mutated = dict(contract); mutated["schema_version"] = 1.0
    check(any("schema_version must be integer 1" in error for error in gate(mutated)),
          "a numerically equal float cannot satisfy the integer schema version")
    mutated = dict(contract); mutated["metric_names"] = []
    check(any("needs at least" in error for error in gate(mutated)),
          "an empty required enum fails the cardinality floor")
    mutated = dict(contract); mutated["event_names"] = ["*", "abc", "tradebot.ok.event"]
    check(any("quality gate" in error for error in gate(mutated)),
          "glob or members shorter than four characters fail the member quality gate")
    mutated = dict(contract)
    mutated["event_names"] = list(contract["event_names"]) + [contract["event_names"][0]]
    check(any("must not contain duplicates" in error for error in gate(mutated)),
          "duplicate enum members are refused")
    mutated = dict(contract); mutated["trusted_verifier_sha256"] = ["not-a-digest"]
    check(any("trusted_verifier_sha256" in error for error in gate(mutated)),
          "a malformed trusted-verifier digest is refused")
    mutated = dict(contract); mutated["correlation_hash_fields"] = ["field_outside_set"]
    check(any("subset of correlation_fields" in error for error in gate(mutated)),
          "hash fields outside correlation_fields are refused")

    mutated = dict(contract); mutated["allowed_modes"] = "SIMULATE_ONLY"
    check(any("allowed_modes must be a list of strings" in error for error in gate(mutated)),
          "a scalar enum list is refused without crashing the schema gate")
    mutated = dict(contract); mutated["event_names"] = [["unhashable"], "tradebot.ok.event"]
    check(any("event_names must be a list of strings" in error for error in gate(mutated)),
          "an unhashable enum member is refused without crashing the schema gate")

    qid = "CURRENT_AUTHORIZED_STAGE_AND_MODE"
    mutated = json.loads(json.dumps(contract))
    mutated["runbook_answer_contract"][qid]["fields"]["mode"] = "unchecked_kind"
    check(any("runbook_answer_contract" in error for error in gate(mutated)),
          "an unknown runbook fact kind fails closed")
    mutated = json.loads(json.dumps(contract))
    mutated["runbook_evidence_fields"].append("phantom_artifact")
    mutated["runbook_answer_contract"][qid]["evidence"] = ["phantom_artifact"]
    check(any("artifact inventory" in error for error in gate(mutated)),
          "a phantom runbook evidence field outside the receipt inventory is refused")
    mutated = json.loads(json.dumps(contract))
    mutated["runbook_answer_contract"][qid]["evidence"] = ["log_artifact", "log_artifact"]
    check(any("runbook_answer_contract" in error for error in gate(mutated)),
          "duplicate runbook evidence references are refused")
    mutated = json.loads(json.dumps(contract))
    mutated["runbook_enum_values"].pop("next_action")
    check(any("enum facts" in error for error in gate(mutated)),
          "every enum fact is bound to an exact runbook_enum_values entry")

    mutated = json.loads(json.dumps(contract))
    mutated["drill_incident"] = {"unrelated": None}
    check(any("five canonical incident fields" in error for error in gate(mutated)),
          "a nullable unrelated field cannot erase the drill predicate")
    for field, malformed in (("event_name", []), ("asset", {})):
        mutated = json.loads(json.dumps(contract))
        mutated["drill_incident"][field] = malformed
        check(any("five canonical incident fields" in error for error in gate(mutated)),
              f"an unhashable nested drill {field} is refused without crashing")
    mutated = json.loads(json.dumps(contract)); mutated["drill_alert"]["status"] = "OPEN"
    check(any("drill_alert" in error for error in gate(mutated)),
          "FIRED remains an engine-required alert invariant")

    for label, bounds in (
        ("null lower bound", [None, 1]),
        ("boolean lower bound", [False, 1]),
        ("boolean upper bound", [0, True]),
        ("reversed bounds", [2, 1]),
    ):
        mutated = json.loads(json.dumps(contract))
        mutated["metric_domains"]["tradebot_drawdown_ratio"] = bounds
        check(any("metric_domains" in error for error in gate(mutated)),
              f"{label} is refused before metric sample validation")

    oversized = write("projects/oversized-contract.json",
                      json.dumps(contract) + " " * (opl.OBSERVABILITY_CONTRACT_MAX_BYTES + 1))
    _, errors = opl.load_observability_contract_file(oversized)
    check(any("byte limit" in error for error in errors),
          "an oversized contract file is refused before parsing")

    real = write("projects/real-contract.json", json.dumps(contract))
    link = ROOT / "projects" / "link-contract.json"
    link.symlink_to(real)
    _, errors = opl.load_observability_contract_file(link)
    check(errors == ["observability contract must not be a symlink"],
          "a symlinked contract file is refused")

    opl.OBSERVABILITY_DEFAULT_CONTRACT_ERRORS = ["induced load failure"]
    refusal = opl.validate_observability_runtime_receipt({"schema_version": 1})
    check(bool(refusal) and refusal[0].startswith("observability_contract_not_registered"),
          "a broken default contract makes receipt validation refuse outright")
    refusal = opl._validate_observability_json_artifact(
        "metric_artifact", ROOT / "projects" / "absent.json", {}
    )
    check(bool(refusal) and refusal[0].startswith("observability_contract_not_registered"),
          "a broken default contract makes artifact validation refuse outright")


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
        "--proof-type", "artifact", "--verified-by", "python3 quality-guard.py", "--verify-cmd", passing_verifier_cmd(),
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
    check(trust.get("status") in {"pass", "warn"},
          f"pathway-trust has no functional failure (got {trust.get('status')})")
    check(Path(trust.get("report", "")).exists() and Path(trust.get("html", "")).exists(),
          "pathway-trust writes markdown and html")
    trust_json = ROOT / "out" / "operator-intelligence" / "pathway-trust.json"
    check(trust_json.exists(), "pathway-trust writes operator-intelligence JSON")

    rec, _proc = run("pathway-next", ["--project", project_path])
    check(rec.get("pathway_trust", {}).get("status") == trust.get("status"),
          "pathway-next includes latest pathway-trust status")
    check(rec.get("recommendation_confidence", {}).get("level") in {"high", "medium", "low"},
          "pathway-next includes recommendation confidence level")
    report_text = Path(rec["report"]).read_text(encoding="utf-8")
    check("## Pathway Trust" in report_text
          and f"Status:** `{trust.get('status')}`" in report_text,
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
                     "--proof-type", "artifact", "--verify-cmd", passing_verifier_cmd()])
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
        data["proofs"].append({
            "proof_id": "P-selected-quality",
            "run_id": "R-selected-quality",
            "work_id": "W-selected",
            "pathway": "quality",
            "result": "pass",
            "verifier_strength": "executed",
            "exit_code": 0,
            "trivial_verifier": False,
            "canary_mutant_failed": None,
            "timestamp": opl.iso_now(),
            "stale_after_days": 3650,
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
                                 "--verify-cmd", passing_verifier_cmd()])
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
                     "--verify-cmd", passing_verifier_cmd()])
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
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    subprocess.run(["git", "-C", str(proj), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(proj), "config", "user.name", "Pathway Test"], check=True)
    release_guard = proj / "release-guard.txt"
    release_guard.write_text("BASELINE\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(proj), "add", "release-guard.txt"], check=True)
    subprocess.run(["git", "-C", str(proj), "commit", "-q", "-m", "fixture baseline"], check=True)
    release_guard.write_text("PRODUCTION_RELEASE_READY\n", encoding="utf-8")
    release_recommendation_id = "REC-release-carry-fixture"
    release_now = opl.utc_now()
    release_receipt = write("out/operator-artifacts/release-carry.json", json.dumps({
        "work_id": wid,
        "recommendation_id": release_recommendation_id,
        "target_project": str(proj.resolve()),
        "issued_at": release_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (release_now + opl.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "release_decision": {
            "decision": "RELEASE", "release_gate": "PASS", "pathway_result": "PASS",
            "deployed": True, "production_mutation_performed": True,
            "current_authorized_stage": "PRODUCTION",
        },
        "release_receipt": {
            "preview_status": "ready", "canary_status": "passed", "production_status": "deployed",
            "rollback_status": "rehearsed", "external_send_state": "not-sent",
            "feature_flag_state": "disabled", "deploy_artifact": "deploy.json",
            "verification_artifact": "verification.json", "canary_artifact": "canary.json",
            "rollback_artifact": "rollback.json", "human_approval": "fixture approval",
        },
    }))
    for artifact_name in ("deploy.json", "verification.json", "canary.json", "rollback.json"):
        write(f"out/operator-artifacts/{artifact_name}", json.dumps({"fixture": artifact_name}))
    receipt_sha = opl.sha256_file(release_receipt)
    release_verify = (
        "grep PRODUCTION_RELEASE_READY release-guard.txt && "
        "printf 'RELEASE_DECISION=RELEASE\\nRELEASE_GATE=PASS\\nPATHWAY_RESULT=PASS\\nPRODUCTION_STATUS=DEPLOYED\\n"
        "CANARY_STATUS=PASSED\\nROLLBACK_STATUS=REHEARSED\\n"
        "EXTERNAL_SEND_STATUS=NOT_SENT\\nEXTERNAL_SEND_COUNT=0\\n"
        f"RELEASE_RECEIPT_SHA256={receipt_sha}\\n'"
    )
    logged_release, _ = run("work-log", ["--work-id", wid, "--pathway", "release", "--kind", "verify",
                                  "--evidence", str(release_evidence), "--result", "pass", "--proof-type", "artifact",
                                  "--project", str(proj), "--verify-cmd", release_verify,
                                  "--canary-target", str(release_guard),
                                  "--recommendation-id", release_recommendation_id])
    release_proof_id = next(r["proof_id"] for r in logged_release["records"] if r.get("proof_id"))
    persisted_release_proof = next(
        json.loads(line)
        for line in (ROOT / "out/operator-intelligence/proofs.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("proof_id") == release_proof_id
    )
    check(
        persisted_release_proof["release_verifier_markers"]["RELEASE_RECEIPT_SHA256"]
        == persisted_release_proof["release_receipt_sha256"],
        "persisted release proof retains the exact verifier-to-receipt digest binding",
    )
    check(not load_cli("release_persisted_credit").proof_is_verified(persisted_release_proof),
          "persisted free-text approval cannot manufacture production release credit")
    rec2, _ = run("pathway-next", ["--project", str(proj)])
    check(rec2.get("recommended_pathway") != "release",
          "unverified production release evidence does not close or repeat release")


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
                         "--verify-cmd", passing_verifier_cmd()])
    run("work-log", ["--work-id", wid, "--pathway", "security", "--kind", "verify",
                     "--evidence", str(security_ev), "--result", "pass", "--proof-type", "artifact",
                     "--verify-cmd", passing_verifier_cmd()])

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
                         "--verify-cmd", passing_verifier_cmd()])
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
                     "--verify-cmd", passing_verifier_cmd()])
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
                         "--verify-cmd", passing_verifier_cmd()])
    partial, _ = run("pathway-next", ["--project", str(proj)])
    check(partial.get("ready_to_close") is False,
          "pathway-next is not ready-to-close while a required pathway is still owed")
    check("work-log" in partial.get("next_command", ""),
          "pathway-next still routes to work-log while coverage is open")

    # Cover the last pathway: explicit ready-to-close result routing to work-close.
    run("work-log", ["--work-id", wid, "--pathway", required[-1], "--kind", "verify",
                     "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact",
                     "--verify-cmd", passing_verifier_cmd()])

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
    silent = write("out/test-verifiers/silent.py", "pass\n")
    run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--proof-type", "artifact", "--verify-cmd",
                     f"{sys.executable} -B {silent}"])
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
    start, _proc = run("work-start", ["--project", project_path, "--goal", "Prove PFOS cockpit", "--tier", "live"])
    run("work-log", [
        "--work-id", start["work_id"], "--pathway", rec["recommended_pathway"], "--kind", "verify",
        "--evidence", str(evidence), "--result", "pass", "--gate", "pfos-cockpit-gate",
        "--proof-type", "artifact", "--verified-by", "python3 /home/dev/.claude/scripts/quality-guard.py", "--verify-cmd", passing_verifier_cmd(),
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


def test_pathway_metric_reuses_generic_verifier_binding():
    """A metric pass parses each shared verifier command once, not once per proof scan."""
    reset()
    opl = load_cli("pathway_metric_verifier_cache")
    project = ROOT / "projects" / "metric-verifier-cache"
    project.mkdir(parents=True)
    verifier = write(
        "out/test-verifiers/metric-cache.py",
        "print('GENERIC_TEST_VERIFIER=PASS')\n",
    )
    command = f"{sys.executable} -B {verifier}"
    binding = opl.parse_generic_verifier_command(command, project)
    command_digest = hashlib.sha256(command.encode("utf-8")).hexdigest()
    proof_timestamp = "2026-08-21T12:01:00+00:00"
    recommendation_timestamp = "2026-08-21T12:00:00+00:00"
    proofs = []
    recommendations = []
    for index in range(12):
        recommendation_id = f"REC-cache-{index}"
        recommendations.append({
            "recommendation_id": recommendation_id,
            "timestamp": recommendation_timestamp,
            "work_id": "W-cache",
            "project": project.name,
            "pathway": "quality",
        })
        proofs.append({
            "proof_id": f"P-cache-{index}",
            "recommendation_id": recommendation_id,
            "timestamp": proof_timestamp,
            "work_id": "W-cache",
            "project": project.name,
            "project_path": str(project),
            "pathway": "quality",
            "result": "pass",
            "verifier_strength": "executed",
            "exit_code": 0,
            "trivial_verifier": False,
            "canary_mutant_failed": None,
            "verify_command": command,
            "verify_command_sha256": command_digest,
            "verify_error": "",
            "verifier_source_kind": "python_file",
            "verifier_source_error": "",
            "verifier_source_path": binding["path"],
            "verifier_source_target_path": binding["resolved_path"],
            "verifier_source_sha256": binding["source_sha256"],
            "verifier_interpreter_path": binding["interpreter_path"],
            "verifier_interpreter_sha256": binding["interpreter_sha256"],
            "verifier_post_source_sha256": binding["source_sha256"],
            "verifier_post_interpreter_sha256": binding["interpreter_sha256"],
            "verifier_snapshot_stable": True,
        })

    args = type("Args", (), {
        "claude_home": str(ROOT / "claude"),
        "codex_home": str(ROOT / "codex"),
        "projects_root": str(ROOT / "projects"),
        "output_root": str(ROOT / "out"),
    })()
    paths = opl.Paths(args)
    paths.operator_intel.mkdir(parents=True, exist_ok=True)
    opl.write_ndjson(paths.recommendations_path, recommendations)
    opl.write_ndjson(paths.proofs_path, proofs)
    opl.write_ndjson(paths.work_items_path, [{
        "work_id": "W-cache", "project_name": project.name,
    }])

    parse_calls = 0
    original_parse = opl.parse_generic_verifier_command

    def counting_parse(*call_args, **call_kwargs):
        nonlocal parse_calls
        parse_calls += 1
        return original_parse(*call_args, **call_kwargs)

    opl.parse_generic_verifier_command = counting_parse
    metric = opl.compute_pathway_metric(paths)
    check(metric["proved"] == len(recommendations),
          "the verifier-binding cache preserves the proved recommendation count")
    check(parse_calls == 1,
          "pathway-metric parses one shared generic verifier binding once per computation")

    parse_calls = 0
    freshness_cache = {}
    check(opl.generic_verifier_source_is_current(proofs[0], freshness_cache),
          "a cached verifier binding accepts unchanged live source")
    verifier.write_bytes(verifier.read_bytes() + b"# drift\n")
    check(not opl.generic_verifier_source_is_current(proofs[0], freshness_cache),
          "a cached verifier binding still rejects live source drift")
    check(parse_calls == 1,
          "live source drift is caught without reparsing the shared verifier binding")


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
        "--proof-type", "artifact", "--verified-by", "python3 tests", "--verify-cmd", passing_verifier_cmd(), "--recommendation-id", recommendation_id,
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

    # Production-secure closeout cannot be laundered through free-text N/A reasons. This is a
    # separate work item so the exact attack can exercise every mandatory pathway without
    # affecting the rest of this coverage test.
    waiver_start, _ = run("work-start", [
        "--project", str(proj), "--goal", "production secure waiver bypass regression",
        "--tier", "production-secure",
    ])
    waiver_wid = waiver_start["work_id"]
    run("work-log", [
        "--work-id", waiver_wid, "--pathway", "govern", "--kind", "verify",
        "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact",
        "--verify-cmd", passing_verifier_cmd(),
    ])
    waiver_findings = []
    for pathway in (
        "research", "data", "security", "implementation", "quality", "observability",
        "techdebt", "release", "docs",
    ):
        rejected, _ = run("work-cover", [
            "--work-id", waiver_wid, "--pathway", pathway, "--na",
            "--reason", "agent says not applicable",
        ])
        waiver_findings.extend(ids(rejected))
    check(
        waiver_findings.count("work-cover-production-secure-na-blocked") == 9,
        "every production-secure free-text N/A waiver is rejected",
    )
    waiver_status, _ = run("work-status", ["--work-id", waiver_wid])
    waiver_states = {
        entry["pathway"]: entry["status"] for entry in waiver_status["summary"]["itinerary"]
    }
    check(
        all(waiver_states[pathway] == "required"
            for pathway in ("security", "observability", "release")),
        "security, observability, and release remain required after waiver attempts",
    )
    waiver_close, _ = run("work-close", ["--work-id", waiver_wid])
    check(
        waiver_close.get("closed") is False,
        "production-secure closeout stays blocked after arbitrary N/A attempts",
    )
    run("work-start", [
        "--project", str(proj), "--goal", "production secure waiver bypass regression",
        "--tier", "demoable",
    ])
    downgraded_waiver, _ = run("work-cover", [
        "--work-id", waiver_wid, "--pathway", "release", "--na",
        "--reason", "agent downgraded the tier first",
    ])
    check(
        "work-cover-production-secure-na-blocked" in ids(downgraded_waiver),
        "tier downgrade cannot remove a production-secure profile's non-waivable proof floor",
    )
    work_items_path = ROOT / "out/operator-intelligence/work-items.ndjson"
    work_items = [
        json.loads(line) for line in work_items_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for work_item in work_items:
        if work_item.get("work_id") == waiver_wid:
            for entry in work_item.get("itinerary", []):
                entry["status"] = "proved"
                entry["proved_by_run"] = "R-stale-or-revoked"
    work_items_path.write_text(
        "".join(json.dumps(work_item, sort_keys=True) + "\n" for work_item in work_items),
        encoding="utf-8",
    )
    revoked_status, _ = run("work-status", ["--work-id", waiver_wid])
    revoked_states = {
        entry["pathway"]: entry["status"]
        for entry in revoked_status["summary"]["itinerary"]
    }
    check(
        revoked_states["govern"] == "proved"
        and all(revoked_states[pathway] == "required"
                for pathway in ("security", "observability", "release")),
        "persisted proved labels reopen unless the current verified proof ledger supports them",
    )
    revoked_close, _ = run("work-close", ["--work-id", waiver_wid])
    check(
        revoked_close.get("closed") is False,
        "stale or verifier-revoked proved labels cannot close production-secure work",
    )

    # P0 (Codex): a fake/nonexistent evidence path must NOT mark a pathway proved.
    run("work-log", ["--work-id", demo_wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ROOT / "nope.txt"), "--result", "pass"])
    data, _ = run("work-status", ["--work-id", demo_wid])
    st = {e["pathway"]: e["status"] for e in data["summary"]["itinerary"]}
    check(st["govern"] == "required", "fake/nonexistent evidence path does not mark a pathway proved")

    # A real on-disk artifact + a named verifier proves it (Gap A sufficiency bar).
    run("work-log", ["--work-id", demo_wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact", "--verified-by", "test verifier", "--verify-cmd", passing_verifier_cmd()])
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
    run("work-log", ["--work-id", secure_wid, "--pathway", "security", "--kind", "verify", "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact", "--verified-by", "test verifier", "--verify-cmd", passing_verifier_cmd()])
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
                                 "--evidence", str(ev), "--gate", "govern-gate", "--verify-cmd", passing_verifier_cmd()])
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


def test_proof_add_resolves_bare_project_name_and_flags_invalid_cwd():
    """Regression (verify cwd): legacy work items created via `work-start --project koho` stored
    the bare project NAME, so proof-add handed subprocess.run cwd="koho", which raised and was
    recorded fail-closed as exit 1 / empty stdout / trivial_verifier — the leg could never flip
    to proved (W-20260720-koho-consultops-tasks-section-d84095). proof-add must resolve the name
    against the projects root before running the verifier, work-start must store the resolved
    path at entry, and a cwd that resolves nowhere must be recorded as verify_error=cwd_invalid
    instead of an indistinguishable silent exit 1."""
    reset()
    proj = ROOT / "projects" / "barename"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "proof-of-cwd.txt").write_text("cwd resolved to the real project directory\n", encoding="utf-8")
    ev = ROOT / "barename-evidence.txt"
    ev.write_text("artifact", encoding="utf-8")
    start, _ = run("work-start", ["--project", "barename", "--goal", "bare name cwd test", "--tier", "demoable"])
    wid = start["work_id"]
    items_path = ROOT / "out" / "operator-intelligence" / "work-items.ndjson"

    # Entry fix: work-start resolves the bare name against the projects root before storing it.
    items = [json.loads(l) for l in items_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    stored = next(w for w in items if w.get("work_id") == wid)
    check(stored["project"] == str(proj.resolve()),
          "work-start resolves a bare --project name to the real project directory")

    # Re-inject the legacy shape (bare name) to prove proof-add resolves it at consumption too.
    stored["project"] = "barename"
    items_path.write_text("\n".join(json.dumps(w) for w in items) + "\n", encoding="utf-8")
    cwd_verifier = text_guard_verifier_cmd(
        "proof-of-cwd.txt", "cwd resolved to the real project directory",
        name="cwd-verifier.py",
    )
    added, _ = run("proof-add", ["--work-id", wid, "--pathway", "govern", "--proof-type", "artifact",
                                 "--evidence", str(ev), "--verify-cmd", cwd_verifier])
    proof = added["records"][0]
    check(proof.get("exit_code") == 0 and not proof.get("verify_error"),
          "proof-add resolves a bare work-item project name and runs the verifier in the real directory")
    check(added.get("itinerary_coverage", {}).get("covered", 0) >= 1,
          "a verifier run in the resolved directory flips the pathway to proved")

    # A project value that resolves nowhere is a distinguishable receipt, not a silent exit 1.
    stored["project"] = "no-such-project-dir"
    items_path.write_text("\n".join(json.dumps(w) for w in items) + "\n", encoding="utf-8")
    ev2 = ROOT / "barename-evidence-2.txt"
    ev2.write_text("artifact two", encoding="utf-8")
    added2, _ = run("proof-add", ["--work-id", wid, "--pathway", "quality", "--proof-type", "artifact",
                                  "--evidence", str(ev2), "--verify-cmd", cwd_verifier])
    proof2 = added2["records"][0]
    check(proof2.get("verify_error") == "cwd_invalid" and proof2.get("exit_code") is None,
          "an unresolvable project cwd records verify_error=cwd_invalid with no fabricated exit code")
    check(not proof2.get("trivial_verifier"),
          "a cwd_invalid verifier is not mislabeled trivial_verifier")
    data, _ = run("work-status", ["--work-id", wid])
    st = {e["pathway"]: e["status"] for e in data["summary"]["itinerary"]}
    check(st.get("quality") != "proved", "cwd_invalid stays fail-closed: the pathway does not prove")


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
    run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev), "--result", "pass", "--proof-type", "artifact", "--verified-by", "pytest -q (green)", "--verify-cmd", passing_verifier_cmd()])
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
                     "--result", "pass", "--proof-type", "artifact", "--verified-by", "test", "--verify-cmd", passing_verifier_cmd()])
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
                     "--verified-by", "python3 tests (green)", "--verify-cmd", passing_verifier_cmd(), "--recommendation-id", gov_rec])

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
                     "--result", "pass", "--gate", "govern-gate", "--proof-type", "artifact", "--verified-by", "test", "--verify-cmd", passing_verifier_cmd()])

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
    # pathway proved EXCEPT docs and release (explicitly N/A), plus security (NOT in live's
    # default) always proved. Release cannot be represented as proved without a currently
    # corroborated approval-backed proof row; this calibration fixture is not testing that stack.
    live_default = ["govern", "data", "implementation", "quality", "observability", "release", "docs"]
    rows = []
    for i in range(3):
        itin = [
            {"pathway": p, "status": ("na" if p in {"docs", "release"} else "proved")}
            for p in live_default
        ]
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
                     "--result", "pass", "--proof-type", "artifact", "--verify-cmd", failing_verifier_cmd()])
    check(gov_status() == "required", "a verifier command that exits non-zero does not prove")

    # 3. BLOCKED OUTCOME STAYS BLOCKED — exit 0 means the verifier ran; it must not launder an
    # explicitly blocked operator result into a passing proof.
    blocked, _ = run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev),
                     "--result", "blocked", "--proof-type", "artifact", "--verify-cmd", passing_verifier_cmd()])
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
                     "--result", "pass", "--proof-type", "artifact", "--verify-cmd", passing_verifier_cmd()])
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
                     "--result", "pass", "--proof-type", "artifact", "--verify-cmd", passing_verifier_cmd(), "--recommendation-id", rid])
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
    check(proof.get("verify_error") == "generic_verifier_not_executed"
          and bool(proof.get("verifier_source_error")),
          "a non-Python no-op verifier is rejected before execution")
    status, _ = run("work-status", ["--work-id", wid])
    st = {e["pathway"]: e["status"] for e in status["summary"]["itinerary"]}
    check(st["govern"] == "required", "a trivial verifier does not prove the pathway")
    close, _ = run("work-close", ["--work-id", wid])
    check(close.get("closed") is not True, "a trivial verifier cannot make closeout ready")


def test_verifier_receipt_flags_trivial_command():
    """New generic receipts reject shell commands and bind a trusted direct Python verifier."""
    import hashlib
    reset()
    write("projects/recpt/README.md", "# recpt\n")
    proj = str(ROOT / "projects" / "recpt")
    ev = write("out/operator-artifacts/recpt-proof.md", "proof\n")
    start, _ = run("work-start", ["--project", proj, "--goal", "verifier receipt"])
    wid = start["work_id"]
    proofs_file = ROOT / "out" / "operator-intelligence" / "proofs.ndjson"

    # A shell no-op is recorded but never executed or credited.
    run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--proof-type", "artifact", "--verify-cmd", "true"])
    p = [json.loads(l) for l in proofs_file.read_text().splitlines() if l.strip()][-1]
    check(p.get("verify_command_sha256") == hashlib.sha256(b"true").hexdigest()
          and p.get("verifier_source_kind") == "python_file"
          and p.get("verify_error") == "generic_verifier_not_executed"
          and bool(p.get("verifier_source_error")),
          "receipt records the command digest and fail-closed unsupported form")
    check(p.get("artifact_sha256") == hashlib.sha256(b"proof\n").hexdigest(),
          "the artifact-hash binding is preserved, not scrubbed to [REDACTED] by the entropy redactor")
    check(p.get("verify_stdout_bytes") == 0 and p.get("exit_code") is None,
          "an unsupported shell verifier is not executed")

    # Each denylisted form is caught.
    for cmd in [":", "exit 0", "echo ok"]:
        run("work-log", ["--work-id", wid, "--pathway", "govern", "--kind", "verify", "--evidence", str(ev),
                         "--result", "pass", "--proof-type", "artifact", "--verify-cmd", cmd])
        pl = [json.loads(l) for l in proofs_file.read_text().splitlines() if l.strip()][-1]
        check(pl.get("verify_error") == "generic_verifier_not_executed"
              and not load_cli("unsupported_shell").proof_is_verified(pl),
              f"`{cmd}` is rejected and cannot prove")

    # A trusted direct Python verifier executes and binds both source and interpreter.
    direct_command = passing_verifier_cmd(name="receipt-pass.py")
    run("work-log", ["--work-id", wid, "--pathway", "quality", "--kind", "verify", "--evidence", str(ev),
                     "--result", "pass", "--proof-type", "artifact", "--verify-cmd", direct_command])
    p2 = [json.loads(l) for l in proofs_file.read_text().splitlines() if l.strip()][-1]
    check(p2.get("verify_stdout_bytes", 0) >= 1 and p2.get("exit_code") == 0,
          "a trusted direct Python verifier executes with observable output")
    check(p2.get("verifier_source_kind") == "python_file"
          and p2.get("verifier_interpreter_sha256")
          and p2.get("verifier_snapshot_stable") is True,
          "the receipt binds stable verifier and interpreter bytes")

    # An echo PREAMBLE must not hide a real verifier from the canary: only a bare echo is trivial.
    opl = load_cli("trivial_chain")
    check(opl.verifier_command_is_trivial("echo ok") is True, "a bare echo is trivial")
    check(opl.verifier_command_is_trivial("echo start && pytest -q") is False,
          "an echo chained to a real command is NOT trivial (canary must still run)")
    check(opl.verifier_command_is_trivial("echo pretest; ./verify.sh") is False,
          "an echo followed by a semicolon-chained verifier is NOT trivial")


def test_generic_python_verifier_source_freshness_reopens_pathway():
    """A direct Python verifier remains proof only while the exact regular source file remains."""
    import hashlib
    import subprocess as sp

    reset()
    proj = ROOT / "projects" / "verifier-freshness"
    proj.mkdir(parents=True, exist_ok=True)

    def git(*args):
        return sp.run(["git", "-C", str(proj), *args], capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Pathway Test")
    guard = proj / "guard.txt"
    guard.write_text("baseline\n", encoding="utf-8")
    git("add", "guard.txt")
    git("commit", "-q", "-m", "baseline")
    guard.write_text("approved\n", encoding="utf-8")

    verifier = proj / "verify_quality.py"
    verifier.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "if Path(sys.argv[1]).read_text(encoding='utf-8') != 'approved\\n':\n"
        "    raise SystemExit(7)\n"
        "print('GENERIC_VERIFIER=PASS')\n",
        encoding="utf-8",
    )
    original_source = verifier.read_bytes()
    opl = load_cli("generic_verifier_binding")
    composite_command = f"{sys.executable} {verifier} {guard} && printf composite"
    composite_binding = opl.parse_generic_verifier_command(composite_command, proj)
    check(
        composite_binding["error"] == "generic_verifier_shell_composition_unsupported"
        and not composite_binding["argv"],
        "a newly recorded composite shell verifier is ineligible",
    )
    evidence = write(
        "out/operator-artifacts/verifier-freshness-proof.md",
        "# Verification\n\nThe direct Python verifier checked the changed guard.\n",
    )
    started, _ = run("work-start", [
        "--project", str(proj),
        "--goal", "Keep production-secure proof bound to current verifier source",
        "--tier", "production-secure",
    ])
    work_id = started["work_id"]
    verify_command = f"{sys.executable} -B {verifier} {guard}"
    logged, _ = run("work-log", [
        "--work-id", work_id, "--pathway", "quality", "--kind", "verify",
        "--evidence", str(evidence), "--result", "pass", "--proof-type", "artifact",
        "--project", str(proj), "--verify-cmd", verify_command,
        "--canary-target", str(guard),
    ])
    proof = next(record for record in logged["records"] if record.get("verifier_strength"))
    expected_source_digest = hashlib.sha256(original_source).hexdigest()
    expected_command_digest = hashlib.sha256(verify_command.encode("utf-8")).hexdigest()
    check(
        proof.get("verifier_source_kind") == "python_file"
        and proof.get("verifier_source_path") == str(verifier)
        and proof.get("verifier_source_target_path") == str(verifier.resolve())
        and proof.get("verifier_source_sha256") == expected_source_digest
        and proof.get("verify_command_sha256") == expected_command_digest
        and proof.get("verifier_interpreter_path") == str(Path(sys.executable).resolve())
        and proof.get("verifier_interpreter_sha256")
        and proof.get("verifier_post_source_sha256") == expected_source_digest
        and proof.get("verifier_post_interpreter_sha256")
        == proof.get("verifier_interpreter_sha256")
        and not proof.get("verifier_source_error"),
        "a direct Python proof binds command, interpreter, and exact verifier source bytes",
    )

    def quality_status():
        status, _ = run("work-status", ["--work-id", work_id])
        return next(
            entry["status"] for entry in status["summary"]["itinerary"]
            if entry["pathway"] == "quality"
        )

    check(quality_status() == "proved", "the freshly logged direct Python verifier proves quality")

    verifier.write_bytes(original_source + b"# post-receipt drift\n")
    check(quality_status() == "required", "changed verifier bytes reopen the proved pathway")
    verifier.write_bytes(original_source)
    check(quality_status() == "proved", "restoring exact verifier bytes restores current proof")

    saved = verifier.with_suffix(".saved")
    verifier.rename(saved)
    check(quality_status() == "required", "a missing verifier source fails closed at read time")
    saved.rename(verifier)
    check(quality_status() == "proved", "restoring the missing verifier source restores proof")

    verifier.rename(saved)
    verifier.symlink_to(saved.name)
    check(quality_status() == "required", "a symlink replacement cannot satisfy a file-bound proof")
    closeout, _ = run("work-close", ["--work-id", work_id])
    check(closeout.get("closed") is not True, "verifier-source drift keeps closeout false")
    verifier.unlink()
    saved.rename(verifier)

    current_proof = next(
        json.loads(line)
        for line in (ROOT / "out" / "operator-intelligence" / "proofs.ndjson")
        .read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("proof_id") == proof.get("proof_id")
    )
    opl = load_cli("generic_verifier_freshness")
    check(quality_status() == "proved" and opl.proof_is_verified(current_proof),
          "exact source restoration makes the existing receipt valid again")

    # Exact bypass regressions: fake Python, env wrapping, unsupported options, and shell
    # composition are recorded without execution and cannot prove even when stdout could pass.
    fake_python = write(
        "fake-bin/python3",
        "#!/bin/sh\nprintf 'FAKE_VERIFIER=PASS\\n'\n",
    )
    fake_python.chmod(0o755)
    unsupported_commands = {
        "fake_interpreter": f"{fake_python} {verifier} {guard}",
        "env_wrapper": f"env {sys.executable} {verifier} {guard}",
        "unsupported_option": f"{sys.executable} -W ignore {verifier} {guard}",
        "shell_composite": f"{sys.executable} {verifier} {guard} && printf bypass",
    }
    for label, command in unsupported_commands.items():
        rejected, _ = run("work-log", [
            "--work-id", work_id, "--pathway", "quality", "--kind", "verify",
            "--evidence", str(evidence), "--result", "pass", "--proof-type", "artifact",
            "--project", str(proj), "--verify-cmd", command,
        ])
        rejected_proof = next(
            record for record in rejected["records"] if record.get("verifier_strength")
        )
        check(
            rejected_proof.get("verify_error") == "generic_verifier_not_executed"
            and rejected_proof.get("exit_code") is None
            and bool(rejected_proof.get("verifier_source_error"))
            and not opl.proof_is_verified(rejected_proof),
            f"{label} is never executed and cannot prove",
        )

    # A no-git verifier that mutates its own source after the pre-run hash is caught by the
    # post-run snapshot even though no changed-file canary is available.
    toctou_proj = ROOT / "projects" / "verifier-toctou"
    toctou_proj.mkdir(parents=True)
    toctou_verifier = toctou_proj / "verify.py"
    toctou_verifier.write_text(
        "from pathlib import Path\n"
        "path = Path(__file__)\n"
        "path.write_bytes(path.read_bytes() + b'# mutated\\n')\n"
        "print('GENERIC_TOCTOU=PASS')\n",
        encoding="utf-8",
    )
    toctou_start, _ = run("work-start", [
        "--project", str(toctou_proj), "--goal", "Reject verifier source TOCTOU",
        "--tier", "production-secure",
    ])
    toctou_logged, _ = run("work-log", [
        "--work-id", toctou_start["work_id"], "--pathway", "quality", "--kind", "verify",
        "--evidence", str(evidence), "--result", "pass", "--proof-type", "artifact",
        "--project", str(toctou_proj),
        "--verify-cmd", f"{sys.executable} -B {toctou_verifier}",
    ])
    toctou_proof = next(
        record for record in toctou_logged["records"] if record.get("verifier_strength")
    )
    check(
        toctou_proof.get("exit_code") == 0
        and toctou_proof.get("canary_mutant_failed") is None
        and toctou_proof.get("verifier_snapshot_stable") is False
        and toctou_proof.get("verifier_source_error")
        == "generic_verifier_source_changed_during_execution"
        and toctou_proof.get("verifier_post_source_sha256")
        != toctou_proof.get("verifier_source_sha256")
        and not opl.proof_is_verified(toctou_proof),
        "post-run hashes reject no-git verifier source TOCTOU",
    )


def test_generic_python_verifier_binds_symlinked_ancestor_target():
    """A stable ancestor symlink is target-bound; retargeting it immediately reopens proof."""
    reset()
    project = ROOT / "projects" / "ancestor-link-proof"
    project.mkdir(parents=True)
    source_root = ROOT / "verifier-targets"
    target_a = source_root / "a"
    target_b = source_root / "b"
    target_a.mkdir(parents=True)
    target_b.mkdir(parents=True)
    verifier_source = (
        "from helper import EXIT_CODE\n"
        "if EXIT_CODE:\n"
        "    raise SystemExit(EXIT_CODE)\n"
        "print('ANCESTOR_LINK_VERIFIER=PASS')\n"
    )
    for target, exit_code in ((target_a, 0), (target_b, 23)):
        (target / "verify.py").write_text(verifier_source, encoding="utf-8")
        (target / "helper.py").write_text(
            f"EXIT_CODE = {exit_code}\n", encoding="utf-8"
        )
    parent_link = ROOT / "verifier-parent-link"
    parent_link.symlink_to(target_a, target_is_directory=True)
    lexical_verifier = parent_link / "verify.py"
    command = f"{sys.executable} -B {lexical_verifier}"
    evidence = write(
        "out/operator-artifacts/ancestor-link-proof.md",
        "# Verification\n\nThe target-bound verifier passed.\n",
    )
    started, _ = run("work-start", [
        "--project", str(project),
        "--goal", "Bind a generic verifier through a stable ancestor symlink",
        "--tier", "production-secure",
    ])
    logged, _ = run("work-log", [
        "--work-id", started["work_id"], "--pathway", "quality", "--kind", "verify",
        "--evidence", str(evidence), "--result", "pass", "--proof-type", "artifact",
        "--project", str(project), "--verify-cmd", command,
    ])
    proof = next(record for record in logged["records"] if record.get("verifier_strength"))
    opl = load_cli("ancestor_symlink_binding")
    check(
        proof.get("exit_code") == 0
        and proof.get("canary_mutant_failed") is None
        and proof.get("verifier_source_path") == str(lexical_verifier)
        and proof.get("verifier_source_target_path") == str((target_a / "verify.py").resolve())
        and opl.proof_is_verified(proof),
        "a stable symlink ancestor is accepted only with its resolved regular target bound",
    )
    binding = opl.parse_generic_verifier_command(command, project)
    check(
        binding.get("argv", [])[:4]
        == [str(Path(sys.executable).resolve()), "-I", "-B", "-S"]
        and binding.get("argv", [])[-1:] == [str((target_a / "verify.py").resolve())],
        "the accepted command executes an isolated snapshot labeled with the resolved target",
    )

    parent_link.unlink()
    parent_link.symlink_to(target_b, target_is_directory=True)
    raw = subprocess.run(
        [sys.executable, "-B", str(lexical_verifier)],
        cwd=project, capture_output=True, text=True,
    )
    check(raw.returncode == 23,
          "the exact reviewer probe confirms the retargeted lexical command changed behavior")
    check(
        opl.parse_generic_verifier_command(command, project).get("resolved_path")
        == str((target_b / "verify.py").resolve())
        and not opl.generic_verifier_source_is_current(proof)
        and not opl.proof_is_verified(proof),
        "ancestor symlink retargeting invalidates the bound proof despite byte-identical source",
    )
    status, _ = run("work-status", ["--work-id", started["work_id"]])
    quality = next(
        entry["status"] for entry in status["summary"]["itinerary"]
        if entry["pathway"] == "quality"
    )
    check(quality == "required", "ancestor symlink drift reopens quality at read time")

    parent_link.unlink()
    parent_link.symlink_to(target_a, target_is_directory=True)
    check(opl.proof_is_verified(proof),
          "restoring the exact ancestor target restores the bound proof")


def test_generic_python_verifier_executes_exact_source_snapshot():
    """A transient source replacement cannot run bytes outside the receipt's source digest.

    The pinned loader must still preserve the useful semantics of direct script execution:
    arguments, resolved ``__file__``, requested cwd, and imports from the script directory.
    """
    import argparse
    import hashlib

    reset()
    project = ROOT / "projects" / "exact-verifier-snapshot"
    project.mkdir(parents=True)
    evidence = write(
        "out/operator-artifacts/exact-verifier-snapshot.md",
        "# Verification\n\nThe captured verifier source passed with direct-script semantics.\n",
    )
    verifier = project / "verify.py"
    helper = project / "helper.py"
    helper.write_text("EXPECTED = 'local-import-ok'\n", encoding="utf-8")
    legitimate_source = (
        "from helper import EXPECTED\n"
        "from pathlib import Path\n"
        "import sys\n"
        "if EXPECTED != 'local-import-ok':\n"
        "    raise SystemExit(11)\n"
        "if sys.argv[1] != 'argument with spaces':\n"
        "    raise SystemExit(12)\n"
        "if Path(__file__).resolve() != Path(sys.argv[2]).resolve():\n"
        "    raise SystemExit(13)\n"
        "if Path.cwd().resolve() != Path(sys.argv[3]).resolve():\n"
        "    raise SystemExit(14)\n"
        "print('EXACT_SNAPSHOT_VERIFIER=PASS')\n"
    ).encode("utf-8")
    verifier.write_bytes(legitimate_source)
    malicious_marker = project / "malicious-replacement-executed.txt"
    malicious_source = (
        "from pathlib import Path\n"
        f"Path({str(malicious_marker)!r}).write_text('executed', encoding='utf-8')\n"
        "print('MALICIOUS_REPLACEMENT=PASS')\n"
    ).encode("utf-8")
    command = " ".join(shlex.quote(str(value)) for value in (
        sys.executable,
        "-B",
        verifier,
        "argument with spaces",
        verifier.resolve(),
        project.resolve(),
    ))
    opl = load_cli("exact_generic_verifier_snapshot")
    original_runner = opl.run_generic_verifier_snapshot
    executed_snapshots = []

    def coordinated_transient_swap(binding, cwd, timeout=120):
        executed_snapshots.append(binding.get("source_bytes"))
        verifier.write_bytes(malicious_source)
        try:
            return original_runner(binding, cwd, timeout=timeout)
        finally:
            verifier.write_bytes(legitimate_source)

    opl.run_generic_verifier_snapshot = coordinated_transient_swap
    args = argparse.Namespace(
        evidence=str(evidence), work_id="W-exact-verifier-snapshot", pathway="quality",
        gate="quality-gate", kind="verify", result="pass", stale_after_days=30,
        verified_by="", recommendation_id="", verify_cmd=command, reviewer="",
        proof_type="artifact", canary_target=None, project=str(project),
    )
    proof, warning = opl.build_proof_record(
        args,
        work_item={
            "project": str(project),
            "project_name": project.name,
            "tier": "production-secure",
        },
        projects_root=str(ROOT / "projects"),
    )
    legitimate_digest = hashlib.sha256(legitimate_source).hexdigest()
    legitimate_stdout = b"EXACT_SNAPSHOT_VERIFIER=PASS\n"
    check(
        executed_snapshots == [legitimate_source]
        and proof.get("verifier_source_sha256") == legitimate_digest
        and proof.get("verify_stdout_sha256") == hashlib.sha256(legitimate_stdout).hexdigest(),
        "the recorded source digest and credited stdout come from the same captured bytes",
    )
    check(
        proof.get("exit_code") == 0
        and proof.get("verifier_snapshot_stable") is True
        and warning is None
        and opl.proof_is_verified(proof),
        "the exact legitimate snapshot preserves args, __file__, cwd, and local imports",
    )
    check(
        not malicious_marker.exists() and verifier.read_bytes() == legitimate_source,
        "a transient malicious replacement never executes or supplies credited output",
    )


def test_generic_python_verifier_isolates_python_startup_environment():
    """PYTHONPATH sitecustomize cannot execute before the pinned verifier snapshot."""
    import hashlib

    reset()
    project = ROOT / "projects" / "isolated-verifier-startup"
    project.mkdir(parents=True)
    injection_dir = ROOT / "python-startup-injection"
    injection_dir.mkdir()
    injection_marker = project / "sitecustomize-loaded.txt"
    (injection_dir / "sitecustomize.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(injection_marker)!r}).write_text('loaded', encoding='utf-8')\n"
        "print('SITECUSTOMIZE=FORGED')\n",
        encoding="utf-8",
    )
    control_env = dict(os.environ)
    control_env["PYTHONPATH"] = str(injection_dir)
    control = subprocess.run(
        [sys.executable, "-B", "-c", "print('CONTROL=PASS')"],
        cwd=project, env=control_env, capture_output=True, text=True, timeout=30,
    )
    check(control.returncode == 0 and injection_marker.exists(),
          "the startup-injection fixture executes under an ordinary Python launch")
    injection_marker.unlink()

    verifier = project / "verify.py"
    source = (
        "import os\n"
        "if (any(key.upper().startswith('PYTHON') for key in os.environ)\n"
        "        or '__PYVENV_LAUNCHER__' in os.environ):\n"
        "    raise SystemExit(17)\n"
        "print('ISOLATED_SNAPSHOT_VERIFIER=PASS')\n"
    ).encode("utf-8")
    verifier.write_bytes(source)
    command = " ".join(shlex.quote(str(value)) for value in (
        sys.executable, "-B", verifier,
    ))
    opl = load_cli("isolated_generic_verifier_startup")
    binding = opl.parse_generic_verifier_command(command, project)
    prior_pythonpath = os.environ.get("PYTHONPATH")
    prior_pyvenv_launcher = os.environ.get("__PYVENV_LAUNCHER__")
    os.environ["PYTHONPATH"] = str(injection_dir)
    os.environ["__PYVENV_LAUNCHER__"] = str(ROOT / "untrusted-python-launcher")
    try:
        exit_code, stdout_sha256, _stdout_bytes, stdout = (
            opl.run_generic_verifier_snapshot(binding, project)
        )
    finally:
        if prior_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = prior_pythonpath
        if prior_pyvenv_launcher is None:
            os.environ.pop("__PYVENV_LAUNCHER__", None)
        else:
            os.environ["__PYVENV_LAUNCHER__"] = prior_pyvenv_launcher
    expected_stdout = b"ISOLATED_SNAPSHOT_VERIFIER=PASS\n"
    check(
        not binding.get("error")
        and binding.get("argv", [])[:4]
        == [str(Path(sys.executable).resolve()), "-I", "-B", "-S"]
        and binding.get("argv", []).count("-B") == 1,
        "generic verifier startup is normalized to one isolated no-bytecode stdlib launch",
    )
    check(
        exit_code == 0
        and stdout == expected_stdout.decode("utf-8")
        and stdout_sha256 == hashlib.sha256(expected_stdout).hexdigest()
        and not injection_marker.exists(),
        "PYTHONPATH and sitecustomize cannot alter or preempt the verifier snapshot",
    )


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
                     "--verify-cmd", text_guard_verifier_cmd("value.txt", "100")])
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
                     "--verify-cmd", passing_verifier_cmd(name="opaque-pass.py")])
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
                          "body": "password=hunter2",
                          "release_artifact_sha256": {
                              field: "b" * 64 for field in opl.RELEASE_RECEIPT_ARTIFACT_FIELDS
                          }})
    check(out["artifact_sha256"] == "a" * 64, "a real 64-hex digest under a digest-named key is preserved")
    uppercase_digest = opl.redact_obj({
        "release_verifier_markers": {"RELEASE_RECEIPT_SHA256": "c" * 64}
    })
    check(uppercase_digest["release_verifier_markers"]["RELEASE_RECEIPT_SHA256"] == "c" * 64,
          "uppercase verifier digest keys retain exact content hashes")
    check("sk-proj-" not in out["note_sha256"] and "LEAKED" not in out["note_sha256"],
          "a *_sha256 key holding a non-digest secret is still redacted")
    check(hex_secret not in out["session_key"],
          "a 64-hex secret under a non-digest key is scrubbed (key+value conjunction)")
    check("hunter2" not in out["body"], "ordinary secret values are unaffected by the exemption")
    check(all(value == "b" * 64 for value in out["release_artifact_sha256"].values()),
          "the closed release-artifact digest map survives proof-ledger redaction")
    closed_map_attack = opl.redact_obj({"release_artifact_sha256": {"session_key": hex_secret}})
    check(hex_secret not in closed_map_attack["release_artifact_sha256"]["session_key"],
          "unknown keys cannot exploit the closed release-digest map exemption")


def test_redaction_covers_bearer_and_provider_prefixed_credentials():
    """Provider keys are often shorter than the entropy fallback, especially in test/dev tiers."""
    reset()
    opl = load_cli("provider_redaction")
    xai_key = "xai-abcdefghijklmnopqrstuvwx123456"
    github_token = "github_pat_abcdefghijklmnopqrstuvwx123456"
    bearer = "Authorization: Bearer bearer_abcdefghijklmnopqrstuvwx123456"
    aws_key = "AKIAIOSFODNN7EXAMPLE"
    google_key = "AIzaSyDUMMYKEYabcdefghijklmnopqrstu1234"
    slack_token = "xoxb-EXAMPLE-NOT-A-REAL-TOKEN-000"
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
    check(opl.release_receipt_credit_scope(preview) == "",
          "preview readiness does not credit the production release pathway")
    target_ready = {
        **preview,
        "canary_status": "passed",
        "production_status": "deployed",
        "rollback_status": "ready",
        "human_approval": "Alex approved",
        "canary_artifact": "canary.json",
    }
    check(not any("rollback_status" in error for error in opl.validate_release_receipt(
        target_ready, production_approval=True
    )), "production receipt accepts a provider-backed ready rollback target")
    send_ready = {**preview, "external_send_state": "send-ready", "claimed_external_send": True}
    check(any("send-ready" in error for error in opl.validate_release_receipt(send_ready))
          and not opl.release_receipt_supports_send(send_ready),
          "send-ready cannot be claimed as sent")
    auth_only_send = {
        **target_ready,
        "external_send_state": "user-triggered-auth-only",
        "external_send_count": 1,
        "external_send_action": "request-one-supabase-magic-link",
        "external_send_artifact": "auth-send.json",
        "human_approval": "Alex approved the exact one auth message",
    }
    check(not opl.validate_release_receipt(
        auth_only_send, production_approval=True
    ), "one separately approved user-triggered auth message is representable")
    check(any("exactly one" in error for error in opl.validate_release_receipt(
        {**auth_only_send, "external_send_count": 2}, production_approval=True
    )), "user-triggered auth state rejects more than one message")
    check(any("exact auth action" in error for error in opl.validate_release_receipt(
        {**auth_only_send, "external_send_action": "send-campaign"},
        production_approval=True,
    )), "user-triggered auth state cannot authorize another send kind")
    unattested_send = {
        **preview,
        "external_send_state": "sent",
        "human_approval": "agent says Alex approved",
    }
    check(any("verifiable single-use external approval" in error
              for error in opl.validate_release_receipt(unattested_send))
          and not opl.release_receipt_supports_send(unattested_send),
          "a non-deployed external send cannot trust free-text approval")
    production = {
        **preview,
        "canary_status": "passed",
        "production_status": "deployed",
        "rollback_status": "rehearsed",
        "human_approval": "Alex approved",
        "external_send_state": "sent",
        "canary_artifact": "canary.json",
    }
    check(any("verifiable single-use external approval" in error
              for error in opl.validate_release_receipt(production)),
          "free-text approval cannot authorize a production release or external send")
    check(not opl.release_receipt_supports_send(production)
          and opl.release_receipt_credit_scope(production) == "",
          "production credit stays closed until a verifiable approval trust root exists")
    contradictory = {
        "release_receipt": production,
        "release_decision": {
            "decision": "RELEASE", "release_gate": "PASS", "pathway_result": "PASS",
            "deployed": False, "production_mutation_performed": False,
            "current_authorized_stage": "NONE",
        },
    }
    check(opl.release_receipt_credit_scope(production, contradictory) == "",
          "contradictory no-deploy envelope cannot wrap a production receipt")

    base_proof = {
        "pathway": "release", "result": "pass", "verifier_strength": "executed",
        "exit_code": 0, "trivial_verifier": False, "canary_mutant_failed": True,
        "release_snapshot_stable": True, "release_snapshot_errors": [],
        "template_check": {"valid": True}, "release_credit_scope": "production",
        "release_receipt_errors": [], "release_verifier_errors": [],
        "release_verifier_bound": True,
        "release_artifact_sha256": {field: "a" * 64 for field in opl.RELEASE_RECEIPT_ARTIFACT_FIELDS},
    }
    check(not opl.proof_is_verified(base_proof),
          "production release proof cannot credit while external approval verification is unavailable")
    check(not opl.proof_is_verified({**base_proof, "canary_mutant_failed": None}),
          "release proof cannot credit when the verifier canary is unavailable")
    check(not opl.proof_is_verified({**base_proof, "template_check": {"valid": False}}),
          "release proof cannot credit an invalid evidence template")
    check(not opl.proof_is_verified({**base_proof, "release_credit_scope": ""}),
          "release proof cannot credit a hold or preview-only receipt")
    marker_text = (
        "RELEASE_DECISION=RELEASE\nRELEASE_GATE=PASS\nPATHWAY_RESULT=PASS\n"
        "PRODUCTION_STATUS=DEPLOYED\nCANARY_STATUS=PASSED\nROLLBACK_STATUS=REHEARSED\n"
        "EXTERNAL_SEND_STATUS=NOT_SENT\nEXTERNAL_SEND_COUNT=0\n"
        f"RELEASE_RECEIPT_SHA256={'b' * 64}\n"
    )
    check(opl.release_verifier_binding(
        marker_text,
        "b" * 64,
        {"rollback_status": "rehearsed", "external_send_state": "not-sent"},
    )["bound"] is True,
          "release verifier markers bind the production outcome to the receipt digest")
    duplicate = "RELEASE_DECISION=NO_RELEASE\n" + marker_text
    check(opl.release_verifier_binding(
        duplicate,
        "b" * 64,
        {"rollback_status": "rehearsed", "external_send_state": "not-sent"},
    )["bound"] is False,
          "duplicate release markers fail closed instead of using the last value")
    target_ready_marker_text = marker_text.replace(
        "ROLLBACK_STATUS=REHEARSED", "ROLLBACK_STATUS=TARGET_READY"
    )
    check(opl.release_verifier_binding(
        target_ready_marker_text,
        "b" * 64,
        {"rollback_status": "ready", "external_send_state": "not-sent"},
    )["bound"] is True,
          "target-ready output binds only to a typed ready rollback receipt")
    check(opl.release_verifier_binding(
        target_ready_marker_text, "b" * 64, None
    )["bound"] is False,
          "target-ready output cannot earn release credit without a typed receipt")
    check(opl.release_verifier_binding(
        marker_text,
        "b" * 64,
        {"rollback_status": "ready", "external_send_state": "not-sent"},
    )["bound"] is False,
          "a ready rollback receipt rejects a false rehearsed output marker")
    auth_marker_text = target_ready_marker_text.replace(
        "EXTERNAL_SEND_STATUS=NOT_SENT\nEXTERNAL_SEND_COUNT=0",
        "EXTERNAL_SEND_STATUS=USER_TRIGGERED_AUTH_ONLY\nEXTERNAL_SEND_COUNT=1",
    )
    check(opl.release_verifier_binding(
        auth_marker_text,
        "b" * 64,
        {
            "rollback_status": "ready",
            "external_send_state": "user-triggered-auth-only",
            "external_send_count": 1,
        },
    )["bound"] is True,
          "one auth-only send marker binds to the exact typed receipt")
    check(opl.release_verifier_binding(
        auth_marker_text,
        "b" * 64,
        {"rollback_status": "ready", "external_send_state": "not-sent"},
    )["bound"] is False,
          "auth-only stdout cannot bind a receipt that claims no send")

    reset()
    missing_artifact_md = write("out/operator-artifacts/missing-release.md", "release verification rollback\n")
    write("out/operator-artifacts/missing-release.json", json.dumps({"release_receipt": production}))
    loaded = opl.release_receipt_from_evidence(missing_artifact_md)
    check(any("existing companion-directory file" in error for error in loaded["errors"]),
          "production release artifacts must exist before their hashes can enter proof")

    now = opl.utc_now()
    for artifact_name in (
        "preview-plan.md", "preview-check.json", "canary.json", "rollback-plan.md",
    ):
        write(f"out/operator-artifacts/{artifact_name}", json.dumps({"fixture": artifact_name}))
    release_context = {
        "work_id": "W-release-bound", "recommendation_id": "REC-release-bound",
        "target_project": str((ROOT / "projects" / "release-bound").resolve()),
    }
    bound_envelope = {
        **release_context,
        "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (now + opl.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "release_decision": {
            "decision": "RELEASE", "release_gate": "PASS", "pathway_result": "PASS",
            "deployed": True, "production_mutation_performed": True,
            "current_authorized_stage": "PRODUCTION",
        },
        "release_receipt": production,
    }
    write("out/operator-artifacts/auth-send.json", json.dumps({
        "action": "request-one-supabase-magic-link",
        "message_count": 1,
        "approval_reference": "Alex approved the exact one auth message",
    }))
    auth_bound_receipt = {**auth_only_send, "external_send_artifact": "auth-send.json"}
    auth_bound_json = write(
        "out/operator-artifacts/release-auth-bound.json",
        json.dumps({**bound_envelope, "release_receipt": auth_bound_receipt}),
    )
    auth_loaded = opl.release_receipt_from_evidence(
        auth_bound_json,
        release_context,
        now=now,
        production_approval=True,
    )
    check(not auth_loaded["errors"]
          and set(auth_loaded["artifact_sha256"])
          == set(opl.RELEASE_RECEIPT_ARTIFACT_FIELDS) | {"external_send_artifact"},
          "auth-only release proof snapshots its separate send artifact")
    bound_md = write("out/operator-artifacts/release-bound.md", "release verification rollback\n")
    write("out/operator-artifacts/release-bound.json", json.dumps(bound_envelope))
    loaded = opl.release_receipt_from_evidence(bound_md, release_context, now=now)
    check(any("verifiable single-use external approval" in error for error in loaded["errors"])
          and loaded["credit_scope"] == "",
          "fresh production claims remain uncreditable without external approval verification")
    replay = opl.release_receipt_from_evidence(bound_md, {
        "work_id": "W-replay", "recommendation_id": "REC-replay",
        "target_project": str((ROOT / "projects" / "other").resolve()),
    }, now=now)
    check(replay["credit_scope"] == "",
          "untrusted production release claims cannot earn scope under replayed context")
    stale_envelope = {
        **bound_envelope,
        "issued_at": (now - opl.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (now - opl.timedelta(days=2, hours=-1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    stale_md = write("out/operator-artifacts/release-stale.md", "release verification rollback\n")
    write("out/operator-artifacts/release-stale.json", json.dumps(stale_envelope))
    stale_loaded = opl.release_receipt_from_evidence(stale_md, release_context, now=now)
    check(stale_loaded["credit_scope"] == ""
          and any("verifiable single-use external approval" in error
                  for error in stale_loaded["errors"]),
          "expired production claims remain uncreditable while approval trust is absent")
    absolute_envelope = {
        **bound_envelope,
        "release_receipt": {**production, "deploy_artifact": str(
            (ROOT / "out/operator-artifacts/deploy.json").resolve()
        )},
    }
    absolute_md = write("out/operator-artifacts/release-absolute.md", "release verification rollback\n")
    write("out/operator-artifacts/release-absolute.json", json.dumps(absolute_envelope))
    check(any("companion-directory filename" in error for error in opl.release_receipt_from_evidence(
        absolute_md, release_context, now=now
    )["errors"]), "production release artifacts cannot escape the companion directory")
    release_companion = bound_md.with_suffix(".json")
    release_target = release_companion.with_name("release-bound-target.json")
    release_target.write_bytes(release_companion.read_bytes())
    release_companion.unlink()
    release_companion.symlink_to(release_target.name)
    check(any("must not be a symlink" in error for error in opl.release_receipt_from_evidence(
        bound_md, release_context, now=now
    )["errors"]), "symlinked release companions fail closed")


def test_release_hold_carries_constraints_without_credit_or_repeat():
    """A verified NO_RELEASE check is a constraint baton, never release readiness.

    This reproduces the tradebot defect: the caller supplies `--result pass`, the verifier exits
    zero, and the artifact truth still says BLOCKED / NOT_DEPLOYED. The hold must remain unproved,
    become the latest carry-forward, and route to another open prerequisite.
    """
    reset()
    proj = ROOT / "projects" / "releasehold"
    proj.mkdir(parents=True, exist_ok=True)
    shared = write("out/operator-artifacts/security-carry.md", """# Verified prerequisite

Decision, verifier, question, sources, threat, and verification are recorded.

## Summary
Security remains fail-closed while prerequisites are open.

## What Changed
- Bound the no-deploy authority state.

## More Relevant
- Secretless data preflight.

## Less Relevant
- Production rollout.

## Next Pathway Must Use
- Data preflight remains secretless.
- Quality and release must verify runtime controls before any stage beyond data preflight.

## Do Not Do Yet
- Do not deploy execution or flip a production feature flag.

## Open Decisions
- Choose the runtime and rollback target.

## Active Risk Overlays
- rollback
""")
    start, _ = run("work-start", [
        "--project", str(proj), "--goal", "agent release hold routing", "--tier", "live",
    ])
    wid = start["work_id"]
    for pathway in ("govern", "research", "security"):
        run("work-log", [
            "--work-id", wid, "--pathway", pathway, "--kind", "verify",
            "--evidence", str(shared), "--result", "pass", "--proof-type", "artifact",
            "--verify-cmd", passing_verifier_cmd(),
        ])

    hold = write("out/operator-artifacts/release-hold.md", """# Release hold verification

Rollback and verification were checked without deployment.

## Summary
The release decision is NO_RELEASE and the pathway remains blocked.

## What Changed
- Verified the release hold and rollback model.

## More Relevant
- Close observability prerequisites.

## Less Relevant
- Production deployment.

## Next Pathway Must Use
- Prefer the next engine-selected non-release prerequisite after this blocked receipt.

## Do Not Do Yet
- Do not deploy, run a canary, or flip a feature flag.

## Open Decisions
- Select the runtime rollback harness.

## Active Risk Overlays
- rollback
""")
    write("out/operator-artifacts/release-hold.json", json.dumps({
        "status": "RELEASE_BLOCKED_NO_RUNTIME",
        "claim_scope": "SPEC_ONLY_NO_DEPLOY",
        "release_decision": {
            "decision": "NO_RELEASE", "release_gate": "BLOCKED", "pathway_result": "BLOCKED",
            "deployed": False, "production_mutation_performed": False,
            "current_authorized_stage": "NONE",
        },
        "release_receipt": {
            "preview_status": "not-run", "canary_status": "not-run",
            "production_status": "not-deployed", "rollback_status": "not-needed",
            "external_send_state": "not-sent", "feature_flag_state": "not-used",
        },
    }))
    logged, _ = run("work-log", [
        "--work-id", wid, "--pathway", "release", "--kind", "verify",
        "--evidence", str(hold), "--result", "pass", "--proof-type", "artifact",
        "--verify-cmd", "printf 'RELEASE_DECISION=NO_RELEASE\\nRELEASE_GATE=BLOCKED\\nPATHWAY_RESULT=BLOCKED\\nPRODUCTION_STATUS=NOT_DEPLOYED\\n'",
        "--control-risk", "release proof credit and no-deploy routing",
        "--target-pathways", "release,observability",
    ])
    proof = next(record for record in logged["records"] if record.get("proof_id"))
    check(not load_cli("release_hold_proof").proof_is_verified(proof),
          "caller-supplied pass cannot credit a NO_RELEASE verifier and not-deployed receipt")
    check(logged.get("carry_forward", {}).get("credits_pathway") is False
          and logged.get("carry_forward", {}).get("pathway_outcome") == "blocked_no_deploy",
          "the verified release hold becomes a structured constraint-only carry-forward")

    status, _ = run("work-status", ["--work-id", wid])
    release_status = next(e["status"] for e in status["summary"]["itinerary"] if e["pathway"] == "release")
    check(release_status == "required", "constraint-only release carry-forward leaves release coverage open")

    rec, _ = run("pathway-next", ["--project", str(proj), "--work-id", wid])
    check(rec.get("recommended_pathway") == "observability",
          f"release hold routes to the highest open non-release prerequisite (got {rec.get('recommended_pathway')})")
    check(rec.get("latest_carry_forward", {}).get("pathway") == "release"
          and rec.get("latest_carry_forward", {}).get("credits_pathway") is False,
          "pathway-next consumes the release hold as the latest constraint baton")
    check("release" in rec.get("deferred_pathways", []),
          "the no-deploy carry-forward explicitly defers release selection")
    check(load_cli("release_hold_structured").carry_forward_deferred_pathways({
        "pathway": "release", "credits_pathway": False,
        "pathway_outcome": "blocked_no_deploy", "do_not_do_yet": ["Do not add credentials."],
    }) == ["release"], "structured blocked outcome defers release without relying on prose")
    check(load_cli("release_hold_observability_negation").carry_forward_deferred_pathways({
        "pathway": "quality", "credits_pathway": True, "pathway_outcome": "proved",
        "do_not_do_yet": ["Do not skip observability before promotion."],
    }) == [], "a requirement not to skip observability is not inverted into a deferral")
    check(load_cli("release_hold_double_negation").carry_forward_deferred_pathways({
        "pathway": "quality", "credits_pathway": True, "pathway_outcome": "proved",
        "do_not_do_yet": ["Do not fail to run observability before promotion."],
    }) == [], "a double-negative observability requirement is not inverted into a deferral")
    check(load_cli("release_hold_observability_prerequisite").carry_forward_deferred_pathways({
        "pathway": "quality", "credits_pathway": True, "pathway_outcome": "proved",
        "do_not_do_yet": ["Do not close the work item until observability is proved."],
    }) == [], "an observability prerequisite is not inverted into an observability deferral")
    check(load_cli("release_hold_alert_prerequisite").carry_forward_deferred_pathways({
        "pathway": "quality", "credits_pathway": True, "pathway_outcome": "proved",
        "do_not_do_yet": ["Do not run the next stage until observability alerts are wired."],
    }) == [], "an alert-wiring prerequisite is not inverted into an observability deferral")
    for verb in ("forget", "neglect", "refuse"):
        check(load_cli(f"release_hold_{verb}_observability").carry_forward_deferred_pathways({
            "pathway": "quality", "credits_pathway": True, "pathway_outcome": "proved",
            "do_not_do_yet": [f"Do not {verb} to run observability before promotion."],
        }) == [], f"nested negation '{verb}' is not inverted into an observability deferral")
    check("release" not in load_cli("release_hold_negation").carry_forward_next_pathways({
        "next_pathway_must_use": [
            "Prefer the next engine-selected non-release prerequisite after this blocked receipt."
        ]
    }), "non-release wording is never parsed as a positive release directive")
    report = Path(rec["report"]).read_text(encoding="utf-8")
    check("Do not deploy, run a canary" in report and "Select the runtime rollback harness" in report,
          "the operator card renders do-not-do-yet and open-decision constraints")
    check(rec.get("karpathy_card", {}).get("do_not_do_yet")
          and rec.get("karpathy_card", {}).get("open_decisions"),
          "the JSON card carries the same constraints as the report")

    # Terminal edge: if release is now the only open item and the same carry-forward defers it,
    # the router must stop instead of manufacturing another blocked release recommendation.
    for entry in status["summary"]["itinerary"]:
        if entry.get("status") == "required" and entry.get("pathway") != "release":
            run("work-cover", [
                "--work-id", wid, "--pathway", entry["pathway"], "--na",
                "--reason", "fixture isolates the deferred-release terminal edge",
            ])
    rec_path = ROOT / "out" / "operator-intelligence" / "pathway-recommendations.ndjson"
    recs_before = len(rec_path.read_text(encoding="utf-8").splitlines())
    terminal, _ = run("pathway-next", ["--project", str(proj), "--work-id", wid])
    recs_after = len(rec_path.read_text(encoding="utf-8").splitlines())
    check(terminal.get("blocked_on_deferred") is True and terminal.get("recommended_pathway") == "",
          "sole deferred release returns a blocked no-recommendation state")
    check(terminal.get("recommendation_id") == "" and recs_after == recs_before,
          "sole deferred release does not mint a recommendation ledger row")
    check("Select the runtime rollback harness" in terminal.get("blocked_next_action", ""),
          "terminal hold routes the next action to the first carry-forward open decision")
    terminal_report = Path(terminal["report"]).read_text(encoding="utf-8")
    check("No pathway recommendation was logged" in terminal_report
          and "Do not deploy, run a canary" in terminal_report,
          "terminal hold report preserves the no-deploy authority boundary")


def test_release_proof_rejects_mid_verification_evidence_mutation():
    """A verifier cannot change release state after the pre-run receipt snapshot and keep credit."""
    reset()
    proj = ROOT / "projects" / "release-mutation"
    proj.mkdir(parents=True, exist_ok=True)
    started, _ = run("work-start", [
        "--project", str(proj), "--goal", "verify immutable production release evidence",
        "--tier", "production-secure",
    ])
    release_recommendation_id = "REC-release-mutation-fixture"
    opl = load_cli("release_mutation_context")
    release_now = opl.utc_now()
    evidence = write("out/operator-artifacts/release-mutation.md", """# Release Verification

## Summary
Production release and rollback evidence is staged for an adversarial integrity test.

## What Changed
- Bound release evidence before verifier execution.

## More Relevant
- Detect any verifier-side mutation.

## Less Relevant
- None.

## Next Pathway Must Use
- Quality must preserve the release evidence snapshot.

## Do Not Do Yet
- Do not trust mutable evidence.

## Open Decisions
- None.

## Active Risk Overlays
- release-integrity
""")
    artifacts = {}
    for name in ("deploy.json", "verification.json", "canary.json", "rollback.json"):
        artifacts[name] = write(f"out/operator-artifacts/{name}", json.dumps({"artifact": name}))
    production = {
        "preview_status": "ready", "canary_status": "passed", "production_status": "deployed",
        "rollback_status": "rehearsed", "external_send_state": "not-sent",
        "feature_flag_state": "disabled", "deploy_artifact": "deploy.json",
        "verification_artifact": "verification.json", "canary_artifact": "canary.json",
        "rollback_artifact": "rollback.json", "human_approval": "fixture approval",
    }
    receipt = write("out/operator-artifacts/release-mutation.json", json.dumps({
        "work_id": started["work_id"],
        "recommendation_id": release_recommendation_id,
        "target_project": str(proj.resolve()),
        "issued_at": release_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (release_now + opl.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "release_decision": {
            "decision": "RELEASE", "release_gate": "PASS", "pathway_result": "PASS",
            "deployed": True, "production_mutation_performed": True,
            "current_authorized_stage": "PRODUCTION",
        },
        "release_receipt": production,
    }))
    pre_receipt_sha = load_cli("release_mutation_sha").sha256_file(receipt)
    guard = proj / "release-guard.txt"
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    subprocess.run(["git", "-C", str(proj), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(proj), "config", "user.name", "Pathway Test"], check=True)
    guard.write_text("BASELINE\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(proj), "add", "release-guard.txt"], check=True)
    subprocess.run(["git", "-C", str(proj), "commit", "-q", "-m", "fixture baseline"], check=True)
    guard.write_text("PRODUCTION_RELEASE_READY\n", encoding="utf-8")
    mutator = write("projects/release-mutation/mutate-release.py", f"""import json
from pathlib import Path
import sys

guard = Path({str(guard)!r})
receipt = Path({str(receipt)!r})
if guard.read_text(encoding="utf-8") != "PRODUCTION_RELEASE_READY\\n":
    sys.exit(9)
receipt.write_text(json.dumps({{
    "release_decision": {{"decision": "NO_RELEASE", "release_gate": "BLOCKED", "pathway_result": "BLOCKED",
        "deployed": False, "production_mutation_performed": False, "current_authorized_stage": "NONE"}},
    "release_receipt": {{"preview_status": "not-run", "canary_status": "not-run",
        "production_status": "not-deployed", "rollback_status": "not-needed",
        "external_send_state": "not-sent", "feature_flag_state": "not-used"}},
}}), encoding="utf-8")
print("RELEASE_DECISION=RELEASE")
print("RELEASE_GATE=PASS")
print("PATHWAY_RESULT=PASS")
print("PRODUCTION_STATUS=DEPLOYED")
print("CANARY_STATUS=PASSED")
print("ROLLBACK_STATUS=REHEARSED")
print("EXTERNAL_SEND_STATUS=NOT_SENT")
print("EXTERNAL_SEND_COUNT=0")
print("RELEASE_RECEIPT_SHA256={pre_receipt_sha}")
""")
    logged, _ = run("work-log", [
        "--work-id", started["work_id"], "--pathway", "release", "--kind", "verify",
        "--evidence", str(evidence), "--result", "pass", "--proof-type", "artifact",
        "--project", str(proj), "--verify-cmd", f"{sys.executable} {mutator}",
        "--canary-target", str(guard),
        "--recommendation-id", release_recommendation_id,
    ])
    proof_id = next(record["proof_id"] for record in logged["records"] if record.get("proof_id"))
    proof = next(
        json.loads(line)
        for line in (ROOT / "out/operator-intelligence/proofs.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("proof_id") == proof_id
    )
    opl = load_cli("release_mutation_assert")
    check(proof.get("canary_mutant_failed") is True,
          "adversarial verifier still trips the anti-gaming canary")
    check(proof.get("release_snapshot_stable") is False
          and any("receipt changed" in error for error in proof.get("release_snapshot_errors", [])),
          "post-verification receipt hash detects the TOCTOU mutation")
    check(not opl.proof_is_verified(proof),
          "mutated release evidence cannot receive release pathway credit")
    check(any(f.get("id") == "proof-logged-unverified" for f in logged.get("findings", [])),
          "release mutation is surfaced as an explicit unverified-proof finding")


def _observability_evidence(stem):
    return write(f"out/operator-artifacts/{stem}.md", """# Observability verification

The runtime signal and verification receipt are recorded.

## Summary
Observability evidence is bound without changing runtime authority.

## What Changed
- Bound the exact observability state.

## More Relevant
- Close the remaining runtime prerequisites.

## Less Relevant
- Unverified telemetry claims.

## Next Pathway Must Use
- Prefer the next engine-selected non-observability prerequisite while runtime is absent.

## Do Not Do Yet
- Do not claim or wire runtime telemetry before prerequisites close.

## Open Decisions
- Select the runtime implementation boundary.

## Active Risk Overlays
- observability
""")


def _observability_runtime_fixture(
        opl, proj, work_id, recommendation_id, stem, mutate=False, ignore_field=""):
    """Create strict companion-local artifacts and a verifier sensitive to each bound hash."""
    now = opl.utc_now()
    observed_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_at = (now + opl.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    runtime_digest = "d" * 64
    environment_id = f"{proj.name}-secretless-runtime"
    common = {
        "schema_version": 1,
        "environment_id": environment_id,
        "runtime_digest": runtime_digest,
        "observed_at": observed_at,
    }
    metric_data = {
        **common,
        "artifact_type": "metric_evidence",
        "metric_names": sorted(opl.OBSERVABILITY_METRIC_NAMES),
        "samples": [
            {
                "name": name,
                "value": (0.1 if name == "tradebot_drawdown_ratio" else index + 1),
                "labels": {
                    key: sorted(values)[0]
                    for key, values in opl.OBSERVABILITY_METRIC_LABEL_VALUES[name].items()
                },
            }
            for index, name in enumerate(sorted(opl.OBSERVABILITY_METRIC_NAMES))
        ],
    }
    log_record = {field: f"fixture-{field}" for field in opl.OBSERVABILITY_CORRELATION_FIELDS}
    log_record.update({
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
        **{field: "c" * 64 for field in opl.OBSERVABILITY_CORRELATION_HASH_FIELDS},
    })
    drill_facts = {
        "CURRENT_AUTHORIZED_STAGE_AND_MODE": {
            "authorized_stage": "NONE", "mode": "SIMULATE_ONLY",
        },
        "DECISION_CYCLE_INTENT_AND_CLIENT_ORDER_IDENTIFIERS": {
            "decision_id": log_record["decision_id"], "cycle_id": log_record["cycle_id"],
            "intent_id": log_record["intent_id"], "client_order_id": log_record["client_order_id"],
        },
        "STRATEGY_DATA_POLICY_AND_MANIFEST_HASHES": {
            "strategy_hash": log_record["strategy_hash"],
            "data_snapshot_hash": log_record["data_snapshot_hash"],
            "risk_policy_hash": log_record["risk_policy_hash"],
            "manifest_hash": log_record["manifest_hash"],
        },
        "LAST_TRUSTED_MARKET_AND_PRIVATE_FEED_TIMESTAMPS": {
            "market_timestamp": observed_at, "private_feed_timestamp": observed_at,
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
            "halt_reason": "STALE_MARKET_DATA_AND_UNCERTAIN_VENUE_ACK", "halt_latched": True,
        },
        "WHY_RETRY_FLATTEN_AND_HALT_RELEASE_ARE_PROHIBITED": {
            "retry_prohibited": True, "flatten_prohibited": True,
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
    json_artifacts = {
        "metric_artifact": metric_data,
        "log_artifact": {
            **common,
            "artifact_type": "structured_log_evidence",
            "correlation_fields": sorted(opl.OBSERVABILITY_CORRELATION_FIELDS),
            "records": [log_record],
        },
        "trace_artifact": {
            **common,
            "artifact_type": "trace_evidence",
            "context_validated": True,
            "spans": [{"trace_id": "a" * 32, "span_id": "b" * 16, "name": "halt.activate"}],
        },
        "alert_artifact": {
            **common,
            "artifact_type": "alert_execution_evidence",
            "alerts_wired": True,
            "executions": [{
                "alert_id": "stale-feed",
                "condition": "market data absent",
                "status": "FIRED",
                "safe_action": "HALT_ENTRIES_RECONCILE_ONLY",
            }],
        },
        "runbook_drill_artifact": {
            **common,
            "artifact_type": "runbook_drill_evidence",
            "runbook_version": "3am-v1",
            "drill_executed": True,
            "answered_questions": [{
                "question_id": question_id,
                "answer": opl.OBSERVABILITY_RUNBOOK_ANSWER_CODES[question_id],
                "facts": drill_facts[question_id],
                "evidence_refs": list(
                    opl.OBSERVABILITY_RUNBOOK_ANSWER_CONTRACT[question_id]["evidence"]
                ),
            } for question_id in sorted(opl.OBSERVABILITY_RUNBOOK_QUESTION_IDS)],
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
        artifacts[field] = write(
            f"out/operator-artifacts/{stem}-{field}.json", json.dumps(payload) + "\n"
        )
    verifier = write(f"out/operator-artifacts/{stem}-verifier.py", f"""import hashlib
import json
from pathlib import Path
import sys

receipt_path = Path(sys.argv[1])
payload = json.loads(receipt_path.read_text(encoding="utf-8"))
receipt = payload["observability_receipt"]
base = receipt_path.resolve().parent
ignored_field = {ignore_field!r}
for field, expected_digest in receipt["artifact_sha256"].items():
    if field == ignored_field:
        continue
    artifact = base / receipt[field]
    if artifact.is_symlink() or not artifact.is_file():
        sys.exit(8)
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != expected_digest:
        sys.exit(9)
if {str(bool(mutate))}:
    metric = base / receipt["metric_artifact"]
    metric.write_text(json.dumps({{"mutated": True}}) + "\\n", encoding="utf-8")
print("OBSERVABILITY_DECISION=CREDIT")
print("OBSERVABILITY_GATE=PASS")
print("PATHWAY_RESULT=PASS")
print("RUNTIME_STATUS=PRESENT")
print("TELEMETRY_STATUS=PRESENT")
print("ALERT_STATUS=WIRED")
print("RUNBOOK_STATUS=DRILLED")
print("CANARY_STATUS=FAILED_AS_EXPECTED")
print("AUTHORIZED_STAGE=" + receipt["authorized_stage"])
print("CURRENT_VERDICT=" + receipt["current_verdict"])
print("WORK_ID=" + receipt["work_id"])
print("RECOMMENDATION_ID=" + receipt["recommendation_id"])
print("ENVIRONMENT_ID=" + receipt["environment_id"])
print("OBSERVABILITY_RECEIPT_SHA256=" + hashlib.sha256(receipt_path.read_bytes()).hexdigest())
""")
    artifacts["verifier_artifact"] = verifier
    runbook = json_artifacts["runbook_drill_artifact"]
    runbook["recovery_evidence"] = [{
        "artifact_field": field,
        "sha256": opl.sha256_file(artifacts[field]),
    } for field in ("metric_artifact", "log_artifact", "alert_artifact")]
    artifacts["runbook_drill_artifact"].write_text(json.dumps(runbook) + "\n", encoding="utf-8")
    evidence = _observability_evidence(stem)
    receipt = {
        "schema_version": 1,
        "receipt_type": "runtime_observability",
        "pathway_result": "PASS",
        "claim_scope": "runtime",
        "work_id": work_id,
        "recommendation_id": recommendation_id,
        "project": proj.name,
        "target_project": str(proj.resolve()),
        "runtime_digest": runtime_digest,
        "environment_id": environment_id,
        "environment_class": "test",
        "authorized_stage": "NONE",
        "current_verdict": "NO_PROMOTE",
        "runbook_version": "3am-v1",
        "issued_at": observed_at,
        "expires_at": expires_at,
        "verifier_source_sha256": opl.sha256_file(verifier),
        "metric_names": sorted(opl.OBSERVABILITY_METRIC_NAMES),
        "log_correlation_fields": sorted(opl.OBSERVABILITY_CORRELATION_FIELDS),
        **{field: True for field in opl.OBSERVABILITY_RUNTIME_TRUE_FIELDS},
        **{field: path.name for field, path in artifacts.items()},
        "artifact_sha256": {field: opl.sha256_file(path) for field, path in artifacts.items()},
    }
    receipt_path = write(
        f"out/operator-artifacts/{stem}.json",
        json.dumps({"status": "RUNTIME_OBSERVABILITY_RECEIPT", "observability_receipt": receipt}),
    )
    return evidence, receipt_path, receipt, artifacts["metric_artifact"], verifier


def test_observability_pre_runtime_hold_carries_without_credit_or_repeat():
    """A Tier-A verifier can validate a negative claim but cannot launder caller `pass`."""
    reset()
    proj = ROOT / "projects" / "observability-hold"
    proj.mkdir(parents=True, exist_ok=True)
    started, _ = run("work-start", [
        "--project", str(proj), "--goal", "runtime observability hold routing",
        "--tier", "live",
    ])
    work_id = started["work_id"]
    recommendation_id = "REC-observability-hold-fixture"
    target_project = str(proj.resolve())
    opl = load_cli("observability_hold")
    evidence = _observability_evidence("observability-hold")
    companion = write("out/operator-artifacts/observability-hold.json", json.dumps({
        "status": "PRE_RUNTIME_OBSERVABILITY_CONTRACT",
        "claim_scope": "SPEC_ONLY_NO_TELEMETRY",
        "pathway_result": "BLOCKED",
        "credits_pathway": False,
        "runtime_present": False,
        "telemetry_present": False,
        "alert_backend_present": False,
        "alerts_wired": False,
        "incident_drills_run": False,
        "authorized_stage": "NONE",
        "current_verdict": "NO_PROMOTE",
        "work_id": work_id,
        "recommendation_id": recommendation_id,
        "target_project": target_project,
    }))
    companion_sha256 = opl.sha256_file(companion)
    markers = (
        "OBSERVABILITY_DECISION=NO_CREDIT\\n"
        "OBSERVABILITY_GATE=BLOCKED_NO_RUNTIME\\n"
        "TELEMETRY_STATUS=ABSENT\\n"
        "ALERT_STATUS=NOT_WIRED\\n"
        "RUNBOOK_STATUS=SPECIFIED_NOT_DRILLED\\n"
        "AUTHORIZED_STAGE=NONE\\n"
        "CURRENT_VERDICT=NO_PROMOTE\\n"
        "PROJECT_TREE_MUTATION=NONE\\n"
        "EXTERNAL_SIDE_EFFECTS=0\\n"
        f"WORK_ID={work_id}\\n"
        f"RECOMMENDATION_ID={recommendation_id}\\n"
        f"TARGET_PROJECT={target_project}\\n"
        f"OBSERVABILITY_RECEIPT_SHA256={companion_sha256}\\n"
    )
    expected = {
        "work_id": work_id, "recommendation_id": recommendation_id,
        "target_project": target_project, "project": proj.name,
    }
    replay = opl.observability_receipt_from_evidence(evidence, {
        **expected, "work_id": "W-replayed", "recommendation_id": "REC-replayed",
        "target_project": str(ROOT / "projects" / "other"),
    })
    check(replay["outcome"] == "" and sum(
        "current proof context" in error for error in replay["errors"]
    ) == 3, "Tier-A cross-work, recommendation, and project replay fail closed")
    marker_text = markers.replace("\\n", "\n")
    missing_bindings = "\n".join(
        line for line in marker_text.splitlines()
        if not line.startswith(("WORK_ID=", "RECOMMENDATION_ID=", "TARGET_PROJECT=",
                                "OBSERVABILITY_RECEIPT_SHA256="))
    )
    check(not opl.observability_verifier_binding(
        missing_bindings, companion_sha256, read_json(companion), "blocked_no_runtime"
    )["bound"], "Tier-A missing context or receipt-digest markers fail closed")
    logged, _ = run("work-log", [
        "--work-id", work_id, "--pathway", "observability", "--kind", "verify",
        "--evidence", str(evidence), "--result", "pass", "--proof-type", "artifact",
        "--verify-cmd", f"printf '{markers}'", "--recommendation-id", recommendation_id,
    ])
    proof = next(record for record in logged["records"] if "verifier_strength" in record)
    check(not opl.proof_is_verified(proof),
          "caller-supplied pass cannot credit a blocked no-runtime observability receipt")
    carry = logged.get("carry_forward", {})
    check(carry.get("credits_pathway") is False
          and carry.get("pathway_outcome") == "blocked_no_runtime",
          "valid Tier-A markers create a blocked_no_runtime constraint carry-forward")
    check(opl.carry_forward_deferred_pathways(carry) == ["observability"],
          "structured blocked_no_runtime outcome defers observability")

    status, _ = run("work-status", ["--work-id", work_id])
    obs_status = next(
        entry["status"] for entry in status["summary"]["itinerary"]
        if entry["pathway"] == "observability"
    )
    check(obs_status == "required", "blocked observability carry-forward does not increase coverage")
    next_result, _ = run("pathway-next", ["--project", str(proj), "--work-id", work_id])
    check(next_result.get("recommended_pathway") != "observability"
          and "observability" in next_result.get("deferred_pathways", []),
          "observability is deferred while another prerequisite remains open")

    for entry in status["summary"]["itinerary"]:
        if entry.get("status") == "required" and entry.get("pathway") != "observability":
            run("work-cover", [
                "--work-id", work_id, "--pathway", entry["pathway"], "--na",
                "--reason", "fixture isolates the sole deferred-observability edge",
            ])
    recommendations = ROOT / "out/operator-intelligence/pathway-recommendations.ndjson"
    count_before = len(recommendations.read_text(encoding="utf-8").splitlines())
    terminal, _ = run("pathway-next", ["--project", str(proj), "--work-id", work_id])
    count_after = len(recommendations.read_text(encoding="utf-8").splitlines())
    check(terminal.get("blocked_on_deferred") is True
          and terminal.get("recommended_pathway") == "",
          "sole deferred observability returns a no-action prerequisite hold")
    check(terminal.get("recommendation_id") == "" and count_after == count_before,
          "sole deferred observability does not create a repeat recommendation")


def test_observability_runtime_receipt_completeness_binding_and_replay_guards():
    reset()
    proj = ROOT / "projects" / "observability-runtime"
    proj.mkdir(parents=True, exist_ok=True)
    started, _ = run("work-start", [
        "--project", str(proj), "--goal", "verify runtime observability", "--tier", "production-secure",
    ])
    work_id = started["work_id"]
    recommendation_id = "REC-observability-runtime-fixture"
    opl = load_cli("observability_runtime")
    evidence, receipt_path, receipt, metric, verifier = _observability_runtime_fixture(
        opl, proj, work_id, recommendation_id, "observability-runtime"
    )
    expected = {
        "work_id": work_id,
        "recommendation_id": recommendation_id,
        "project": proj.name,
        "target_project": str(proj.resolve()),
    }
    frozen_questions = {
        "CURRENT_AUTHORIZED_STAGE_AND_MODE",
        "DECISION_CYCLE_INTENT_AND_CLIENT_ORDER_IDENTIFIERS",
        "STRATEGY_DATA_POLICY_AND_MANIFEST_HASHES",
        "LAST_TRUSTED_MARKET_AND_PRIVATE_FEED_TIMESTAMPS",
        "ORDER_UNCERTAINTY_AND_LAST_VENUE_EVIDENCE",
        "RESERVATION_EXPOSURE_AND_LEDGER_MISMATCH_STATE",
        "WHY_HALT_ENTRIES_LATCHED",
        "WHY_RETRY_FLATTEN_AND_HALT_RELEASE_ARE_PROHIBITED",
        "EXACT_RECONCILIATION_EVIDENCE_STILL_MISSING",
        "HUMAN_DISPOSITION_REQUIRED_NEXT",
    }
    check(opl.OBSERVABILITY_RUNBOOK_QUESTION_IDS == frozen_questions,
          "runtime observability uses the exact frozen Tradebot 3am question set")
    loaded = opl.observability_receipt_from_evidence(evidence, expected)
    check(not loaded["errors"] and loaded["outcome"] == "runtime"
          and loaded["credit_scope"] == "runtime",
          "complete typed runtime observability receipt is structurally eligible")
    unsafe_authority = {**receipt, "authorized_stage": "PRODUCTION", "current_verdict": "PROMOTE"}
    unsafe_errors = opl.validate_observability_runtime_receipt(
        unsafe_authority, receipt_path.parent, expected
    )
    check(any("authorized_stage" in error for error in unsafe_errors)
          and any("current_verdict" in error for error in unsafe_errors),
          "runtime observability cannot raise Tradebot authority or promotion verdict")
    check(set(loaded["artifact_sha256"]) == set(opl.OBSERVABILITY_RECEIPT_ARTIFACT_FIELDS)
          and all(len(value) == 64 for value in loaded["artifact_sha256"].values()),
          "every metric/log/trace/alert/drill/canary/verifier artifact exists and is hashed")
    oversized = receipt_path.parent / "observability-runtime-oversized.json"
    oversized.write_bytes(b"{}" + b" " * 5_000_000 + b"NOT_JSON")
    _, oversized_errors = opl._read_strict_json_object(oversized, "oversized fixture")
    check(any("exceeds" in error for error in oversized_errors),
          "strict observability JSON rejects bytes beyond its parsing limit")
    invalid_utf8 = receipt_path.parent / "observability-runtime-invalid-utf8.json"
    invalid_utf8.write_bytes(b'{"status":"ok"}' + bytes([0xFF]))
    _, encoding_errors = opl._read_strict_json_object(invalid_utf8, "encoding fixture")
    check(any("valid UTF-8" in error for error in encoding_errors),
          "strict observability JSON rejects invalid UTF-8 instead of replacing bytes")
    nonfinite = receipt_path.parent / "observability-runtime-nonfinite.json"
    nonfinite.write_text('{"value":1e400}\n', encoding="utf-8")
    _, nonfinite_errors = opl._read_strict_json_object(nonfinite, "nonfinite fixture")
    check(any("non-finite" in error for error in nonfinite_errors),
          "strict observability JSON rejects numeric overflow to infinity")
    replay_errors = opl.validate_observability_runtime_receipt(
        receipt, receipt_path.parent,
        {"work_id": "W-replay", "recommendation_id": "REC-replay", "project": "other"},
    )
    check(sum("current proof context" in error for error in replay_errors) == 3,
          "work, recommendation, and project replay bindings fail closed")
    missing = {**receipt, "trace_artifact": "missing-trace.json"}
    check(any("existing file" in error for error in opl.validate_observability_runtime_receipt(
        missing, receipt_path.parent, expected
    )), "missing runtime evidence artifacts fail closed")

    incomplete_hashes = {**receipt, "artifact_sha256": {
        field: digest for field, digest in receipt["artifact_sha256"].items()
        if field != "trace_artifact"
    }}
    check(any("exact lowercase artifact_sha256 map" in error
              for error in opl.validate_observability_runtime_receipt(
                  incomplete_hashes, receipt_path.parent, expected
              )), "incomplete receipt artifact hash maps fail closed")

    dummy_metric = write(
        "out/operator-artifacts/observability-runtime-dummy-metric.json",
        json.dumps({"status": "looks-good"}) + "\n",
    )
    dummy_receipt = {
        **receipt,
        "metric_artifact": dummy_metric.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"], "metric_artifact": opl.sha256_file(dummy_metric),
        },
    }
    check(any("typed sample" in error for error in opl.validate_observability_runtime_receipt(
        dummy_receipt, receipt_path.parent, expected
    )), "dummy JSON artifact content cannot satisfy runtime observability")

    infinite_metric_payload = read_json(metric)
    infinite_metric_payload["samples"][0]["value"] = 1e400
    infinite_metric = write(
        "out/operator-artifacts/observability-runtime-infinite-metric.json",
        json.dumps(infinite_metric_payload) + "\n",
    )
    infinite_receipt = {
        **receipt,
        "metric_artifact": infinite_metric.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"], "metric_artifact": opl.sha256_file(infinite_metric),
        },
    }
    check(any("non-finite" in error or "typed sample" in error
              for error in opl.validate_observability_runtime_receipt(
                  infinite_receipt, receipt_path.parent, expected
              )), "non-finite metric samples cannot satisfy runtime observability")
    huge_metric_payload = read_json(metric)
    huge_metric_payload["samples"][0]["value"] = 10 ** 400
    huge_metric = write(
        "out/operator-artifacts/observability-runtime-huge-metric.json",
        json.dumps(huge_metric_payload) + "\n",
    )
    huge_receipt = {
        **receipt,
        "metric_artifact": huge_metric.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"], "metric_artifact": opl.sha256_file(huge_metric),
        },
    }
    check(any("typed sample" in error for error in opl.validate_observability_runtime_receipt(
        huge_receipt, receipt_path.parent, expected
    )), "oversized integer metric samples fail closed without raising")
    negative_metric_payload = read_json(metric)
    for sample in negative_metric_payload["samples"]:
        sample["value"] = -1
    negative_metric = write(
        "out/operator-artifacts/observability-runtime-negative-metric.json",
        json.dumps(negative_metric_payload) + "\n",
    )
    negative_receipt = {
        **receipt,
        "metric_artifact": negative_metric.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"], "metric_artifact": opl.sha256_file(negative_metric),
        },
    }
    check(any("typed sample" in error for error in opl.validate_observability_runtime_receipt(
        negative_receipt, receipt_path.parent, expected
    )), "negative ages, counters, latency, heartbeat, and drawdown fail domain validation")

    unbounded_metric_payload = read_json(metric)
    unbounded_metric_payload["samples"][0]["labels"]["client_order_id"] = "client-123"
    unbounded_metric = write(
        "out/operator-artifacts/observability-runtime-unbounded-metric.json",
        json.dumps(unbounded_metric_payload) + "\n",
    )
    unbounded_receipt = {
        **receipt,
        "metric_artifact": unbounded_metric.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"], "metric_artifact": opl.sha256_file(unbounded_metric),
        },
    }
    check(any("typed sample" in error for error in opl.validate_observability_runtime_receipt(
        unbounded_receipt, receipt_path.parent, expected
    )), "identifier and unbounded metric labels cannot satisfy runtime observability")

    false_log_payload = read_json(receipt_path.parent / receipt["log_artifact"])
    false_log_payload["records"] = [{
        "event_name": "tradebot.halt.latched",
        **{field: False for field in opl.OBSERVABILITY_CORRELATION_FIELDS},
    }]
    false_log = write(
        "out/operator-artifacts/observability-runtime-false-log.json",
        json.dumps(false_log_payload) + "\n",
    )
    false_log_receipt = {
        **receipt,
        "log_artifact": false_log.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"], "log_artifact": opl.sha256_file(false_log),
        },
    }
    check(any("correlated structured log" in error
              for error in opl.validate_observability_runtime_receipt(
                  false_log_receipt, receipt_path.parent, expected
              )), "false and empty-like correlation values cannot satisfy runtime observability")

    inverted_log_payload = read_json(receipt_path.parent / receipt["log_artifact"])
    inverted_log_payload["records"][0]["occurred_at"] = (
        opl.parse_ts(inverted_log_payload["records"][0]["market_event_ts"])
        - opl.timedelta(seconds=1)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    inverted_log = write(
        "out/operator-artifacts/observability-runtime-inverted-log.json",
        json.dumps(inverted_log_payload) + "\n",
    )
    inverted_log_receipt = {
        **receipt,
        "log_artifact": inverted_log.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"], "log_artifact": opl.sha256_file(inverted_log),
        },
    }
    check(any("correlated structured log" in error
              for error in opl.validate_observability_runtime_receipt(
                  inverted_log_receipt, receipt_path.parent, expected
              )), "market, occurrence, and observation timestamps must be coherently ordered")

    drill_path = receipt_path.parent / receipt["runbook_drill_artifact"]
    vacuous_drill_payload = read_json(drill_path)
    vacuous_drill_payload["answered_questions"] = [{
        "question_id": question_id,
        "answer": str(index),
        "evidence_refs": ["runbook_drill_artifact"],
    } for index, question_id in enumerate(sorted(opl.OBSERVABILITY_RUNBOOK_QUESTION_IDS))]
    vacuous_drill_payload["operator_disposition"] = "x"
    vacuous_drill_payload["recovery_evidence"] = [{
        "artifact_field": "runbook_drill_artifact", "sha256": opl.sha256_file(drill_path),
    }]
    vacuous_drill = write(
        "out/operator-artifacts/observability-runtime-vacuous-drill.json",
        json.dumps(vacuous_drill_payload) + "\n",
    )
    vacuous_drill_receipt = {
        **receipt,
        "runbook_drill_artifact": vacuous_drill.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"],
            "runbook_drill_artifact": opl.sha256_file(vacuous_drill),
        },
    }
    check(any("complete safe 3am drill" in error
              for error in opl.validate_observability_runtime_receipt(
                  vacuous_drill_receipt, receipt_path.parent, expected
              )), "vacuous or circular 3am drill answers cannot earn observability credit")

    decoy_drill_payload = read_json(drill_path)
    decoy_drill_payload["answered_questions"][0]["question_id"] = "GENERIC_ALERT_RECEIVED"
    decoy_drill = write(
        "out/operator-artifacts/observability-runtime-decoy-drill.json",
        json.dumps(decoy_drill_payload) + "\n",
    )
    decoy_drill_receipt = {
        **receipt,
        "runbook_drill_artifact": decoy_drill.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"],
            "runbook_drill_artifact": opl.sha256_file(decoy_drill),
        },
    }
    check(any("complete safe 3am drill" in error
              for error in opl.validate_observability_runtime_receipt(
                  decoy_drill_receipt, receipt_path.parent, expected
              )), "the frozen ten-question Tradebot drill cannot be replaced by a generic decoy")
    filler_drill_payload = read_json(drill_path)
    for answer in filler_drill_payload["answered_questions"]:
        answer["answer"] = "This identical generic filler sentence contains no incident answer."
        answer["evidence_refs"] = ["metric_artifact"]
    filler_drill_payload["recovery_evidence"] = [{
        "artifact_field": "metric_artifact",
        "sha256": receipt["artifact_sha256"]["metric_artifact"],
    }]
    filler_drill = write(
        "out/operator-artifacts/observability-runtime-filler-drill.json",
        json.dumps(filler_drill_payload) + "\n",
    )
    filler_receipt = {
        **receipt,
        "runbook_drill_artifact": filler_drill.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"],
            "runbook_drill_artifact": opl.sha256_file(filler_drill),
        },
    }
    check(any("complete safe 3am drill" in error
              for error in opl.validate_observability_runtime_receipt(
                  filler_receipt, receipt_path.parent, expected
              )), "generic filler and single-artifact recovery cannot satisfy the frozen drill")

    semantic_filler_payload = read_json(drill_path)
    for answer in semantic_filler_payload["answered_questions"]:
        answer["answer"] = "This identical generic filler sentence contains no incident answer."
        contract = opl.OBSERVABILITY_RUNBOOK_ANSWER_CONTRACT[answer["question_id"]]
        for field, kind in contract["fields"].items():
            if kind in {"identifier", "enum"}:
                answer["facts"][field] = "x"
    semantic_filler = write(
        "out/operator-artifacts/observability-runtime-semantic-filler-drill.json",
        json.dumps(semantic_filler_payload) + "\n",
    )
    semantic_filler_receipt = {
        **receipt,
        "runbook_drill_artifact": semantic_filler.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"],
            "runbook_drill_artifact": opl.sha256_file(semantic_filler),
        },
    }
    check(any("complete safe 3am drill" in error
              for error in opl.validate_observability_runtime_receipt(
                  semantic_filler_receipt, receipt_path.parent, expected
              )), "semantic filler fails even when evidence references and recovery hashes remain valid")

    benign_log_payload = read_json(receipt_path.parent / receipt["log_artifact"])
    benign_log_payload["records"][0].update({
        "event_name": "tradebot.proposal.created",
        "risk_decision": "APPROVE",
        "reason_code": "POLICY_PASS",
    })
    benign_log = write(
        "out/operator-artifacts/observability-runtime-benign-log.json",
        json.dumps(benign_log_payload) + "\n",
    )
    benign_runbook_payload = read_json(drill_path)
    for recovery in benign_runbook_payload["recovery_evidence"]:
        if recovery["artifact_field"] == "log_artifact":
            recovery["sha256"] = opl.sha256_file(benign_log)
    benign_runbook = write(
        "out/operator-artifacts/observability-runtime-benign-runbook.json",
        json.dumps(benign_runbook_payload) + "\n",
    )
    benign_incident_receipt = {
        **receipt,
        "log_artifact": benign_log.name,
        "runbook_drill_artifact": benign_runbook.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"],
            "log_artifact": opl.sha256_file(benign_log),
            "runbook_drill_artifact": opl.sha256_file(benign_runbook),
        },
    }
    check(any("structured incident record" in error
              for error in opl.validate_observability_runtime_receipt(
                  benign_incident_receipt, receipt_path.parent, expected
              )), "a healthy proposal event cannot be relabeled as the frozen halt incident")

    false_recovery_payload = read_json(drill_path)
    human_answer = next(
        answer for answer in false_recovery_payload["answered_questions"]
        if answer["question_id"] == "HUMAN_DISPOSITION_REQUIRED_NEXT"
    )
    human_answer["facts"]["human_disposition"] = "RECOVERED_KEEP_NO_PROMOTE"
    false_recovery_payload["operator_disposition"] = "RECOVERED_KEEP_NO_PROMOTE"
    false_recovery = write(
        "out/operator-artifacts/observability-runtime-false-recovery-drill.json",
        json.dumps(false_recovery_payload) + "\n",
    )
    false_recovery_receipt = {
        **receipt,
        "runbook_drill_artifact": false_recovery.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"],
            "runbook_drill_artifact": opl.sha256_file(false_recovery),
        },
    }
    check(any("complete safe 3am drill" in error
              for error in opl.validate_observability_runtime_receipt(
                  false_recovery_receipt, receipt_path.parent, expected
              )), "an unresolved acknowledgement and mismatch cannot claim recovered disposition")

    symlink = receipt_path.parent / "observability-runtime-symlink-trace.json"
    symlink.symlink_to(receipt["trace_artifact"])
    symlink_receipt = {
        **receipt,
        "trace_artifact": symlink.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"], "trace_artifact": receipt["artifact_sha256"]["trace_artifact"],
        },
    }
    check(any("must not be a symlink" in error for error in opl.validate_observability_runtime_receipt(
        symlink_receipt, receipt_path.parent, expected
    )), "symlinked observability artifacts fail closed")
    traversal = {**receipt, "log_artifact": "../../outside-log.json"}
    check(any("without traversal" in error for error in opl.validate_observability_runtime_receipt(
        traversal, receipt_path.parent, expected
    )), "artifact traversal outside the companion directory fails closed")

    stale_time = (opl.utc_now() - opl.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale_expiry = (opl.utc_now() - opl.timedelta(days=2, hours=-1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale_receipt = {**receipt, "issued_at": stale_time, "expires_at": stale_expiry}
    check(any("stale" in error for error in opl.validate_observability_runtime_receipt(
        stale_receipt, receipt_path.parent, expected
    )), "stale runtime observability receipts fail closed")
    overlong_receipt = {
        **receipt,
        "expires_at": (opl.utc_now() + opl.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    check(any("overlong" in error for error in opl.validate_observability_runtime_receipt(
        overlong_receipt, receipt_path.parent, expected
    )), "overlong observability receipt validity windows fail closed")
    skewed_metric_payload = read_json(metric)
    skewed_metric_payload["observed_at"] = (
        opl.utc_now() - opl.timedelta(minutes=10)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    skewed_metric = write(
        "out/operator-artifacts/observability-runtime-skewed-metric.json",
        json.dumps(skewed_metric_payload) + "\n",
    )
    skewed_receipt = {
        **receipt,
        "metric_artifact": skewed_metric.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"], "metric_artifact": opl.sha256_file(skewed_metric),
        },
    }
    check(any("observation window" in error
              for error in opl.validate_observability_runtime_receipt(
                  skewed_receipt, receipt_path.parent, expected
              )), "runtime observability artifacts must share one coherent observation window")
    metric_payload = read_json(metric)
    metric_payload["observed_at"] = (
        opl.utc_now() + opl.timedelta(minutes=10)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    future_metric = write(
        "out/operator-artifacts/observability-runtime-future-metric.json",
        json.dumps(metric_payload) + "\n",
    )
    future_receipt = {
        **receipt,
        "metric_artifact": future_metric.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"], "metric_artifact": opl.sha256_file(future_metric),
        },
    }
    check(any("in the future" in error for error in opl.validate_observability_runtime_receipt(
        future_receipt, receipt_path.parent, expected
    )), "future-dated observability artifacts fail closed")
    metric_payload["observed_at"] = stale_time
    stale_metric = write(
        "out/operator-artifacts/observability-runtime-stale-metric.json",
        json.dumps(metric_payload) + "\n",
    )
    stale_artifact_receipt = {
        **receipt,
        "metric_artifact": stale_metric.name,
        "artifact_sha256": {
            **receipt["artifact_sha256"], "metric_artifact": opl.sha256_file(stale_metric),
        },
    }
    check(any("is stale" in error for error in opl.validate_observability_runtime_receipt(
        stale_artifact_receipt, receipt_path.parent, expected
    )), "stale observability artifacts fail closed")

    trusted_command = opl.parse_observability_verifier_command(
        f"{sys.executable} {verifier} {receipt_path}", proj, verifier
    )
    check(not trusted_command["errors"]
          and trusted_command["argv"][:2] == [sys.executable, str(verifier.resolve())],
          "current sys.executable is accepted and normalized with the bound verifier in script position")
    check(opl.parse_observability_verifier_command(
        f"{verifier} {receipt_path}", proj, verifier
    )["errors"], "direct or shebang verifier execution is rejected")
    check(opl.parse_observability_verifier_command(
        f"{sys.executable} -I {verifier} {receipt_path}", proj, verifier
    )["errors"], "interpreter wrapper options before the verifier are rejected")
    fake_python = write(
        "out/fake-python-bin/python3", "#!/bin/sh\nexec /usr/bin/true\n"
    )
    fake_python.chmod(0o755)
    check(opl.parse_observability_verifier_command(
        f"{fake_python} {verifier} {receipt_path}", proj, verifier
    )["errors"], "an arbitrary executable named python3 is rejected")
    fake_link = ROOT / "out/fake-python-link-bin/python3"
    fake_link.parent.mkdir(parents=True, exist_ok=True)
    fake_link.symlink_to(fake_python)
    check(opl.parse_observability_verifier_command(
        f"{fake_link} {verifier} {receipt_path}", proj, verifier
    )["errors"], "a python3 symlink to an untrusted executable is rejected")
    decoy = write("out/operator-artifacts/observability-runtime-decoy.py", "print('decoy')\n")
    decoy_command = f"{sys.executable} {decoy} {verifier} {receipt_path}"
    check(opl.parse_observability_verifier_command(
        decoy_command, proj, verifier
    )["errors"], "a decoy script followed by the bound verifier token is rejected")
    composed_command = f"{sys.executable} {verifier} {receipt_path} && true"
    check(opl.parse_observability_verifier_command(
        composed_command, proj, verifier
    )["errors"], "shell-composed observability verifier commands are rejected")

    valid_stdout = subprocess.run(
        [sys.executable, str(verifier), str(receipt_path)],
        capture_output=True, text=True, check=True,
    ).stdout
    check(opl.observability_verifier_binding(
        valid_stdout, opl.sha256_file(receipt_path), receipt, "runtime"
    )["bound"] is True, "positive verifier markers bind exactly to runtime receipt context and digest")
    duplicate = "OBSERVABILITY_DECISION=NO_CREDIT\n" + valid_stdout
    check(opl.observability_verifier_binding(
        duplicate, opl.sha256_file(receipt_path), receipt, "runtime"
    )["bound"] is False, "duplicate contradictory observability markers fail closed")

    logged, _ = run("work-log", [
        "--work-id", work_id, "--pathway", "observability", "--kind", "verify",
        "--evidence", str(evidence), "--result", "pass", "--proof-type", "artifact",
        "--project", str(proj),
        "--verify-cmd", f"{sys.executable} {verifier} {receipt_path}",
        "--recommendation-id", recommendation_id,
    ])
    proof = next(record for record in logged["records"] if "verifier_strength" in record)
    check(proof.get("canary_mutant_failed") is True and not opl.proof_is_verified(proof),
          "a structurally complete runtime receipt stays uncredited without a trusted verifier root")
    check(opl.OBSERVABILITY_RUNTIME_VERIFIER_TRUST_STATE == "TRUSTED_VERIFIER_NOT_CONFIGURED"
          and not opl.OBSERVABILITY_TRUSTED_VERIFIER_SHA256,
          "runtime observability verifier trust is explicitly unconfigured and fail closed")
    check(set(proof.get("observability_artifact_canary_results", {}))
          == set(opl.OBSERVABILITY_RECEIPT_ARTIFACT_FIELDS)
          and all(proof["observability_artifact_canary_results"].values()),
          "every one of the seven receipt-bound artifacts independently trips the verifier")
    check(proof.get("observability_artifact_restoration_sha256")
          == proof.get("observability_artifact_sha256"),
          "every mutation canary restores the exact pre-run artifact hash")
    generic = {
        "pathway": "quality", "result": "pass", "verifier_strength": "executed",
        "exit_code": 0, "trivial_verifier": False, "canary_mutant_failed": None,
    }
    check(opl.proof_is_verified(generic),
          "observability receipt gates do not change generic non-observability verification")


def test_observability_proof_rejects_verifier_that_ignores_one_bound_artifact():
    reset()
    proj = ROOT / "projects" / "observability-ignored-artifact"
    proj.mkdir(parents=True, exist_ok=True)
    started, _ = run("work-start", [
        "--project", str(proj), "--goal", "reject partial observability verifier coverage",
        "--tier", "production-secure",
    ])
    work_id = started["work_id"]
    recommendation_id = "REC-observability-ignored-artifact"
    opl = load_cli("observability_ignored_artifact")
    evidence, receipt_path, _receipt, _metric, verifier = _observability_runtime_fixture(
        opl, proj, work_id, recommendation_id, "observability-ignored-artifact",
        ignore_field="log_artifact",
    )
    logged, _ = run("work-log", [
        "--work-id", work_id, "--pathway", "observability", "--kind", "verify",
        "--evidence", str(evidence), "--result", "pass", "--proof-type", "artifact",
        "--project", str(proj),
        "--verify-cmd", f"{sys.executable} {verifier} {receipt_path}",
        "--recommendation-id", recommendation_id,
    ])
    proof = next(record for record in logged["records"] if "verifier_strength" in record)
    results = proof.get("observability_artifact_canary_results", {})
    check(results.get("log_artifact") is False
          and all(value is True for field, value in results.items() if field != "log_artifact"),
          "one ignored receipt-bound artifact is detected by its independent mutation canary")
    check(not opl.proof_is_verified(proof),
          "a verifier that ignores any one observability artifact cannot earn credit")


def test_observability_proof_rejects_stateful_invocation_counter_verifier():
    """A schedule-aware verifier cannot earn credit without an external verifier trust root."""
    reset()
    proj = ROOT / "projects" / "observability-stateful-verifier"
    proj.mkdir(parents=True, exist_ok=True)
    work_id = "W-observability-stateful-verifier"
    recommendation_id = "REC-observability-stateful-verifier"
    opl = load_cli("observability_stateful_verifier")
    evidence, receipt_path, receipt, _metric, verifier = _observability_runtime_fixture(
        opl, proj, work_id, recommendation_id, "observability-stateful-verifier"
    )
    counter = receipt_path.parent / "observability-stateful-counter.txt"
    verifier.write_text(f"""import hashlib
from pathlib import Path
import sys

counter = Path({str(counter)!r})
count = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(count))
if count in {{3, 6, 9, 12, 15, 18, 21, 23, 24, 25, 26, 27, 28, 29}}:
    raise SystemExit(9)
receipt_path = Path(sys.argv[1])
print("OBSERVABILITY_DECISION=CREDIT")
print("OBSERVABILITY_GATE=PASS")
print("PATHWAY_RESULT=PASS")
print("RUNTIME_STATUS=PRESENT")
print("TELEMETRY_STATUS=PRESENT")
print("ALERT_STATUS=WIRED")
print("RUNBOOK_STATUS=DRILLED")
print("CANARY_STATUS=FAILED_AS_EXPECTED")
print("AUTHORIZED_STAGE=" + {receipt["authorized_stage"]!r})
print("CURRENT_VERDICT=" + {receipt["current_verdict"]!r})
print("WORK_ID=" + {work_id!r})
print("RECOMMENDATION_ID=" + {recommendation_id!r})
print("ENVIRONMENT_ID=" + {receipt["environment_id"]!r})
print("OBSERVABILITY_RECEIPT_SHA256=" + hashlib.sha256(receipt_path.read_bytes()).hexdigest())
""", encoding="utf-8")
    receipt["verifier_source_sha256"] = opl.sha256_file(verifier)
    receipt["artifact_sha256"] = {
        **receipt["artifact_sha256"], "verifier_artifact": opl.sha256_file(verifier),
    }
    receipt_path.write_text(json.dumps({
        "status": "RUNTIME_OBSERVABILITY_RECEIPT", "observability_receipt": receipt,
    }), encoding="utf-8")
    import argparse
    args = argparse.Namespace(
        evidence=str(evidence), work_id=work_id, pathway="observability",
        gate="observability-gate", kind="verify", result="pass", stale_after_days=30,
        verified_by="", recommendation_id=recommendation_id,
        verify_cmd=f"{sys.executable} {verifier} {receipt_path}", reviewer="",
        proof_type="artifact", canary_target=None, project=str(proj),
    )
    proof, warning = opl.build_proof_record(args, projects_root=str(ROOT / "projects"))
    check(not opl.proof_is_verified(proof),
          "a schedule-aware invocation-counter verifier cannot earn runtime observability credit")
    check(opl.OBSERVABILITY_RUNTIME_VERIFIER_TRUST_STATE != "CONFIGURED_AND_VERIFIED",
          "black-box mutation behavior cannot substitute for a configured verifier trust root")
    check(warning is not None and warning.get("id") == "proof-logged-unverified",
          "stateful observability verifier produces a loud unverified finding")


def test_observability_proof_revalidates_receipt_freshness_after_canaries():
    """An unchanged receipt that expires while its verifier runs cannot earn credit."""
    reset()
    proj = ROOT / "projects" / "observability-expiry"
    proj.mkdir(parents=True, exist_ok=True)
    work_id = "W-observability-expiry"
    recommendation_id = "REC-observability-expiry"
    opl = load_cli("observability_expiry")
    evidence, receipt_path, receipt, _metric, verifier = _observability_runtime_fixture(
        opl, proj, work_id, recommendation_id, "observability-expiry"
    )
    issued_at = opl.parse_ts(receipt["issued_at"])
    expires_at = issued_at + opl.timedelta(minutes=1)
    receipt["expires_at"] = expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    receipt_path.write_text(json.dumps({
        "status": "RUNTIME_OBSERVABILITY_RECEIPT",
        "observability_receipt": receipt,
    }), encoding="utf-8")

    before_expiry = issued_at + opl.timedelta(seconds=30)
    after_expiry = issued_at + opl.timedelta(seconds=61)
    clock_values = iter((before_expiry, after_expiry))

    def controlled_utc_now():
        return next(clock_values, after_expiry)

    opl.utc_now = controlled_utc_now
    import argparse
    args = argparse.Namespace(
        evidence=str(evidence), work_id=work_id, pathway="observability",
        gate="observability-gate", kind="verify", result="pass",
        stale_after_days=30, verified_by="", recommendation_id=recommendation_id,
        verify_cmd=f"{sys.executable} {verifier} {receipt_path}", reviewer="",
        proof_type="artifact", canary_target=None, project=str(proj),
    )
    proof, warning = opl.build_proof_record(
        args, projects_root=str(ROOT / "projects")
    )
    canary_results = proof.get("observability_artifact_canary_results", {})
    check(set(canary_results) == set(opl.OBSERVABILITY_RECEIPT_ARTIFACT_FIELDS)
          and all(canary_results.values()),
          "receipt expiry fixture runs and passes all seven independent mutation canaries")
    check(proof.get("observability_post_receipt_sha256")
          == proof.get("observability_receipt_sha256")
          and proof.get("observability_post_observability_artifact_sha256")
          == proof.get("observability_artifact_sha256"),
          "receipt expiry fixture keeps receipt and artifact bytes unchanged")
    snapshot_errors = proof.get("observability_snapshot_errors", [])
    check(proof.get("observability_snapshot_stable") is False
          and any("post-verification observability receipt is invalid" in error
                  and "stale" in error for error in snapshot_errors),
          "post-canary receipt expiry fails semantic snapshot revalidation")
    check(proof.get("observability_credit_scope") == ""
          and proof.get("observability_outcome") == ""
          and not opl.proof_is_verified(proof),
          "an expired post-verifier receipt cannot earn observability credit")
    check(warning is not None and warning.get("id") == "proof-logged-unverified",
          "post-verifier receipt expiry produces a loud unverified finding")


def test_observability_proof_rejects_mid_verification_artifact_mutation():
    reset()
    proj = ROOT / "projects" / "observability-mutation"
    proj.mkdir(parents=True, exist_ok=True)
    started, _ = run("work-start", [
        "--project", str(proj), "--goal", "reject mutable observability evidence",
        "--tier", "production-secure",
    ])
    work_id = started["work_id"]
    recommendation_id = "REC-observability-mutation-fixture"
    opl = load_cli("observability_mutation")
    evidence, receipt_path, _receipt, metric, verifier = _observability_runtime_fixture(
        opl, proj, work_id, recommendation_id, "observability-mutation", mutate=True
    )
    logged, _ = run("work-log", [
        "--work-id", work_id, "--pathway", "observability", "--kind", "verify",
        "--evidence", str(evidence), "--result", "pass", "--proof-type", "artifact",
        "--project", str(proj),
        "--verify-cmd", f"{sys.executable} {verifier} {receipt_path}",
        "--recommendation-id", recommendation_id,
    ])
    proof = next(record for record in logged["records"] if "verifier_strength" in record)
    check(proof.get("canary_mutant_failed") is False
          and proof.get("observability_artifact_canary_errors"),
          "TOCTOU fixture fails the per-artifact restoration canary")
    check(proof.get("observability_snapshot_stable") is False
          and any("artifacts changed" in error for error in proof.get("observability_snapshot_errors", [])),
          "post-verifier hashes detect observability artifact mutation")
    check(not opl.proof_is_verified(proof),
          "mutated observability evidence cannot receive pathway credit")
    status, _ = run("work-status", ["--work-id", work_id])
    obs_status = next(
        entry["status"] for entry in status["summary"]["itinerary"]
        if entry["pathway"] == "observability"
    )
    check(obs_status == "required", "TOCTOU failure leaves observability coverage open")


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
    json_baton = json.dumps({
        "scope": "Mechanical contract extraction with durable continuity.",
        "lineage": {"source": "engine constants"},
        "verification": {"fidelity": "24/24"},
        "what_changed": ["The contract was extracted."],
        "more_relevant": ["Phase 2 containment."],
        "less_relevant": [],
        "next_pathway_must_use": ["Read the locked constraints."],
        "do_not_do_yet": ["Do not resolve arbitrary project paths yet."],
        "open_decisions": [],
        "active_risk_overlays": ["rollback"],
    })
    parsed_json = opl.extract_carry_forward_sections(json_baton)
    check(opl.check_verifier_template("data", json_baton)["valid"]
          and parsed_json.get("summary")
          == "Mechanical contract extraction with durable continuity."
          and parsed_json.get("do_not_do_yet")
          == ["Do not resolve arbitrary project paths yet."]
          and parsed_json.get("open_decisions") == [],
          "strict JSON receipts preserve complete carry-forward fields, including empty lists")
    duplicate_json = json_baton[:-1] + ',"what_changed":["shadowed"]}'
    check(not opl.check_verifier_template("data", duplicate_json)["valid"],
          "duplicate-key JSON receipts fail the carry-forward template closed")
    markdown_suffix = baton + "\nlineage\nverification"
    duplicate_with_headings = (
        '{\n  "summary": "first",\n  "summary": "second"\n}\n' + markdown_suffix
    )
    nan_with_headings = '{"summary": NaN}\n' + markdown_suffix
    check(not opl.check_verifier_template("data", duplicate_with_headings)["valid"]
          and not opl.check_verifier_template("data", nan_with_headings)["valid"],
          "invalid JSON candidates cannot fall through to valid-looking Markdown headings")
    empty_json_baton = json.dumps({
        "summary": "An explicitly empty continuity fixture.",
        "lineage": {},
        "verification": {},
        **{field: [] for field in opl.CARRY_FORWARD_LIST_FIELDS},
    })
    empty_evidence = write("out/operator-artifacts/empty-json-baton.json", empty_json_baton)
    empty_record = opl.build_carry_forward_record({
        "work_id": "W-empty-json-baton",
        "project": "fixture-project",
        "project_path": str(ROOT / "projects" / "fixture-project"),
        "pathway": "data",
        "evidence_path": str(empty_evidence),
        "artifact_sha256": opl.sha256_file(empty_evidence),
        "proof_id": "P-empty-json-baton",
        "result": "pass",
        "verifier_strength": "executed",
        "exit_code": 0,
        "trivial_verifier": False,
        "canary_mutant_failed": True,
    }, {
        "project": str(ROOT / "projects" / "fixture-project"),
        "project_name": "fixture-project",
        "risk_overlays": [{"id": "rollback"}],
    })
    check(empty_record is not None
          and all(empty_record[field] == [] for field in opl.CARRY_FORWARD_LIST_FIELDS),
          "the carry-forward builder preserves every explicit empty JSON list without fallback")


def test_phase1_g1_verifier_rejects_ambiguous_receipts():
    """The registered G1 verifier accepts only its exact, unambiguous continuity receipt."""
    import importlib.util

    reset()
    verifier_path = (
        REPO / ".planning/per-project-observability-contracts/quality/verify_phase1_fidelity.py"
    )
    spec = importlib.util.spec_from_file_location("phase1_g1_fidelity_verifier", verifier_path)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    receipt_path = (
        REPO / ".planning/per-project-observability-contracts/quality/receipt-phase1-g1.json"
    )
    raw = receipt_path.read_text(encoding="utf-8")
    contract_sha256 = verifier.sha256_bytes(verifier.CONTRACT_PATH.read_bytes())
    check(verifier.validate_g1_receipt(receipt_path, contract_sha256) == [],
          "the canonical G1 receipt passes its strict verifier")

    duplicate = raw.replace(
        '  "summary": ',
        '  "summary": "attacker-first-value",\n  "summary": ',
        1,
    )
    nonfinite = raw[:-2] + ',\n  "ambiguous": NaN\n}\n'
    duplicate_path = write("out/g1-mutants/duplicate.json", duplicate)
    nonfinite_path = write("out/g1-mutants/nonfinite.json", nonfinite)
    check(verifier.validate_g1_receipt(duplicate_path, contract_sha256)
          and verifier.validate_g1_receipt(nonfinite_path, contract_sha256),
          "duplicate keys and non-finite values fail the G1 verifier closed")

    parsed = json.loads(raw)
    non_string_path = write(
        "out/g1-mutants/non-string-list.json",
        json.dumps({**parsed, "open_decisions": [42]}),
    )
    missing_lineage = dict(parsed)
    missing_lineage.pop("lineage")
    missing_lineage_path = write(
        "out/g1-mutants/missing-lineage.json", json.dumps(missing_lineage)
    )
    wrong_verification_path = write(
        "out/g1-mutants/wrong-verification.json",
        json.dumps({**parsed, "verification": "not a receipt object"}),
    )
    check(verifier.validate_g1_receipt(non_string_path, contract_sha256)
          and verifier.validate_g1_receipt(missing_lineage_path, contract_sha256)
          and verifier.validate_g1_receipt(wrong_verification_path, contract_sha256),
          "malformed carry-forward, lineage, and verification fields cannot earn G1 credit")


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
              "--verify-cmd", passing_verifier_cmd(name="boundary-pass.py")]

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

    run("proof-add", common + [
        "--pathway", "govern", "--verify-cmd",
        text_guard_verifier_cmd("value.txt", "100", name="dirty-guard.py"),
    ])
    named = [json.loads(l) for l in proofs_file.read_text().splitlines() if l.strip()][-1]
    check(named.get("canary_mutant_failed") is True and named.get("trivial_verifier") is False,
          "a dirty registered checkout selects the verifier-named changed file")
    check(named.get("canary_target") == "value.txt" and named.get("canary_target_source") == "verifier_reference",
          "automatic selection records only the relevant repository-relative file")

    run("proof-add", common + [
        "--pathway", "quality", "--verify-cmd", passing_verifier_cmd(name="dirty-opaque.py"),
    ])
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


def test_pathway_prompt_never_retiers_an_existing_outcome_via_work_start():
    """commands/pathway.md is the contract the model executes, and it had NO coverage until
    2026-08-09. The defect this guards actually shipped: the `--max` section told the reader to
    re-run `work-start` with the same goal to retier an existing outcome. `stable_work_id` hashes
    the current DAY (see below), so on any later date that opens a SECOND outcome and orphans every
    proof on the first. The safe retier path is `work-cover --add`, which is keyed on --work-id."""
    doc = (HERE / ".." / ".." / "commands" / "pathway.md").resolve()
    check(doc.is_file(), f"commands/pathway.md is reachable from the test dir ({doc})")
    if not doc.is_file():
        return
    text = doc.read_text(encoding="utf-8")

    # The day-in-the-hash property that makes work-start unsafe for retiering. If this ever stops
    # being true the guard below can be relaxed — but it must be re-proved, not assumed.
    cli_src = CLI.read_text(encoding="utf-8")
    fn = cli_src.split("def stable_work_id(", 1)[1].split("\ndef ", 1)[0]
    check("strftime(\"%Y%m%d\")" in fn and "short_hash(" in fn and "day" in fn,
          "stable_work_id still hashes the calendar day, so a same-goal re-run forks on a new date")

    max_section = text.split("## `--max`", 1)[-1].split("\n## ", 1)[0] if "## `--max`" in text else ""
    check(bool(max_section), "the --max flag advertised in argument-hint has a body section defining it")
    check("work-cover" in max_section and "--add" in max_section,
          "--max retiers an existing outcome through work-cover --add (keyed on --work-id)")
    check("Never re-run `work-start` to retier" in max_section,
          "--max explicitly forbids retiering an existing outcome via work-start (proof-fork guard)")

    # Modifier stripping must be defined BEFORE intent classification, or `go --max` falls through
    # to START and mints a work item whose goal is literally "go --max".
    strip_at = text.find("Strip modifiers FIRST")
    intent_at = text.find("Remaining text = intent")
    check(strip_at != -1 and intent_at != -1 and strip_at < intent_at,
          "the modifier-strip rule is stated before intent classification, not after")

    # A rigor modifier must never promote a read-only verb into an executing one.
    check("rigor modifier only" in max_section,
          "--max is documented as rigor-only, never widening authority")


def test_resolve_project_dir_nesting_and_unverified_proof_loudness():
    """2026-08-10 regression: a work item storing the bare name of an
    owner-family-nested project (koho/consultops-live) resolved to no
    directory, the verifier never ran (cwd_invalid), and the proof parked in
    logged_unverified with a clean-looking summary. Two guarantees now: the
    resolver searches one owner-family level down (unique hit only), and a
    proof that will not credit returns a loud warn finding at log time."""
    reset()
    import importlib.util
    spec = importlib.util.spec_from_file_location("opl_nesting", CLI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    projects = ROOT / "projects"
    (projects / "koho" / "consultops-live").mkdir(parents=True)
    (projects / "flatproj").mkdir()
    (projects / "_archive" / "shadowed").mkdir(parents=True)
    (projects / "koho" / "dupe").mkdir()
    (projects / "prettyfly" / "dupe").mkdir(parents=True)

    check(
        mod.resolve_project_dir("consultops-live", projects_root=str(projects))
        == str((projects / "koho" / "consultops-live").resolve()),
        "owner-family nested project resolves one level down",
    )
    check(
        mod.resolve_project_dir("flatproj", projects_root=str(projects))
        == str((projects / "flatproj").resolve()),
        "flat project still resolves first",
    )
    check(
        mod.resolve_project_dir("dupe", projects_root=str(projects)) == "dupe",
        "ambiguous nested name refuses to guess a cwd",
    )
    check(
        mod.resolve_project_dir("shadowed", projects_root=str(projects)) == "shadowed",
        "meta directories (_archive) never satisfy the nested search",
    )

    import argparse
    ev = write("out/proof-evidence.md", "# evidence\n")
    args = argparse.Namespace(
        evidence=str(ev), work_id="W-test", pathway="quality", gate="quality-gate",
        kind="verify", result="pass", stale_after_days=14, verified_by="",
        recommendation_id="", verify_cmd="bash -c 'echo ok'", reviewer="",
        proof_type="executed", canary_target=None, project=None,
    )
    proof, warn = mod.build_proof_record(
        args, work_item={"project": "no-such-project-xyz"}, run_id="R-test",
        measurement_id_value="M-test", projects_root=str(projects),
    )
    check(
        proof is not None and proof.get("verify_error") == "cwd_invalid",
        "unresolvable work-item project records cwd_invalid on the proof",
    )
    check(
        warn is not None and warn.get("id") == "proof-logged-unverified"
        and warn.get("severity") == "warn",
        "non-crediting proof returns the loud proof-logged-unverified finding",
    )
    check(
        warn is not None and "cwd" in warn.get("message", ""),
        "the finding names the cwd_invalid reason",
    )

    recorded_checkout = projects / "owner-a" / "same-name"
    supplied_checkout = projects / "owner-b" / "same-name"
    recorded_checkout.mkdir(parents=True)
    supplied_checkout.mkdir(parents=True)
    mismatch_args = argparse.Namespace(
        evidence=str(ev), work_id="W-cross-checkout", pathway="quality", gate="quality-gate",
        kind="verify", result="pass", stale_after_days=14, verified_by="",
        recommendation_id="", verify_cmd="bash -c 'echo verifier-output-is-not-empty'",
        reviewer="", proof_type="executed", canary_target=None,
        project=str(supplied_checkout),
    )
    mismatch_proof, mismatch_warn = mod.build_proof_record(
        mismatch_args,
        work_item={"project": str(recorded_checkout), "project_name": "same-name"},
        run_id="R-cross-checkout", measurement_id_value="M-cross-checkout",
        projects_root=str(projects),
    )
    check(
        mismatch_proof.get("verify_error") == "project_context_mismatch"
        and mismatch_proof.get("exit_code") is None
        and mismatch_proof.get("project_path") == str(recorded_checkout.resolve()),
        "verification never runs in a different same-named checkout than the work item records",
    )
    check(
        mismatch_warn is not None and "different checkout" in mismatch_warn.get("message", ""),
        "cross-checkout proof attempts return a loud unverified finding",
    )


def test_artifact_filename_dates_use_local_day_not_utc():
    """An artifact filename must carry the operator's calendar day, never UTC's.

    2026-08-10. report_path() and dated_artifact_path() both stamped the filename
    from utc_now(). Every run after 7pm CDT was therefore dated TOMORROW, and a
    document dated tomorrow can never read as stale to doc_freshness.py or to
    operator-artifacts-supersede.py, which both key on that filename date. 175
    artifacts were misdated between 2026-05-22 and 2026-08-11 before it was caught.

    The fixture forces two extreme zones 25 hours apart, so at any instant at least
    one of them disagrees with UTC about what day it is. The final check asserts the
    split actually happened, so this test can never pass vacuously.
    """
    import datetime as _dt
    import importlib.util
    import types

    spec = importlib.util.spec_from_file_location("opl_clock_under_test", CLI)
    opl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(opl)
    paths = types.SimpleNamespace(operator_artifacts=Path("/tmp/oa-clock-test"))

    def under_tz(tz, fn):
        previous = os.environ.get("TZ")
        os.environ["TZ"] = tz
        time.tzset()
        try:
            return fn()
        finally:
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            time.tzset()

    utc_day = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    observed_local_days = []

    for tz in ("Pacific/Kiritimati", "Pacific/Midway"):  # UTC+14 and UTC-11
        local_day = under_tz(tz, lambda: _dt.datetime.now().strftime("%Y-%m-%d"))
        observed_local_days.append(local_day)

        dated = under_tz(tz, lambda: opl.dated_artifact_path(paths, "proof-registry").name)
        check(
            dated == f"{local_day}-proof-registry.md",
            f"dated_artifact_path uses the local day in {tz} (got {dated}, local {local_day})",
        )

        report = under_tz(tz, lambda: opl.report_path(paths).name)
        check(
            report == f"{local_day}-operating-layer-report.md",
            f"report_path uses the local day in {tz} (got {report}, local {local_day})",
        )

        check(
            under_tz(tz, opl.local_day) == local_day,
            f"local_day() tracks the machine timezone in {tz}",
        )

    check(
        any(day != utc_day for day in observed_local_days),
        f"the fixture actually exercised a local/UTC date split (UTC {utc_day}, saw {observed_local_days})",
    )

    # Guard the other direction: instants inside artifacts must STAY UTC.
    check(
        opl.iso_now().endswith("Z") and opl.iso_now()[:10] == utc_day,
        "iso_now() still reports UTC, because a timestamp is an instant not a day",
    )


def test_approval_issue_guard_blocks_agent_shell_issuance():
    """The PreToolUse guard blocks executable approval authority mutations."""
    waiver = "--kind production-secure-waiver --work-id W-test --pathway release"
    release = "--kind release-production-approval --work-id W-test --release-receipt r.json"
    invalidation = "--ticket-id AT-000000000000 --reason compromised-ticket"
    deeply_nested = f"operating-layer.py approval-issue {waiver}"
    for _ in range(5):
        deeply_nested = f"bash -c {shlex.quote(deeply_nested)}"
    blocked = [
        ("PATH executable", f"operating-layer.py approval-issue {waiver}"),
        ("absolute executable", f"{CLI} approval-issue {waiver}"),
        ("live Claude symlink", f"~/.claude/scripts/operating-layer.py approval-issue {waiver}"),
        ("relative script", f"./scripts/operating-layer.py approval-issue {waiver}"),
        ("python script", f"python3 scripts/operating-layer.py approval-issue {waiver}"),
        ("python flag", f"python3 -B scripts/operating-layer.py approval-issue {waiver}"),
        ("python value flag", "python3 --check-hash-based-pycs always "
         f"scripts/operating-layer.py approval-issue {waiver}"),
        ("leading assignment", f"TEST_ONLY=1 operating-layer.py approval-issue {waiver}"),
        ("env wrapper", f"env TEST_ONLY=1 python3 scripts/operating-layer.py approval-issue {waiver}"),
        ("env split string", f"env -S 'python3 scripts/operating-layer.py approval-issue {waiver}'"),
        ("env split argv", f"env -S python3 scripts/operating-layer.py approval-issue {waiver}"),
        ("env split equals", f"env --split-string=python3 scripts/operating-layer.py approval-issue {waiver}"),
        ("command env split", f"command env -S 'python3 scripts/operating-layer.py approval-issue {waiver}'"),
        ("exec env split", f"exec env -S 'python3 scripts/operating-layer.py approval-issue {waiver}'"),
        ("time env split", f"time env -S 'python3 scripts/operating-layer.py approval-issue {waiver}'"),
        ("builtin command env split", f"builtin command env -S 'python3 scripts/operating-layer.py approval-issue {waiver}'"),
        ("env split option", f"env -S '-i python3' scripts/operating-layer.py approval-issue {waiver}"),
        ("env split separator", f"env -S -- python3 scripts/operating-layer.py approval-issue {waiver}"),
        ("env split equals option", f"env --split-string='-i python3' scripts/operating-layer.py approval-issue {waiver}"),
        ("env search path", f"env -P /usr/bin python3 scripts/operating-layer.py approval-issue {waiver}"),
        ("nested env search path", f"command env -P /usr/bin python3 scripts/operating-layer.py approval-issue {waiver}"),
        ("command wrapper", f"command python3 scripts/operating-layer.py approval-issue {waiver}"),
        ("exec wrapper", f"exec operating-layer.py approval-issue {waiver}"),
        ("time wrapper", f"time -p operating-layer.py approval-issue {waiver}"),
        ("nohup wrapper", f"nohup operating-layer.py approval-issue {waiver}"),
        ("nice wrapper", f"nice -n 5 operating-layer.py approval-issue {waiver}"),
        ("leading redirection", f"> /tmp/approval-guard-test.log operating-layer.py approval-issue {waiver}"),
        ("global options", f"operating-layer.py --json --claude-home /tmp/x approval-issue {waiver}"),
        ("abbreviated global option", f"operating-layer.py --claude-ho /tmp/x approval-issue {waiver}"),
        ("shorter global option", f"operating-layer.py --claude /tmp/x approval-issue {waiver}"),
        ("output global option", f"operating-layer.py --out /tmp/x approval-issue {waiver}"),
        ("bash c", f"bash -c 'operating-layer.py approval-issue {waiver}'"),
        ("nested exec", f"bash -c 'exec operating-layer.py approval-issue {waiver}'"),
        ("nested nice", f"bash -c 'nice operating-layer.py approval-issue {waiver}'"),
        ("bash lc", f"/bin/bash -lc 'python3 scripts/operating-layer.py approval-issue {waiver}'"),
        ("bash norc", f"bash --norc -c 'operating-layer.py approval-issue {waiver}'"),
        ("bash rcfile", f"bash --rcfile /tmp/empty -c 'operating-layer.py approval-issue {waiver}'"),
        ("sh c", f"sh -c 'operating-layer.py approval-issue {waiver}'"),
        ("zsh lc", f"zsh -lc 'operating-layer.py approval-issue {waiver}'"),
        ("five nested shells", deeply_nested),
        ("semicolon chain", f"true; operating-layer.py approval-issue {waiver}"),
        ("newline chain", f"true\noperating-layer.py approval-issue {waiver}"),
        ("and chain", f"true && operating-layer.py approval-issue {waiver}"),
        ("or chain", f"false || operating-layer.py approval-issue {waiver}"),
        ("subshell", f"(operating-layer.py approval-issue {waiver})"),
        ("brace group", f"{{ operating-layer.py approval-issue {waiver}; }}"),
        ("negated command", f"! operating-layer.py approval-issue {waiver}"),
        ("if condition", f"if operating-layer.py approval-issue {waiver}; then true; fi"),
        ("nested brace group", f"bash -c '{{ operating-layer.py approval-issue {waiver}; }}'"),
        ("quoted executable", f"operating'-'layer.py approval-issue {waiver}"),
        ("inner quoted executable", f"operat''ing-layer.py approval-issue {waiver}"),
        ("inner quoted executable suffix", f"operating-la''yer.py approval-issue {waiver}"),
        ("case-folded script", f"python3 scripts/OPERATING-LAYER.PY approval-issue {waiver}"),
        ("quoted join", f"operating-layer.py approval'-'issue {waiver}"),
        ("inner quoted subcommand", f"operating-layer.py approv''al-issue {waiver}"),
        ("inner quoted subcommand suffix", f"operating-layer.py approval-is''sue {waiver}"),
        ("continued executable", f"operating-\\\nlayer.py approval-issue {waiver}"),
        ("continued subcommand", f"operating-layer.py approval-\\\nissue {waiver}"),
        ("ANSI-C quoted join", f"operating-layer.py approval$'-'issue {waiver}"),
        ("ANSI-C quoted subcommand", f"operating-layer.py $'approval-issue' {waiver}"),
        ("ANSI-C quoted executable", f"$'operating-layer.py' approval-issue {waiver}"),
        ("locale quoted subcommand", f"operating-layer.py $\"approval-issue\" {waiver}"),
        ("approval issue help", "operating-layer.py approval-issue --help"),
        ("release ticket", f"operating-layer.py approval-issue {release}"),
        ("approval invalidation", f"operating-layer.py approval-invalidate {invalidation}"),
        ("legacy inline override", "APPROVAL_ISSUE_CHAT_OVERRIDE=1 "
         f"operating-layer.py approval-issue {waiver}"),
        ("legacy inline invalidation override", "APPROVAL_ISSUE_CHAT_OVERRIDE=1 "
         f"operating-layer.py approval-invalidate {invalidation}"),
        ("nested legacy override", "bash -c 'APPROVAL_ISSUE_CHAT_OVERRIDE=1 "
         f"operating-layer.py approval-invalidate {invalidation}'"),
    ]
    for label, command in blocked:
        proc = run_approval_guard({"tool_name": "Bash", "tool_input": {"command": command}})
        check(proc.returncode == 2, f"approval guard blocks {label} with exit 2")
        check(proc.stdout == "", f"approval guard writes no stdout for {label}")
        check(proc.stderr == APPROVAL_GUARD_DENIAL,
              f"approval guard gives the exact manual Terminal message for {label}")

    cmd_proc = run_approval_guard({
        "tool_name": "Bash",
        "tool_input": {"cmd": f"operating-layer.py approval-issue {waiver}"},
    })
    check(cmd_proc.returncode == 2, "approval guard supports the Codex cmd payload")
    check(cmd_proc.stdout == "", "approval guard writes no stdout for a cmd payload")
    check(cmd_proc.stderr == APPROVAL_GUARD_DENIAL,
          "approval guard gives the exact denial for a cmd payload")

    mixed_proc = run_approval_guard({
        "tool_name": "Bash",
        "tool_input": {
            "command": "true",
            "cmd": f"operating-layer.py approval-issue {waiver}",
        },
    })
    check(mixed_proc.returncode == 2, "approval guard checks both command fields")
    check(mixed_proc.stdout == "", "approval guard writes no stdout for mixed fields")
    check(mixed_proc.stderr == APPROVAL_GUARD_DENIAL,
          "approval guard gives the exact denial for mixed fields")

    malformed = run_approval_guard({
        "tool_name": "Bash",
        "tool_input": {
            "command": "python3 scripts/operating-layer.py approval-issue --reason 'unterminated",
        },
    })
    check(malformed.returncode == 2, "approval guard blocks runner-first malformed shell text")
    check(malformed.stdout == "", "approval guard malformed fallback writes no stdout")
    check(malformed.stderr == APPROVAL_GUARD_DENIAL,
          "approval guard malformed fallback gives the exact denial")

    for variable in (
        "APPROVAL_ISSUE_CHAT_OVERRIDE", "CLAUDE_HOOK_FORCE", "EXTERNAL_SEND_APPROVED",
    ):
        proc = run_approval_guard(
            {"tool_name": "Bash", "tool_input": {"command": blocked[0][1]}},
            env={variable: "1"},
        )
        check(proc.returncode == 2, f"approval guard has no {variable} override")
        check(proc.stderr == APPROVAL_GUARD_DENIAL,
              f"approval guard keeps the exact denial with {variable}")


def test_approval_issue_guard_allows_non_issuance_text_and_fail_open_inputs():
    """Search, help, tests, reads, prose, and malformed hook data stay usable."""
    allowed_commands = [
        ("other subcommand", "operating-layer.py work-status --work-id approval-issue"),
        ("top-level help", "operating-layer.py --help"),
        ("test runner", "python3 scripts/tests/operating_layer_test.py"),
        ("ripgrep", "rg 'approval-issue' hooks scripts"),
        ("git grep", "git grep approval-issue"),
        ("printf prose", "printf '%s\\n' 'operating-layer.py approval-issue --help'"),
        ("documentation read", "sed -n '/approval-issue/p' docs/pathway-proof-integrity.md"),
        ("commit text", "git commit -m 'Document approval-issue guard'"),
        ("approval ledger read", "wc -l ~/.claude/operator-intelligence/approvals.ndjson"),
        ("malformed search", "rg 'approval-issue"),
        ("python short help", "python3 -h scripts/operating-layer.py approval-issue --help"),
        ("python long help", "python3 --help scripts/operating-layer.py approval-issue --help"),
        ("python short version", "python3 -V scripts/operating-layer.py approval-issue --help"),
        ("python long version", "python3 --version scripts/operating-layer.py approval-issue --help"),
        ("python environment help", "python3 --help-env scripts/operating-layer.py approval-issue --help"),
        ("python xoptions help", "python3 --help-xoptions scripts/operating-layer.py approval-issue --help"),
        ("python all help", "python3 --help-all scripts/operating-layer.py approval-issue --help"),
        ("bash help", "bash --help -c 'operating-layer.py approval-issue --help'"),
        ("sh help", "sh --help -c 'operating-layer.py approval-issue --help'"),
        ("zsh version", "zsh --version -c 'operating-layer.py approval-issue --help'"),
        ("bash shopt filename", "bash -Ocmdhist 'operating-layer.py approval-issue --help'"),
        ("safe option value", "operating-layer.py --goal approval-issue pathway-next --help"),
        ("plain here-doc", "cat <<EOF\noperating-layer.py approval-issue --help\nEOF"),
        ("quoted here-doc", "cat <<'DOC'\noperating-layer.py approval-issue --help\nDOC"),
    ]
    for label, command in allowed_commands:
        proc = run_approval_guard({"tool_name": "Bash", "tool_input": {"command": command}})
        check(proc.returncode == 0, f"approval guard allows {label}")
        check(proc.stdout == "" and proc.stderr == "",
              f"approval guard is silent for {label}")

    allowed_payloads = [
        ("empty payload", {}),
        ("missing tool input", {"tool_name": "Bash"}),
        ("missing command", {"tool_name": "Bash", "tool_input": {}}),
        ("non-string command", {"tool_name": "Bash", "tool_input": {"command": ["approval-issue"]}}),
        ("unrelated tool", {
            "tool_name": "Read",
            "tool_input": {"command": "operating-layer.py approval-issue --help"},
        }),
    ]
    for label, payload in allowed_payloads:
        proc = run_approval_guard(payload)
        check(proc.returncode == 0, f"approval guard allows {label}")
        check(proc.stdout == "" and proc.stderr == "",
              f"approval guard is silent for {label}")

    invalid = run_approval_guard("{not-json", raw=True)
    check(invalid.returncode == 0, "approval guard fails open on invalid JSON")
    check(invalid.stdout == "" and invalid.stderr == "",
          "approval guard is silent on invalid JSON")


def test_approval_issue_guard_installer_uses_one_canonical_source():
    """The installer links both agent homes to the repo-owned guard."""
    reset()
    claude_home = ROOT / "installer-claude"
    codex_home = ROOT / "installer-codex"
    env = os.environ.copy()
    env.update({
        "CLAUDE_HOME": str(claude_home),
        "PATHWAY_CODEX_HOME": str(codex_home),
    })
    proc = subprocess.run(
        ["bash", str(INSTALLER)], capture_output=True, text=True, timeout=30, env=env,
    )
    check(proc.returncode == 0, f"guard installer succeeds in temp homes ({proc.stderr.strip()})")
    for agent, link in (
        ("Claude", claude_home / "hooks" / "approval-issue-guard.py"),
        ("Codex", codex_home / "hooks" / "approval-issue-guard.py"),
    ):
        check(link.is_symlink(), f"guard installer creates the {agent} symlink")
        check(link.resolve() == APPROVAL_GUARD.resolve(),
              f"guard installer points {agent} at the canonical repo source")


def test_approval_issue_guard_repeatable_verifier():
    """The verifier proves live wiring without touching a real approval command."""
    reset()
    claude_home = ROOT / "verify-claude"
    codex_home = ROOT / "verify-codex"
    isolated_settings = ROOT / "verify-isolated" / "settings.json"
    ledger = ROOT / "fake-approvals.ndjson"
    ledger_bytes = b'{"event":"issued","ticket_id":"AC-test-only"}\n'
    ledger.write_bytes(ledger_bytes)

    install_env = os.environ.copy()
    install_env.update({
        "CLAUDE_HOME": str(claude_home),
        "PATHWAY_CODEX_HOME": str(codex_home),
    })
    installed = subprocess.run(
        ["bash", str(INSTALLER)], capture_output=True, text=True, timeout=30, env=install_env,
    )
    check(installed.returncode == 0,
          f"verifier fixture installs guard links ({installed.stderr.strip()})")

    claude_hook = claude_home / "hooks" / "approval-issue-guard.py"
    codex_hook = codex_home / "hooks" / "approval-issue-guard.py"
    claude_settings = claude_home / "settings.json"
    codex_settings = codex_home / "hooks.json"

    def settings_payload(command, after=False, duplicate=False):
        guard = {"type": "command", "command": command, "timeout": 5}
        handlers = [{"type": "command", "command": "python3 /tmp/earlier-hook.py"}, guard]
        if duplicate:
            handlers.insert(1, dict(guard))
        if after:
            handlers.append({"type": "command", "command": "python3 /tmp/later-hook.py"})
        return {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Read", "hooks": []},
                    {"matcher": "Bash", "hooks": handlers},
                ],
            },
        }

    def save_settings(path, command, **changes):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(settings_payload(command, **changes), indent=2) + "\n",
            encoding="utf-8",
        )

    claude_command = f"python3 {claude_hook}"
    codex_command = f"python3 {codex_hook}"
    save_settings(claude_settings, claude_command)
    save_settings(codex_settings, codex_command)
    save_settings(isolated_settings, claude_command)
    settings_before = {
        path: path.read_bytes()
        for path in (claude_settings, codex_settings, isolated_settings)
    }

    verifier_cmd = [
        sys.executable,
        str(APPROVAL_GUARD_VERIFIER),
        "--repo-hook", str(APPROVAL_GUARD),
        "--claude-hook", str(claude_hook),
        "--codex-hook", str(codex_hook),
        "--claude-settings", str(claude_settings),
        "--codex-settings", str(codex_settings),
        "--isolated-settings", str(isolated_settings),
        "--ledger", str(ledger),
        "--runs", "4",
    ]

    def verify(runs="4"):
        command = list(verifier_cmd)
        command[command.index("--runs") + 1] = runs
        return subprocess.run(
            command, capture_output=True, text=True, timeout=30,
        )

    def verify_source(source, runs="1"):
        command = list(verifier_cmd)
        command[command.index("--repo-hook") + 1] = str(source)
        command[command.index("--runs") + 1] = runs
        return subprocess.run(
            command, capture_output=True, text=True, timeout=30,
        )

    def point_installed_links(source):
        for link in (claude_hook, codex_hook):
            link.unlink()
            link.symlink_to(source)

    def verifier_json(proc):
        try:
            return json.loads(proc.stdout)
        except (TypeError, ValueError):
            return {}

    # With four samples nearest-rank p95 is the maximum, so one scheduler
    # outlier can masquerade as a guard regression. Match the production
    # verifier's 120-run sample while preserving its strict 50ms threshold.
    passed = verify(runs="120")
    summary = verifier_json(passed)
    check(passed.returncode == 0,
          f"repeatable approval guard verifier passes its complete fixture ({passed.stderr.strip()})")
    check(summary.get("status") == "pass", "approval guard verifier returns a JSON pass status")
    check(summary.get("run_count") == 120, "approval guard verifier honors its run-count override")
    check(summary.get("settings_checked") == 3,
          "approval guard verifier reports all three settings files")
    check(summary.get("symlinks_checked") == 2,
          "approval guard verifier reports both installed links")
    check(summary.get("blocked_fixtures") == 21 and summary.get("allowed_fixtures") == 12,
          "approval guard verifier runs fixtures through source and both installed links")
    check(isinstance(summary.get("p95_ms"), (int, float)) and summary.get("p95_ms") < 50,
          "approval guard verifier reports p95 below 50ms")
    check(summary.get("ledger_unchanged") is True and ledger.read_bytes() == ledger_bytes,
          "approval guard verifier leaves fake ledger bytes unchanged")
    check(summary.get("ledger_sha256") == hashlib.sha256(ledger_bytes).hexdigest(),
          "approval guard verifier reports the fake ledger SHA-256")
    check(summary.get("ledger_line_count") == 1,
          "approval guard verifier reports the fake ledger line count")
    check(all(path.read_bytes() == before for path, before in settings_before.items()),
          "approval guard verifier leaves all settings bytes unchanged")

    save_settings(codex_settings, codex_command, after=True)
    not_last = verify()
    check(not_last.returncode != 0 and "last" in not_last.stdout.lower(),
          "approval guard verifier rejects a guard that is not last")
    save_settings(codex_settings, codex_command)

    save_settings(isolated_settings, claude_command, duplicate=True)
    duplicate = verify()
    check(duplicate.returncode != 0 and "exactly one" in duplicate.stdout.lower(),
          "approval guard verifier rejects duplicate guard entries")
    save_settings(isolated_settings, claude_command)

    claude_settings.write_text("{bad-json", encoding="utf-8")
    invalid = verify()
    check(invalid.returncode != 0 and "valid json" in invalid.stdout.lower(),
          "approval guard verifier rejects invalid settings JSON")
    save_settings(claude_settings, claude_command)

    slow_hook = ROOT / "slow-approval-guard.py"
    slow_hook.write_text(
        "import subprocess, sys, time\n"
        "time.sleep(0.06)\n"
        f"proc = subprocess.run([sys.executable, {str(APPROVAL_GUARD)!r}], "
        "input=sys.stdin.read(), capture_output=True, text=True)\n"
        "sys.stdout.write(proc.stdout)\n"
        "sys.stderr.write(proc.stderr)\n"
        "raise SystemExit(proc.returncode)\n",
        encoding="utf-8",
    )
    point_installed_links(slow_hook)
    slow = verify_source(slow_hook)
    check(slow.returncode != 0 and "p95" in slow.stdout.lower(),
          "approval guard verifier rejects a hook at or above the p95 limit")

    mutating_hook = ROOT / "mutating-approval-guard.py"
    mutating_hook.write_text(
        "import subprocess, sys\n"
        "from pathlib import Path\n"
        f"with Path({str(ledger)!r}).open('ab') as handle:\n"
        "    handle.write(b'test-only-change\\n')\n"
        f"proc = subprocess.run([sys.executable, {str(APPROVAL_GUARD)!r}], "
        "input=sys.stdin.read(), capture_output=True, text=True)\n"
        "sys.stdout.write(proc.stdout)\n"
        "sys.stderr.write(proc.stderr)\n"
        "raise SystemExit(proc.returncode)\n",
        encoding="utf-8",
    )
    point_installed_links(mutating_hook)
    changed_ledger = verify_source(mutating_hook)
    check(changed_ledger.returncode != 0
          and "ledger bytes changed" in changed_ledger.stdout.lower(),
          "approval guard verifier rejects any ledger mutation")

    ledger.write_bytes(ledger_bytes)
    point_installed_links(APPROVAL_GUARD)

    codex_hook.unlink()
    codex_hook.symlink_to(CLI)
    wrong_link = verify()
    check(wrong_link.returncode != 0 and "tracked source" in wrong_link.stdout.lower(),
          "approval guard verifier rejects a link to the wrong source")
    check(ledger.read_bytes() == ledger_bytes,
          "approval guard verifier failure paths leave fake ledger bytes unchanged")


def test_approval_ledger_strict_reader_and_authority_refusal_exit_codes():
    """Authority input is all-or-nothing and repo CLI mutation refusals fail at the shell."""
    opl = load_cli("approval_strict_ledger")
    reset()
    proj = ROOT / "projects" / "strict-approval-proj"
    proj.mkdir(parents=True, exist_ok=True)
    started, _ = run("work-start", [
        "--project", str(proj), "--goal", "strict approval ledger fixture",
        "--tier", "production-secure",
    ])
    wid = started["work_id"]
    reason = "strict authority fixture"
    issued, issued_proc = run("approval-issue", [
        "--kind", "production-secure-waiver", "--work-id", wid,
        "--pathway", "observability", "--reason", reason,
    ])
    check(issued_proc.returncode == 0 and bool(issued.get("records")),
          "an isolated valid approval issue exits zero")
    covered, _ = run("work-cover", [
        "--work-id", wid, "--pathway", "observability", "--na", "--reason", reason,
    ])
    waiver_entry = next(
        entry for entry in covered["records"][0]["itinerary"]
        if entry.get("pathway") == "observability"
    )
    ledger = ROOT / "out/operator-intelligence/approvals.ndjson"
    valid_bytes = ledger.read_bytes()
    valid_events = opl._strict_approval_events(ledger)
    check(opl.approval_events_valid(valid_events),
          "the strict reader accepts a complete ordered approval ledger")

    # Root authority pre-consumes at issue time. The first engine attachment must still occur
    # inside the exact 15-minute review window for both waiver and release consumers.
    waiver_digest = issued["records"][0]["subject_digest"]
    waiver_issue_event = next(
        event for event in valid_events
        if event.get("event") == "issued" and event.get("subject_digest") == waiver_digest
    )
    waiver_expiry = opl.parse_ts(waiver_issue_event["expires_at"])
    waiver_consumer = f"work-cover:{wid}:observability"
    timely_waiver, timely_refusal = opl.prebound_approval_for_consumer(
        valid_events, waiver_digest, waiver_consumer,
        now=waiver_expiry - opl.timedelta(seconds=1),
    )
    stale_waiver, stale_refusal = opl.prebound_approval_for_consumer(
        valid_events, waiver_digest, waiver_consumer,
        now=waiver_expiry + opl.timedelta(seconds=1),
    )
    check(timely_waiver is not None and not timely_refusal,
          "a root-preconsumed waiver is attachable inside its review window")
    check(stale_waiver is None and stale_refusal == "expired",
          "a root-preconsumed waiver cannot be attached after its review window")

    release_receipt = write(
        "out/operator-artifacts/strict-root-preconsumed-release.json",
        json.dumps({"strict_fixture": True}) + "\n",
    )
    release_issue, _ = run("approval-issue", [
        "--kind", "release-production-approval", "--work-id", wid,
        "--release-receipt", str(release_receipt),
        "--reason", "strict preconsumed release fixture",
    ])
    release_subject = opl.release_approval_subject(
        wid, proj.name, opl.sha256_file(release_receipt)
    )
    release_consumer = "P-strict-root-preconsumed-release"
    release_consumption, release_refusal = opl.consume_approval(
        type("Paths", (), {"approvals_path": ledger})(),
        release_subject,
        release_consumer,
    )
    check(release_consumption is not None and not release_refusal,
          "the isolated fixture creates an exact preconsumed release binding")
    valid_bytes = ledger.read_bytes()
    valid_events = opl._strict_approval_events(ledger)
    release_digest = release_issue["records"][0]["subject_digest"]
    release_issue_event = next(
        event for event in valid_events
        if event.get("event") == "issued" and event.get("subject_digest") == release_digest
    )
    release_expiry = opl.parse_ts(release_issue_event["expires_at"])
    stale_release, stale_release_refusal = opl.prebound_approval_for_consumer(
        valid_events, release_digest, release_consumer,
        now=release_expiry + opl.timedelta(seconds=1),
    )
    check(stale_release is None and stale_release_refusal == "expired",
          "a root-preconsumed release cannot be attached after its review window")

    original_store_classifier = opl.approval_store_is_protected
    original_event_loader = opl.approval_events_for
    try:
        opl.approval_store_is_protected = lambda _paths: True
        opl.approval_events_for = lambda _paths: valid_events
        protected_stale_waiver, protected_waiver_refusal = opl.consume_approval(
            type("Paths", (), {"approvals_path": ledger})(),
            waiver_issue_event["subject"],
            waiver_consumer,
            now=waiver_expiry + opl.timedelta(seconds=1),
        )
        protected_stale_release, protected_release_refusal = opl.consume_approval(
            type("Paths", (), {"approvals_path": ledger})(),
            release_subject,
            release_consumer,
            now=release_expiry + opl.timedelta(seconds=1),
        )
    finally:
        opl.approval_store_is_protected = original_store_classifier
        opl.approval_events_for = original_event_loader
    check(protected_stale_waiver is None and protected_waiver_refusal == "expired",
          "protected consume rejects a stale root-preconsumed waiver")
    check(protected_stale_release is None and protected_release_refusal == "expired",
          "protected consume rejects a stale root-preconsumed release")

    lines = valid_bytes.splitlines(keepends=True)
    malformed_cases = {
        "malformed middle": lines[0] + b"{not-json}\n" + b"".join(lines[1:]),
        "truncated tail": valid_bytes[:-1],
        "reordered consumption": b"".join([lines[1], lines[0], *lines[2:]]),
        "unknown event": valid_bytes.replace(b'"event": "consumed"', b'"event": "forged"', 1),
    }
    for label, payload in malformed_cases.items():
        ledger.write_bytes(payload)
        events = opl._strict_approval_events(ledger)
        check(not opl.approval_events_valid(events) and len(events) == 0,
              f"the strict reader rejects the whole ledger for {label}")
        check(not opl.waiver_corroborated(waiver_entry, covered["records"][0], events),
              f"{label} cannot retain waiver credit")

    ledger.write_bytes(valid_bytes)
    symlink = ROOT / "out/operator-intelligence/symlinked-approvals.ndjson"
    symlink.symlink_to(ledger)
    check(not opl.approval_events_valid(opl._strict_approval_events(symlink)),
          "a symlinked approval ledger is rejected")
    original_cap = opl.NDJSON_READ_MAX_BYTES
    try:
        opl.NDJSON_READ_MAX_BYTES = len(valid_bytes) - 1
        check(not opl.approval_events_valid(opl._strict_approval_events(ledger)),
              "an over-cap approval ledger is rejected instead of truncated")
        check(not opl._approval_write_fits(valid_events),
              "the projected-size guard refuses the write that would cross the read cap")
    finally:
        opl.NDJSON_READ_MAX_BYTES = original_cap

    bad_ticket, bad_ticket_proc = run("approval-invalidate", [
        "--ticket-id", "not-a-ticket", "--reason", "invalid id fixture",
    ])
    check(bad_ticket_proc.returncode == 2
          and "approval-invalidate-invalid-ticket-id" in ids(bad_ticket),
          "an invalidation validation refusal exits nonzero")
    missing_reason, missing_reason_proc = run("approval-issue", [
        "--kind", "production-secure-waiver", "--work-id", wid,
        "--pathway", "docs",
    ])
    check(missing_reason_proc.returncode == 2
          and "approval-issue-missing-reason" in ids(missing_reason),
          "an issue validation refusal exits nonzero")

    # A live-shaped lexical output path remains protected even when it symlinks to the suite's
    # valid user ledger. The repo CLI renders the sudo helper command and changes no bytes.
    live_link = ROOT / "live-output-link"
    live_link.symlink_to(ROOT / "out", target_is_directory=True)
    before = ledger.read_bytes()
    protected, protected_proc = run("approval-invalidate", [
        "--output-root", str(live_link),
        "--ticket-id", issued["records"][0]["ticket_id"],
        "--reason", "protected path fixture",
    ])
    check(protected_proc.returncode == 2
          and "approval-invalidate-human-helper-required" in ids(protected)
          and str(protected.get("authority_command", "")).startswith(
              "/usr/bin/sudo -k; /usr/bin/sudo -- "
          ),
          "a symlinked live-shaped store still requires the root-owned helper")
    check(ledger.read_bytes() == before,
          "a protected helper-required refusal leaves the user ledger byte-identical")

    protected_release, protected_release_proc = run("approval-issue", [
        "--output-root", str(live_link),
        "--kind", "release-production-approval", "--work-id", wid,
        "--release-receipt", str(release_receipt),
        "--reason", "reviewed strict root command fixture",
    ])
    authority_command = str(protected_release.get("authority_command", ""))
    authority_prefix = (
        "/usr/bin/sudo -k; /usr/bin/sudo -- "
        "/usr/local/libexec/pathway-approval "
    )
    helper_argv = shlex.split(authority_command[len(authority_prefix):])
    subject_json = helper_argv[helper_argv.index("--subject-json") + 1]
    rendered_subject = json.loads(subject_json)
    import importlib.machinery
    import importlib.util
    helper_loader = importlib.machinery.SourceFileLoader(
        "pathway_approval_command_parser", str(APPROVAL_HELPER_SOURCE)
    )
    helper_spec = importlib.util.spec_from_loader(helper_loader.name, helper_loader)
    helper_module = importlib.util.module_from_spec(helper_spec)
    helper_loader.exec_module(helper_module)
    parsed_helper_args = helper_module._build_parser().parse_args(helper_argv)
    check(protected_release_proc.returncode == 2
          and authority_command.startswith(authority_prefix)
          and rendered_subject.get("release_receipt_sha256")
          == opl.sha256_file(release_receipt)
          and "[REDACTED]" not in authority_command,
          "the protected release command preserves the exact reviewed receipt digest")
    check(parsed_helper_args.command == "issue"
          and parsed_helper_args.subject_json == subject_json,
          "the installed helper parser accepts the emitted shlex argument vector")

    project_fragment = '"project":' + json.dumps(rendered_subject["project"])
    duplicate_subject_json = subject_json.replace(
        project_fragment,
        '"project":"sk-proj-' + ("A" * 32) + '",' + project_fragment,
        1,
    )
    check(duplicate_subject_json != subject_json,
          "duplicate authority subject regression plants the adversarial key")
    duplicate_argv = list(helper_argv)
    duplicate_argv[duplicate_argv.index("--subject-json") + 1] = duplicate_subject_json
    duplicate_command = authority_prefix + shlex.join(duplicate_argv)
    duplicate_redacted = opl.redact_obj({"authority_command": duplicate_command})
    check(not opl._is_safe_authority_command(duplicate_command)
          and duplicate_redacted.get("authority_command") != duplicate_command
          and "[REDACTED]" in duplicate_redacted.get("authority_command", ""),
          "duplicate authority subject keys cannot bypass command redaction")

    spoofed_reason, spoofed_reason_proc = run("approval-issue", [
        "--output-root", str(live_link),
        "--kind", "release-production-approval", "--work-id", wid,
        "--release-receipt", str(release_receipt),
        "--reason", "reviewed \u202e visually reversed",
    ])
    check(spoofed_reason_proc.returncode == 2
          and "approval-issue-reason-not-storable" in ids(spoofed_reason)
          and not spoofed_reason.get("authority_command"),
          "Unicode bidi controls are refused before an authority command is displayed")


def test_approval_authority_single_use_waiver_and_release_credit():
    """The verifiable single-use waiver/approval authority (SPEC 2026-08-16): content-bound
    tickets, 15-minute expiry, single-use durable consumption, fail-closed refusals, and
    status-time ledger corroboration for both waived N/A rows and release production credit."""
    opl = load_cli("approval_authority")
    reset()
    proj = ROOT / "projects" / "approval-proj"
    proj.mkdir(parents=True, exist_ok=True)
    ev = ROOT / "approval-evidence.txt"
    ev.write_text("artifact", encoding="utf-8")
    approvals_path = ROOT / "out/operator-intelligence/approvals.ndjson"
    work_items_path = ROOT / "out/operator-intelligence/work-items.ndjson"

    # Criterion 1: canonical digest — key order never changes it, any field edit does.
    subject = {"kind": "production-secure-waiver", "work_id": "W-x", "project": "p",
               "pathway": "release", "reason": "r"}
    reordered = {"reason": "r", "pathway": "release", "project": "p", "work_id": "W-x",
                 "kind": "production-secure-waiver"}
    check(opl.approval_subject_digest(subject) == opl.approval_subject_digest(reordered),
          "approval digest is stable under subject key reordering")
    check(opl.approval_subject_digest({**subject, "reason": "r2"})
          != opl.approval_subject_digest(subject),
          "editing any bound field changes the approval digest")

    data, _ = run("work-start", ["--project", str(proj),
                                 "--goal", "production secure approval authority regression",
                                 "--tier", "production-secure"])
    wid = data["work_id"]

    # Criterion 3: production-secure N/A without a ticket stays fail-closed.
    blocked, _ = run("work-cover", ["--work-id", wid, "--pathway", "observability", "--na",
                                    "--reason", "watcher and health endpoint are live"])
    check("work-cover-production-secure-na-blocked" in ids(blocked),
          "production-secure N/A without a waiver ticket is refused")

    # Criterion 2: approval-issue writes an issued event with a 900-second validity window.
    issued, _ = run("approval-issue", ["--kind", "production-secure-waiver", "--work-id", wid,
                                       "--pathway", "observability",
                                       "--reason", "watcher and health endpoint are live"])
    check(bool(issued.get("subject_digest")) and issued.get("expires_in_seconds") == 900
          and issued.get("single_use") is True,
          "approval-issue returns a digest with a 900-second single-use window")
    ledger = [json.loads(line) for line in approvals_path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    issued_event = ledger[-1]
    window = (opl.parse_ts(issued_event["expires_at"])
              - opl.parse_ts(issued_event["issued_at"])).total_seconds()
    check(issued_event["event"] == "issued" and window == 900,
          "the issued ledger event carries the exact 15-minute validity window")

    # Criterion 7: a reason edit is a different subject — the ticket does not match.
    mismatch, _ = run("work-cover", ["--work-id", wid, "--pathway", "observability", "--na",
                                     "--reason", "a different reason"])
    check("work-cover-production-secure-na-blocked" in ids(mismatch),
          "a waiver ticket bound to a different reason cannot be consumed")

    # Criterion 4: the exact subject consumes once and stamps the row with its waiver receipt.
    covered, _ = run("work-cover", ["--work-id", wid, "--pathway", "observability", "--na",
                                    "--reason", "watcher and health endpoint are live"])
    obs_entry = next(e for e in covered["records"][0]["itinerary"]
                     if e["pathway"] == "observability")
    check(obs_entry["status"] == "na"
          and obs_entry.get("waiver_digest") == issued.get("subject_digest")
          and bool(obs_entry.get("waiver_consumed_id")),
          "a matching active ticket marks the row N/A with its waiver digest and consumption id")
    ledger = [json.loads(line) for line in approvals_path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    consumed_events = [e for e in ledger if e.get("event") == "consumed"]
    check(len(consumed_events) == 1
          and consumed_events[0].get("consumed_by") == f"work-cover:{wid}:observability",
          "consumption appends one durable ledger event bound to the consuming work-cover")

    context_events = opl.approval_events_for(
        type("Paths", (), {"approvals_path": approvals_path})()
    )
    covered_item = covered["records"][0]
    context_digest = opl.work_context_sha256(covered_item, "observability")
    check(issued_event["subject"].get("schema_version") == 2
          and issued_event["subject"].get("work_context_sha256") == context_digest
          and opl.waiver_corroborated(obs_entry, covered_item, context_events),
          "a waiver v2 subject binds the unchanged work context and survives its status update")
    context_mutations = []
    for label, field, value in (
        ("work id", "work_id", "W-mutated-context"),
        ("project name", "project_name", "mutated-project"),
        ("resolved project path", "project", str(proj / "mutated-target")),
        ("goal", "goal", "mutated production goal"),
        ("tier", "tier", "live"),
        ("outcome profile", "outcome_profile", {"id": "mutated-profile"}),
        ("risk overlays", "risk_overlays", [{"id": "mutated-risk"}]),
    ):
        mutated_item = json.loads(json.dumps(covered_item))
        mutated_item[field] = value
        context_mutations.append((label, mutated_item))
    obligation_mutation = json.loads(json.dumps(covered_item))
    obligation_mutation["itinerary"] = [
        entry for entry in obligation_mutation["itinerary"]
        if entry.get("pathway") != "observability"
    ]
    context_mutations.append(("obligation identity", obligation_mutation))
    for label, mutated_item in context_mutations:
        check(not opl.waiver_corroborated(obs_entry, mutated_item, context_events),
              f"mutating the waiver-bound {label} invalidates corroboration")

    # Criterion 5: the consumed ticket cannot be spent by any other consumer.
    class _ApprovalPaths:
        pass
    ns = _ApprovalPaths()
    ns.approvals_path = approvals_path
    replayed, replay_refusal = opl.consume_approval(
        ns, issued_event["subject"], "work-cover:W-other:observability")
    check(replayed is None and replay_refusal == "consumed",
          "a consumed ticket is refused for any other consumer")

    # Criterion 6: an expired ticket fails closed.
    run("approval-issue", ["--kind", "production-secure-waiver", "--work-id", wid,
                           "--pathway", "techdebt", "--reason", "debt paid in the same change"])
    ledger = [json.loads(line) for line in approvals_path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    for event in ledger:
        if event.get("event") == "issued" and event.get("subject", {}).get("pathway") == "techdebt":
            event["issued_at"] = "2026-01-01T00:00:00Z"
            event["expires_at"] = "2026-01-01T00:15:00Z"
    approvals_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in ledger), encoding="utf-8")
    expired, _ = run("work-cover", ["--work-id", wid, "--pathway", "techdebt", "--na",
                                    "--reason", "debt paid in the same change"])
    check("work-cover-production-secure-na-blocked" in ids(expired)
          and any("expired" in json.dumps(f) for f in expired.get("findings", [])),
          "an expired waiver ticket is refused by name")

    # Criterion 8: status recomputation keeps the corroborated N/A row, reopens a forged one,
    # and reopens a tampered waiver digest.
    status, _ = run("work-status", ["--work-id", wid])
    states = {e["pathway"]: e["status"] for e in status["summary"]["itinerary"]}
    check(states["observability"] == "na",
          "a ledger-corroborated waived row survives status recomputation")
    items = [json.loads(line) for line in work_items_path.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    for item in items:
        if item.get("work_id") == wid:
            for entry in item.get("itinerary", []):
                if entry.get("pathway") == "security":
                    entry["status"] = "na"
                    entry["reason"] = "forged free-text waiver"
                if entry.get("pathway") == "observability":
                    entry["waiver_digest"] = "0" * 64
    work_items_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in items), encoding="utf-8")
    tampered_status, _ = run("work-status", ["--work-id", wid])
    tampered_states = {e["pathway"]: e["status"]
                       for e in tampered_status["summary"]["itinerary"]}
    check(tampered_states["security"] == "required",
          "an un-waivered production-secure N/A row still reopens")
    check(tampered_states["observability"] == "required",
          "a tampered waiver digest loses its corroboration and the row reopens")
    recovered, _ = run("work-cover", ["--work-id", wid, "--pathway", "observability", "--na",
                                      "--reason", "watcher and health endpoint are live"])
    recovered_entry = next(e for e in recovered["records"][0]["itinerary"]
                           if e["pathway"] == "observability")
    check(recovered_entry["status"] == "na"
          and recovered_entry.get("waiver_digest") == issued.get("subject_digest"),
          "re-covering with the identical subject restores the earned waiver idempotently")

    # Criteria 9 + 10: release production credit requires the single-use approval ticket.
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    subprocess.run(["git", "-C", str(proj), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(proj), "config", "user.name", "Pathway Test"], check=True)
    release_guard = proj / "release-guard.txt"
    release_guard.write_text("BASELINE\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(proj), "add", "release-guard.txt"], check=True)
    subprocess.run(["git", "-C", str(proj), "commit", "-q", "-m", "fixture baseline"], check=True)
    release_guard.write_text("PRODUCTION_RELEASE_READY\n", encoding="utf-8")
    recommendation_id = "REC-approval-authority"
    release_now = opl.utc_now()
    release_evidence = write(
        "out/operator-artifacts/approval-release.md",
        "This intentionally lacks the release carry-forward headings.\n",
    )
    receipt_path = write("out/operator-artifacts/approval-release.json", json.dumps({
        "work_id": wid,
        "recommendation_id": recommendation_id,
        "target_project": str(proj.resolve()),
        "issued_at": release_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (release_now + opl.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "release_decision": {
            "decision": "RELEASE", "release_gate": "PASS", "pathway_result": "PASS",
            "deployed": True, "production_mutation_performed": True,
            "current_authorized_stage": "PRODUCTION",
        },
        "release_receipt": {
            "preview_status": "ready", "canary_status": "passed", "production_status": "deployed",
            "rollback_status": "rehearsed", "external_send_state": "not-sent",
            "feature_flag_state": "disabled", "deploy_artifact": "deploy.json",
            "verification_artifact": "verification.json", "canary_artifact": "canary.json",
            "rollback_artifact": "rollback.json", "human_approval": "see approval ledger",
        },
    }))
    for artifact_name in ("deploy.json", "verification.json", "canary.json", "rollback.json"):
        write(f"out/operator-artifacts/{artifact_name}", json.dumps({"fixture": artifact_name}))
    receipt_sha = opl.sha256_file(receipt_path)
    release_verify = (
        "grep PRODUCTION_RELEASE_READY release-guard.txt && "
        "printf 'RELEASE_DECISION=RELEASE\\nRELEASE_GATE=PASS\\nPATHWAY_RESULT=PASS\\n"
        "PRODUCTION_STATUS=DEPLOYED\\nCANARY_STATUS=PASSED\\nROLLBACK_STATUS=REHEARSED\\n"
        "EXTERNAL_SEND_STATUS=NOT_SENT\\nEXTERNAL_SEND_COUNT=0\\n"
        f"RELEASE_RECEIPT_SHA256={receipt_sha}\\n'"
    )
    release_log_args = ["--work-id", wid, "--pathway", "release", "--kind", "verify",
                        "--evidence", str(receipt_path), "--result", "pass",
                        "--proof-type", "artifact", "--project", str(proj),
                        "--verify-cmd", release_verify,
                        "--canary-target", str(release_guard),
                        "--recommendation-id", recommendation_id]
    proofs_path = ROOT / "out/operator-intelligence/proofs.ndjson"

    def persisted_release_proof():
        rows = [
            json.loads(line)
            for line in proofs_path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        return next(
            row for row in reversed(rows)
            if row.get("pathway") == "release"
            and row.get("work_id") == wid
            and row.get("evidence_path") == str(receipt_path)
        )

    run("work-log", release_log_args)
    unapproved_proof = persisted_release_proof()
    check(unapproved_proof.get("release_approval_verified") is False
          and not opl.proof_is_verified(unapproved_proof),
          "a production release receipt without an approval ticket cannot credit")
    unapproved_status, _ = run("work-status", ["--work-id", wid])
    check({e["pathway"]: e["status"]
           for e in unapproved_status["summary"]["itinerary"]}["release"] == "required",
          "release stays open after an unapproved production log attempt")

    approved_issue, _ = run("approval-issue", [
        "--kind", "release-production-approval", "--work-id", wid,
        "--release-receipt", str(receipt_path), "--reason", "fixture production approval"])
    check(bool(approved_issue.get("subject_digest")),
          "approval-issue binds a release ticket to the exact receipt digest")

    invalid_template_args = list(release_log_args)
    invalid_template_args[invalid_template_args.index(str(receipt_path))] = str(release_evidence)
    run("work-log", invalid_template_args)
    invalid_template_proof = next(
        row for row in (
            json.loads(line)
            for line in proofs_path.read_text(encoding="utf-8").splitlines() if line.strip()
        )
        if row.get("pathway") == "release"
        and row.get("work_id") == wid
        and row.get("evidence_path") == str(release_evidence)
    )
    check(invalid_template_proof.get("template_check", {}).get("valid") is False
          and invalid_template_proof.get("release_approval_verified") is False
          and invalid_template_proof.get("release_approval_error")
          == "release_evidence_not_creditable",
          "an invalid template cannot consume the exact production ticket")

    run("work-log", release_log_args)
    approved_proof = persisted_release_proof()
    check(approved_proof.get("release_approval_verified") is True,
          "typed JSON receipt consumes its exact production ticket")
    check(bool(approved_proof.get("release_approval_consumed_id"))
          and approved_proof.get("release_approval_digest") == approved_issue.get("subject_digest"),
          "typed JSON receipt records the exact production ticket consumption")
    check(approved_proof.get("template_check") == {
              "valid": True,
              "template_id": "release-production-receipt-v1",
              "missing": [],
          },
          "typed JSON receipt is its own closed production template")
    check(opl.proof_is_verified(approved_proof),
          "the exact typed JSON receipt credits once its single-use ticket is consumed")
    approved_status, _ = run("work-status", ["--work-id", wid])
    check({e["pathway"]: e["status"]
           for e in approved_status["summary"]["itinerary"]}["release"] == "proved",
          "release flips to proved through the approved, corroborated proof")

    # Close the remaining fixture pathways with exact waiver tickets so the item is genuinely
    # ready and closed before its release approval is invalidated. This exercises current views,
    # not a hand-edited status label.
    for pathway in approved_status["summary"]["itinerary_coverage"]["open"]:
        if pathway == "release":
            continue
        reason = f"{pathway} is not applicable in the release invalidation fixture"
        run("approval-issue", [
            "--kind", "production-secure-waiver", "--work-id", wid,
            "--pathway", pathway, "--reason", reason,
        ])
        run("work-cover", [
            "--work-id", wid, "--pathway", pathway, "--na", "--reason", reason,
        ])
    closed, _ = run("work-close", ["--work-id", wid])
    check(closed.get("closed") is True,
          "the fully corroborated fixture closes before its release ticket is invalidated")

    carry_forward_path = ROOT / "out/operator-intelligence/pathway-carry-forward.ndjson"
    raw_carry_forwards = [
        json.loads(line)
        for line in carry_forward_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    historical_release = next(
        row for row in reversed(raw_carry_forwards)
        if row.get("work_id") == wid and row.get("pathway") == "release"
    )
    check(historical_release.get("credits_pathway") is True
          and historical_release.get("pathway_outcome") == "proved",
          "the historical release carry-forward records the originally credited decision")

    release_ticket = approved_issue["records"][0]["ticket_id"]
    invalidated, _ = run("approval-invalidate", [
        "--ticket-id", release_ticket,
        "--reason", "release approval was issued through an agent bypass",
    ])
    check(invalidated.get("status") == "invalidated",
          "the exact consumed release ticket accepts an append-only invalidation")
    reopened_status, _ = run("work-status", ["--work-id", wid])
    reopened_states = {
        entry["pathway"]: entry["status"]
        for entry in reopened_status["summary"]["itinerary"]
    }
    check(reopened_states["release"] == "required"
          and reopened_status["summary"]["closeout_readiness"] == "not_ready",
          "status-time corroboration reopens release after exact-ticket invalidation")
    persisted_closed = next(
        item for item in (
            json.loads(line)
            for line in work_items_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if item.get("work_id") == wid
    )
    check(persisted_closed.get("status") == "closed",
          "the raw work ledger preserves the historical close event")
    daily, _ = run("work-daily")
    dashboard = read_json(daily["dashboard"])
    current_item = next(
        item for item in dashboard.get("active_work_items", [])
        if item.get("work_id") == wid
    )
    check(current_item.get("persisted_status") == "closed"
          and current_item.get("current_status_reason") == "approval_invalidated",
          "the dashboard projects invalidated closed work back into the active current view")
    view_paths = type("Paths", (), {
        "approvals_path": approvals_path,
        "proofs_path": proofs_path,
        "carry_forward_path": carry_forward_path,
    })()
    corrected_carry = opl.latest_carry_forward_for_work(view_paths, wid)
    check(corrected_carry.get("credits_pathway") is False
          and corrected_carry.get("pathway_outcome") == "approval_invalidated",
          "the latest carry-forward view removes invalidated release credit")
    later_docs = {
        **historical_release,
        "carry_forward_id": "CF-later-docs-after-release",
        "pathway": "docs",
        "proof_id": "P-later-docs",
        "summary": "Documentation followed the historical release proof.",
        "source_artifact": "/tmp/later-docs.md",
        "what_changed": ["The operator guide now names the current workflow."],
        "more_relevant": ["Use the current operator guide."],
        "less_relevant": ["Ignore the superseded draft."],
        "next_pathway_must_use": ["Read the current operator guide first."],
        "do_not_do_yet": ["Do not skip the docs review."],
        "open_decisions": ["Choose the final navigation label."],
        "active_risk_overlays": ["rollback", "docs-freshness"],
        "source": "docs carry-forward fixture",
        "created_at": "2099-01-01T00:00:00Z",
    }
    raw_carry_forwards.append(later_docs)
    carry_forward_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in raw_carry_forwards),
        encoding="utf-8",
    )
    corrected_later_baton = opl.latest_carry_forward_for_work(view_paths, wid)
    check(corrected_later_baton.get("pathway") == "docs"
          and corrected_later_baton.get("credits_pathway") is True
          and corrected_later_baton.get("release_credit_current") is False
          and corrected_later_baton.get("release_pathway_outcome")
          == "approval_invalidated",
          "a later non-release baton still carries the current release invalidation overlay")
    preserved_docs_fields = {
        key: corrected_later_baton.get(key)
        for key in (
            "summary", "source_artifact", "what_changed", "more_relevant", "less_relevant",
            "next_pathway_must_use", "do_not_do_yet", "open_decisions",
            "active_risk_overlays", "source",
        )
    }
    check(preserved_docs_fields == {key: later_docs[key] for key in preserved_docs_fields}
          and corrected_later_baton.get("release_approval_summary")
          == "The release approval no longer corroborates; release proof is open again."
          and corrected_later_baton.get("invalidated_release_proof_id")
          == historical_release.get("proof_id"),
          "release invalidation overlays a later baton without clobbering its continuity fields")
    visible_overlay = opl.carry_forward_effect(corrected_later_baton, "release")
    check(later_docs["summary"] in visible_overlay
          and corrected_later_baton["release_approval_summary"] in visible_overlay
          and corrected_later_baton["release_approval_do_not_do_yet"][0] in visible_overlay,
          "a later docs baton stays primary while its release hold is operator-visible")

    invalidated_ledger_bytes = approvals_path.read_bytes()
    proof_rows = [
        json.loads(line) for line in proofs_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    release_proof_row = next(
        row for row in proof_rows
        if row.get("proof_id") == historical_release.get("proof_id")
    )
    original_consumption_id = release_proof_row["release_approval_consumed_id"]
    release_proof_row["release_approval_consumed_id"] = "AC-ffffffffffff"
    proofs_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in proof_rows),
        encoding="utf-8",
    )
    uncorroborated_carry = opl.latest_carry_forward_for_work(view_paths, wid)
    check(uncorroborated_carry.get("release_pathway_outcome")
          == "approval_uncorroborated"
          and uncorroborated_carry.get("summary") == later_docs["summary"],
          "a mismatched release claim is classified as uncorroborated without clobbering docs")
    release_proof_row["release_approval_consumed_id"] = original_consumption_id
    proofs_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in proof_rows),
        encoding="utf-8",
    )

    approvals_path.write_bytes(invalidated_ledger_bytes + b'{"event":"invalidated"')
    invalid_ledger_carry = opl.latest_carry_forward_for_work(view_paths, wid)
    check(invalid_ledger_carry.get("release_pathway_outcome")
          == "approval_ledger_invalid"
          and invalid_ledger_carry.get("release_approval_state_reason")
          == "truncated-tail"
          and invalid_ledger_carry.get("summary") == later_docs["summary"],
          "an invalid authority ledger is classified separately and preserves the later baton")
    approvals_path.write_bytes(invalidated_ledger_bytes)

    proof_ledger_bytes = proofs_path.read_bytes()
    carry_forward_bytes = carry_forward_path.read_bytes()
    proofs_path.write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n" for row in proof_rows
            if row.get("proof_id") != historical_release.get("proof_id")
        ),
        encoding="utf-8",
    )
    missing_proof_docs = opl.latest_carry_forward_for_work(view_paths, wid)
    check(missing_proof_docs.get("release_pathway_outcome") == "release_proof_missing"
          and missing_proof_docs.get("credits_pathway") is True
          and missing_proof_docs.get("summary") == later_docs["summary"],
          "a missing release proof overlays a later docs baton without clobbering it")
    carry_forward_path.write_text(
        json.dumps(historical_release, sort_keys=True) + "\n", encoding="utf-8"
    )
    missing_proof_release = opl.latest_carry_forward_for_work(view_paths, wid)
    check(missing_proof_release.get("credits_pathway") is False
          and missing_proof_release.get("pathway_outcome") == "release_proof_missing"
          and missing_proof_release.get("release_proof_id")
          == historical_release.get("proof_id"),
          "a missing release proof removes credit from the latest release baton")
    proofs_path.write_bytes(proof_ledger_bytes)
    carry_forward_path.write_bytes(carry_forward_bytes)

    raw_after_invalidation = next(
        row for row in reversed([
            json.loads(line)
            for line in carry_forward_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ])
        if row.get("work_id") == wid and row.get("pathway") == "release"
    )
    check(raw_after_invalidation.get("credits_pathway") is True
          and raw_after_invalidation.get("pathway_outcome") == "proved",
          "the raw carry-forward ledger preserves the historical proved record")

    clean_issue, _ = run("approval-issue", [
        "--kind", "release-production-approval", "--work-id", wid,
        "--release-receipt", str(receipt_path),
        "--reason", "independent fixture reapproval",
    ])
    run("work-log", release_log_args)
    restored_status, _ = run("work-status", ["--work-id", wid])
    check(clean_issue["records"][0]["ticket_id"] != release_ticket
          and restored_status["summary"]["closeout_readiness"] == "ready",
          "a new exact ticket and new consumption restore readiness without reviving the old ticket")
    restored_daily, _ = run("work-daily")
    restored_dashboard = read_json(restored_daily["dashboard"])
    check(wid not in {
              item.get("work_id")
              for item in restored_dashboard.get("active_work_items", [])
          },
          "a clean reapproval returns the still-closed item to the effective closed set")

    # Criterion 10 tail: deleting the consumption from the ledger kills the credit at status time.
    ledger = [json.loads(line) for line in approvals_path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    pruned = [event for event in ledger
              if not (event.get("event") == "consumed"
                      and event.get("kind") == "release-production-approval")]
    approvals_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in pruned), encoding="utf-8")
    uncorroborated_status, _ = run("work-status", ["--work-id", wid])
    check({e["pathway"]: e["status"]
           for e in uncorroborated_status["summary"]["itinerary"]}["release"] == "required",
          "a release proof whose approval is missing from the ledger loses credit at status time")
    check(uncorroborated_status["summary"]["work_item"].get("status") == "active"
          and uncorroborated_status["summary"]["work_item"].get("current_status_reason")
          == "approval_uncorroborated",
          "work-status reopens a closed item whose claimed release consumption is missing")
    uncorroborated_daily, _ = run("work-daily")
    uncorroborated_dashboard = read_json(uncorroborated_daily["dashboard"])
    check(any(
              item.get("work_id") == wid
              and item.get("current_status_reason") == "approval_uncorroborated"
              for item in uncorroborated_dashboard.get("active_work_items", [])
          ),
          "the dashboard exposes closed work with an uncorroborated approval claim")
    uncorroborated_route, uncorroborated_route_proc = run("pathway-next", [
        "--project", str(proj), "--work-id", wid,
    ])
    check(uncorroborated_route_proc.returncode == 0
          and uncorroborated_route.get("work_id") == wid,
          "pathway-next can continue closed work with an uncorroborated approval claim")
    uncorroborated_portfolio, _ = run("portfolio-next")
    uncorroborated_portfolio_row = next(
        row for row in uncorroborated_portfolio.get("records", [])
        if row.get("project") == proj.name
    )
    check(uncorroborated_portfolio_row.get("active_work") == 1,
          "portfolio-next counts uncorroborated historically closed work as active")


def test_production_secure_closed_view_rechecks_current_readiness():
    """Deleting approval claims cannot hide a forged production-secure close."""
    reset()
    proj = ROOT / "projects" / "closed-view-root-authority-proj"
    proj.mkdir(parents=True, exist_ok=True)
    started, _ = run("work-start", [
        "--project", str(proj),
        "--goal", "production authority current-view regression",
        "--tier", "production-secure",
    ])
    wid = started["work_id"]
    work_items_path = ROOT / "out/operator-intelligence/work-items.ndjson"
    items = [
        json.loads(line)
        for line in work_items_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    target = next(item for item in items if item.get("work_id") == wid)
    target["status"] = "closed"
    target["closed_at"] = "2026-08-31T00:00:00Z"
    claimed = target["itinerary"][0]
    claimed.update({
        "status": "na",
        "reason": "forged approval claim fixture",
        "waiver_digest": "0" * 64,
        "waiver_consumed_id": "AC-000000000000",
    })
    work_items_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in items),
        encoding="utf-8",
    )
    claimed_status, _ = run("work-status", ["--work-id", wid])
    check(claimed_status["summary"]["work_item"].get("current_status_reason")
          == "approval_uncorroborated",
          "a forged approval claim cannot keep a production-secure item closed")

    # Deleting the claim fields must not turn the historical closed label into authority.
    for field in ("waiver_digest", "waiver_consumed_id"):
        claimed.pop(field, None)
    work_items_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in items),
        encoding="utf-8",
    )
    stripped_status, _ = run("work-status", ["--work-id", wid])
    current_item = stripped_status["summary"]["work_item"]
    check(current_item.get("status") == "active"
          and current_item.get("persisted_status") == "closed"
          and current_item.get("current_status_reason")
          == "production_secure_not_ready",
          "claim deletion still reopens a not-ready production-secure close")
    daily, _ = run("work-daily")
    dashboard = read_json(daily["dashboard"])
    check(any(item.get("work_id") == wid
              for item in dashboard.get("active_work_items", [])),
          "the dashboard exposes a bare forged production-secure close")
    routed, routed_proc = run("pathway-next", [
        "--project", str(proj), "--work-id", wid,
    ])
    check(routed_proc.returncode == 0 and routed.get("work_id") == wid,
          "pathway-next continues a bare forged production-secure close")
    portfolio, _ = run("portfolio-next")
    portfolio_row = next(
        row for row in portfolio.get("records", []) if row.get("project") == proj.name
    )
    check(portfolio_row.get("active_work") == 1,
          "portfolio-next counts a bare forged production-secure close as active")
    calibration, _ = run("tier-calibrate")
    secure_tier = next(
        tier for tier in calibration.get("tiers", [])
        if tier.get("tier") == "production-secure"
    )
    check(secure_tier.get("closed_outcomes") == 0,
          "tier calibration excludes a bare forged production-secure close")
    persisted = next(
        item for item in (
            json.loads(line)
            for line in work_items_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if item.get("work_id") == wid
    )
    check(persisted.get("status") == "closed",
          "current-view correction preserves the append-only historical close")


def test_live_closed_view_reopens_when_release_proof_is_missing():
    """A user-writable proof deletion cannot preserve cached release authority at live tier."""
    opl = load_cli("live_release_proof_deletion")
    reset()
    proj = ROOT / "projects" / "live-release-proof-deletion-proj"
    proj.mkdir(parents=True, exist_ok=True)
    started, _ = run("work-start", [
        "--project", str(proj),
        "--goal", "ship an internal live workflow",
        "--tier", "live",
    ])
    wid = started["work_id"]
    work_items_path = ROOT / "out/operator-intelligence/work-items.ndjson"
    items = [
        json.loads(line)
        for line in work_items_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    target = next(item for item in items if item.get("work_id") == wid)
    target["status"] = "closed"
    target["closed_at"] = "2026-08-31T00:00:00Z"
    for entry in target["itinerary"]:
        entry["status"] = "proved"
        entry["proved_by_run"] = f"R-deleted-{entry['pathway']}"
    work_items_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in items),
        encoding="utf-8",
    )

    # Preserve the stronger adversarial shape too: the root/user test ledger still records an
    # invalidated consumed release ticket, while the same-user proof row it named is gone.
    subject = opl.release_approval_subject(wid, proj.name, "a" * 64)
    digest = opl.approval_subject_digest(subject)
    approvals_path = ROOT / "out/operator-intelligence/approvals.ndjson"
    approval_events = [
        {
            "event": "issued", "kind": opl.APPROVAL_KIND_RELEASE,
            "subject_digest": digest, "ticket_id": "AT-111111111111",
            "subject": subject, "issued_at": "2026-08-31T00:00:00Z",
            "expires_at": "2026-08-31T00:15:00Z", "reason": "reviewed release",
            "work_id": wid, "issued_by": "fixture-human",
        },
        {
            "event": "consumed", "kind": opl.APPROVAL_KIND_RELEASE,
            "subject_digest": digest, "ticket_id": "AT-111111111111",
            "at": "2026-08-31T00:01:00Z", "work_id": wid, "pathway": "release",
            "consumed_by": "P-deleted-release-proof", "consumption_id": "AC-222222222222",
        },
        {
            "event": "invalidated", "kind": opl.APPROVAL_KIND_RELEASE,
            "subject_digest": digest, "ticket_id": "AT-111111111111",
            "at": "2026-08-31T00:02:00Z", "work_id": wid,
            "reason": "compromised approval", "invalidated_by": "fixture-human",
            "invalidation_id": "AI-333333333333",
        },
    ]
    approvals_path.parent.mkdir(parents=True, exist_ok=True)
    approvals_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in approval_events),
        encoding="utf-8",
    )

    status, status_proc = run("work-status", ["--work-id", wid])
    current = status["summary"]["work_item"]
    release_entry = next(
        entry for entry in status["summary"]["itinerary"]
        if entry.get("pathway") == "release"
    )
    check(status_proc.returncode == 0
          and release_entry.get("status") == "required"
          and status["summary"]["closeout_readiness"] == "not_ready"
          and current.get("status") == "active"
          and current.get("persisted_status") == "closed"
          and current.get("current_status_reason") == "release_proof_missing",
          "a missing live-tier release proof reopens cached credit and the closed current view")
    valid_ledger = approvals_path.read_bytes()
    approvals_path.write_bytes(valid_ledger + b'{"event":"invalidated"')
    invalid_status, invalid_status_proc = run("work-status", ["--work-id", wid])
    invalid_current = invalid_status["summary"]["work_item"]
    check(invalid_status_proc.returncode == 0
          and invalid_status["summary"]["closeout_readiness"] == "not_ready"
          and invalid_current.get("status") == "active"
          and invalid_current.get("current_status_reason") == "approval_ledger_invalid",
          "proof deletion plus an invalid authority ledger still reopens a live closed view")
    approvals_path.write_bytes(valid_ledger)
    persisted = next(
        item for item in (
            json.loads(line)
            for line in work_items_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if item.get("work_id") == wid
    )
    check(persisted.get("status") == "closed",
          "missing-proof projection preserves the append-only historical close")


def test_approval_invalidation_revokes_exact_ticket_credit():
    """Invalidation is append-only, exact-ticket, and retroactive for waiver and release credit."""
    opl = load_cli("approval_invalidation")
    reset()
    proj = ROOT / "projects" / "approval-invalidation-proj"
    proj.mkdir(parents=True, exist_ok=True)
    started, _ = run("work-start", [
        "--project", str(proj),
        "--goal", "invalidate compromised approval tickets",
        "--tier", "production-secure",
    ])
    wid = started["work_id"]
    approvals_path = ROOT / "out/operator-intelligence/approvals.ndjson"

    waiver_reason = "runtime proof was independently replaced"
    waiver_issue, _ = run("approval-issue", [
        "--kind", "production-secure-waiver", "--work-id", wid,
        "--pathway", "observability", "--reason", waiver_reason,
    ])
    waiver_ticket = waiver_issue["records"][0]["ticket_id"]
    covered, _ = run("work-cover", [
        "--work-id", wid, "--pathway", "observability", "--na", "--reason", waiver_reason,
    ])
    waiver_entry = next(
        entry for entry in covered["records"][0]["itinerary"]
        if entry["pathway"] == "observability"
    )
    events = opl.approval_events_for(type("Paths", (), {"approvals_path": approvals_path})())
    check(opl.waiver_corroborated(waiver_entry, covered["records"][0], events),
          "the waiver credits before its exact ticket is invalidated")

    # Make every other pathway independently ready, then close through the real gate. This makes
    # the observability ticket causally load-bearing instead of force-closing unrelated debt.
    waiver_status, _ = run("work-status", ["--work-id", wid])
    for pathway in waiver_status["summary"]["itinerary_coverage"]["open"]:
        if pathway == "observability":
            continue
        reason = f"{pathway} is independently waived in the exact-ticket fixture"
        run("approval-issue", [
            "--kind", "production-secure-waiver", "--work-id", wid,
            "--pathway", pathway, "--reason", reason,
        ])
        run("work-cover", [
            "--work-id", wid, "--pathway", pathway, "--na", "--reason", reason,
        ])
    run_evidence = write("out/operator-artifacts/waiver-invalidation-run.txt", "run exists\n")
    run("work-log", [
        "--work-id", wid, "--pathway", "govern", "--kind", "note",
        "--evidence", str(run_evidence), "--result", "recorded",
    ])
    closed, _ = run("work-close", ["--work-id", wid])
    check(closed.get("closed") is True,
          "the waiver invalidation fixture closes through fully corroborated current state")

    # Reproduce the compromised historical shape: the ticket helped close the item before the
    # bypass was discovered. Invalidation must restore it to active current work without
    # deleting the old approval events.
    work_items_path = ROOT / "out/operator-intelligence/work-items.ndjson"

    invalidated, _ = run("approval-invalidate", [
        "--ticket-id", waiver_ticket, "--reason", "ticket was issued through an agent bypass",
    ])
    check(invalidated.get("status") == "invalidated"
          and invalidated["records"][0].get("event") == "invalidated"
          and invalidated["records"][0].get("ticket_id") == waiver_ticket,
          "approval-invalidate appends an event bound to the exact waiver ticket")
    persisted_item = next(
        item for item in (
            json.loads(line)
            for line in work_items_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if item.get("work_id") == wid
    )
    check(persisted_item.get("status") == "closed",
          "invalidation preserves the historical closed work record")
    daily, _ = run("work-daily")
    daily_dashboard = read_json(daily["dashboard"])
    current_item = next(
        item for item in daily_dashboard.get("active_work_items", [])
        if item.get("work_id") == wid
    )
    check(current_item.get("status") == "active"
          and current_item.get("persisted_status") == "closed"
          and current_item.get("current_status_reason") == "approval_invalidated",
          "the invalidated closed item returns to the current active-work dashboard view")
    check(daily.get("summary", {}).get("active") == 1
          and daily.get("summary", {}).get("closed") == 0,
          "dashboard counts use invalidation-aware current status")
    events = [json.loads(line) for line in approvals_path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    check(not opl.waiver_corroborated(waiver_entry, persisted_item, events),
          "an invalidated consumed waiver loses corroboration")
    current_context_sha = opl.work_context_sha256(persisted_item, "observability")
    blocked_consumption, refusal = opl.consume_approval(
        type("Paths", (), {"approvals_path": approvals_path})(),
        opl.waiver_subject(
            wid, proj.name, "observability", waiver_reason, current_context_sha
        ),
        f"work-cover:{wid}:observability",
    )
    check(blocked_consumption is None and refusal == "invalidated",
          "invalidation is checked before idempotent consumption reuse")
    status, _ = run("work-status", ["--work-id", wid])
    check({entry["pathway"]: entry["status"]
           for entry in status["summary"]["itinerary"]}["observability"] == "required",
          "status recomputation reopens an invalidated waiver")
    check(status["summary"]["work_item"].get("status") == "active"
          and status["summary"]["work_item"].get("current_status_reason")
          == "approval_invalidated",
          "work-status exposes the same invalidation-aware current status as the dashboard")
    calibration, _ = run("tier-calibrate")
    production_secure_tier = next(
        tier for tier in calibration.get("tiers", [])
        if tier.get("tier") == "production-secure"
    )
    check(production_secure_tier.get("closed_outcomes") == 0,
          "tier calibration excludes a historically closed outcome reopened by invalidation")
    routed, routed_proc = run("pathway-next", [
        "--project", str(proj), "--work-id", wid,
    ])
    check(routed_proc.returncode == 0 and routed.get("work_id") == wid,
          "pathway-next can continue an invalidated historically closed work item")
    portfolio, _ = run("portfolio-next")
    portfolio_row = next(
        row for row in portfolio.get("records", []) if row.get("project") == proj.name
    )
    check(portfolio_row.get("active_work") == 1,
          "portfolio-next counts invalidated historically closed work as currently active")

    repeated, _ = run("approval-invalidate", [
        "--ticket-id", waiver_ticket, "--reason", "repeat correction is idempotent",
    ])
    events_after_repeat = [
        json.loads(line) for line in approvals_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    check(repeated.get("status") == "already_invalidated"
          and len([event for event in events_after_repeat
                   if event.get("event") == "invalidated"
                   and event.get("ticket_id") == waiver_ticket]) == 1,
          "repeating an invalidation is idempotent and does not append a duplicate")

    reissued, _ = run("approval-issue", [
        "--kind", "production-secure-waiver", "--work-id", wid,
        "--pathway", "observability", "--reason", waiver_reason,
    ])
    check(reissued["records"][0]["ticket_id"] != waiver_ticket,
          "a later deliberate issue receives a distinct ticket id")
    still_open, _ = run("work-status", ["--work-id", wid])
    check({entry["pathway"]: entry["status"]
           for entry in still_open["summary"]["itinerary"]}["observability"] == "required",
          "a clean reissue without a new consumption cannot launder the old consumption")
    recovered, _ = run("work-cover", [
        "--work-id", wid, "--pathway", "observability", "--na", "--reason", waiver_reason,
    ])
    recovered_entry = next(
        entry for entry in recovered["records"][0]["itinerary"]
        if entry["pathway"] == "observability"
    )
    check(recovered_entry.get("waiver_consumed_id") != waiver_entry.get("waiver_consumed_id"),
          "the new ticket earns credit only after its own new consumption")
    recovered_events = opl.approval_events_for(
        type("Paths", (), {"approvals_path": approvals_path})()
    )
    recovered_consumption = next(
        event for event in reversed(recovered_events)
        if event.get("event") == "consumed"
        and event.get("consumption_id") == recovered_entry.get("waiver_consumed_id")
    )
    check(recovered_consumption.get("ticket_id") == reissued["records"][0]["ticket_id"]
          and opl.waiver_corroborated(
              recovered_entry, recovered["records"][0], recovered_events
          ),
          "the replacement waiver corroborates only against its own ticket consumption")

    # An invalidated ticket that was never consumed did not grant credit and cannot reopen work.
    unused_reason = "docs is independently waived in the exact-ticket fixture"
    unused_issue, _ = run("approval-issue", [
        "--kind", "production-secure-waiver", "--work-id", wid,
        "--pathway", "docs", "--reason", unused_reason,
    ])
    run("approval-invalidate", [
        "--ticket-id", unused_issue["records"][0]["ticket_id"],
        "--reason", "unused ticket correction fixture",
    ])
    unused_daily, _ = run("work-daily")
    unused_dashboard = read_json(unused_daily["dashboard"])
    check(wid not in {
              item.get("work_id")
              for item in unused_dashboard.get("active_work_items", [])
          },
          "invalidating an unconsumed ticket does not falsely reopen unrelated closed work")

    # Authority corruption fails closed across every current-state surface while raw history
    # remains untouched. Restore the bytes afterward so later exact-ticket checks stay isolated.
    valid_ledger_bytes = approvals_path.read_bytes()
    approvals_path.write_bytes(valid_ledger_bytes + b'{"event":"invalidated"')
    invalid_status, _ = run("work-status", ["--work-id", wid])
    check(invalid_status["summary"]["work_item"].get("status") == "active"
          and invalid_status["summary"]["work_item"].get("current_status_reason")
          == "approval_ledger_invalid",
          "a truncated approval ledger reopens approval-dependent work-status fail closed")
    invalid_daily, _ = run("work-daily")
    invalid_dashboard = read_json(invalid_daily["dashboard"])
    check(any(
              item.get("work_id") == wid
              and item.get("current_status_reason") == "approval_ledger_invalid"
              for item in invalid_dashboard.get("active_work_items", [])
          ),
          "a truncated approval ledger reopens the dashboard current view")
    invalid_route, invalid_route_proc = run("pathway-next", [
        "--project", str(proj), "--work-id", wid,
    ])
    check(invalid_route_proc.returncode == 0 and invalid_route.get("work_id") == wid,
          "pathway-next can route approval-dependent work while authority is fail closed")
    invalid_portfolio, _ = run("portfolio-next")
    invalid_portfolio_row = next(
        row for row in invalid_portfolio.get("records", []) if row.get("project") == proj.name
    )
    check(invalid_portfolio_row.get("active_work") == 1,
          "portfolio-next exposes approval-dependent work while authority is fail closed")
    approvals_path.write_bytes(valid_ledger_bytes)

    receipt = write("out/operator-artifacts/invalidation-release.json", "{\"release\":true}\n")
    receipt_sha = opl.sha256_file(receipt)
    release_issue, _ = run("approval-issue", [
        "--kind", "release-production-approval", "--work-id", wid,
        "--release-receipt", str(receipt), "--reason", "reviewed release correction fixture",
    ])
    release_ticket = release_issue["records"][0]["ticket_id"]
    release_subject = opl.release_approval_subject(wid, proj.name, receipt_sha)
    paths = type("Paths", (), {"approvals_path": approvals_path})()
    consumption, refusal = opl.consume_approval(paths, release_subject, "P-invalidation-release")
    check(consumption is not None and refusal == "",
          "the release fixture consumes its exact ticket before invalidation")
    release_proof = {
        "work_id": wid,
        "project": proj.name,
        "proof_id": "P-invalidation-release",
        "release_receipt_sha256": receipt_sha,
        "release_approval_digest": release_issue["subject_digest"],
        "release_approval_consumed_id": consumption["consumption_id"],
    }
    events = opl.approval_events_for(paths)
    check(opl.release_approval_corroborated(release_proof, events),
          "the release approval corroborates before invalidation")

    proofs_path = ROOT / "out/operator-intelligence/proofs.ndjson"
    carry_forward_path = ROOT / "out/operator-intelligence/pathway-carry-forward.ndjson"
    proofs_path.write_text(json.dumps(release_proof, sort_keys=True) + "\n", encoding="utf-8")
    carry_forward = {
        "carry_forward_id": "CF-invalidation-release",
        "work_id": wid,
        "project": proj.name,
        "pathway": "release",
        "source_artifact": str(receipt),
        "summary": "Release proof previously credited.",
        "what_changed": ["Release was marked proved."],
        "more_relevant": [],
        "less_relevant": [],
        "next_pathway_must_use": ["Use the release proof."],
        "do_not_do_yet": [],
        "open_decisions": [],
        "active_risk_overlays": [],
        "artifact_sha256": receipt_sha,
        "proof_id": release_proof["proof_id"],
        "credits_pathway": True,
        "pathway_outcome": "proved",
        "created_at": "2026-08-30T00:00:00Z",
    }
    carry_forward_path.write_text(
        json.dumps(carry_forward, sort_keys=True) + "\n", encoding="utf-8"
    )
    view_paths = type("Paths", (), {
        "approvals_path": approvals_path,
        "proofs_path": proofs_path,
        "carry_forward_path": carry_forward_path,
    })()
    check(opl.latest_carry_forward_for_work(view_paths, wid).get("credits_pathway") is True,
          "a currently corroborated release baton remains proved")
    run("approval-invalidate", [
        "--ticket-id", release_ticket, "--reason", "release ticket came from an agent bypass",
    ])
    check(not opl.release_approval_corroborated(release_proof, opl.approval_events_for(paths)),
          "an invalidated consumed release ticket loses corroboration")
    corrected = opl.latest_carry_forward_for_work(view_paths, wid)
    check(corrected.get("credits_pathway") is False
          and corrected.get("pathway_outcome") == "approval_invalidated",
          "the current carry-forward view cannot retain proved release credit after invalidation")

    missing, _ = run("approval-invalidate", [
        "--ticket-id", "AT-ffffffffffff", "--reason", "unknown ticket regression",
    ])
    check("approval-invalidate-ticket-not-found" in ids(missing),
          "approval-invalidate refuses an unknown exact ticket")


def test_release_provider_action_consumes_approval_without_release_credit():
    """A provider action has its own closed verifier contract. It may consume the exact
    production approval after the action ran, but it is not the final release receipt and can
    never close the release pathway."""
    opl = load_cli("release_provider_action")
    reset()
    proj = ROOT / "projects" / "provider-action-proj"
    proj.mkdir(parents=True, exist_ok=True)
    started, _ = run("work-start", [
        "--project", str(proj),
        "--goal", "ship a production release through approved provider actions",
        "--tier", "live",
    ])
    wid = started["work_id"]
    approvals_path = ROOT / "out/operator-intelligence/approvals.ndjson"
    proofs_path = ROOT / "out/operator-intelligence/proofs.ndjson"

    allowed_actions = {
        "apply-product-migration", "deploy-canary", "promote-public-stage",
    }
    check(opl.RELEASE_PROVIDER_ACTIONS == allowed_actions,
          "provider-action contract exposes only the three fixed release actions")

    digest = "a" * 64
    valid_stdout = (
        "PROVIDER_ACTION=deploy-canary\n"
        "PROVIDER_ACTION_PROOF=PASS\n"
        "PATHWAY_RESULT=PASS\n"
        f"RELEASE_RECEIPT_SHA256={digest}\n"
    )
    check(opl.release_provider_action_verifier_binding(
        valid_stdout, "deploy-canary", digest)["bound"] is True,
        "provider-action verifier accepts the exact four-marker contract")
    rejected_bindings = {
        "wrong action": valid_stdout.replace("deploy-canary", "apply-product-migration"),
        "unknown action": valid_stdout.replace("deploy-canary", "deploy-everything"),
        "duplicate marker": valid_stdout + "PATHWAY_RESULT=PASS\n",
        "extra marker": valid_stdout + "RELEASE_DECISION=RELEASE\n",
        "digest mismatch": valid_stdout.replace(digest, "b" * 64),
        "false deployed claim": valid_stdout + "PRODUCTION_STATUS=DEPLOYED\n",
    }
    for label, stdout in rejected_bindings.items():
        check(not opl.release_provider_action_verifier_binding(
            stdout, "deploy-canary", digest)["bound"],
            f"provider-action verifier rejects {label}")

    verifier_body = (
        "import hashlib\n"
        "import sys\n"
        "from pathlib import Path\n"
        "action, receipt_raw, exit_raw, mutate_receipt, mutate_source, extra, sentinel = sys.argv[1:8]\n"
        "receipt = Path(receipt_raw)\n"
        "receipt_digest = hashlib.sha256(receipt.read_bytes()).hexdigest()\n"
        "if sentinel:\n"
        "    Path(sentinel).write_text('executed', encoding='utf-8')\n"
        "if mutate_receipt == '1':\n"
        "    receipt.write_text('tampered', encoding='utf-8')\n"
        "if mutate_source == '1':\n"
        "    Path(__file__).write_text('tampered', encoding='utf-8')\n"
        "sys.stdout.write(\n"
        "    f'PROVIDER_ACTION={action}\\n'\n"
        "    'PROVIDER_ACTION_PROOF=PASS\\n'\n"
        "    'PATHWAY_RESULT=PASS\\n'\n"
        "    f'RELEASE_RECEIPT_SHA256={receipt_digest}\\n'\n"
        "    f'{extra}'\n"
        ")\n"
        "raise SystemExit(int(exit_raw))\n"
    )

    def verifier_source(name, prefix=""):
        return write(f"out/test-verifiers/{name}.py", prefix + verifier_body)

    def authorization(name, source, action="deploy-canary", *, verifier_field=None,
                      omit_verifier_field=False):
        document = {
            "version": 1,
            "work_id": wid,
            "project": proj.name,
            "site": "https://example.test",
            "action": action,
            "fixture": name,
        }
        if not omit_verifier_field:
            document["verifier_source_sha256"] = (
                opl.sha256_file(source) if verifier_field is None else verifier_field
            )
        return write(
            f"out/operator-artifacts/{name}.json",
            json.dumps(document, sort_keys=True),
        )

    def issue(receipt, reason):
        result, _ = run("approval-issue", [
            "--kind", "release-production-approval",
            "--work-id", wid,
            "--release-receipt", str(receipt),
            "--reason", reason,
        ])
        return result

    def verifier(source, receipt, action="deploy-canary", exit_code=0, *,
                 mutate_receipt=False, mutate_source=False, extra="", sentinel=None,
                 extra_args=()):
        return " ".join(shlex.quote(str(value)) for value in (
            sys.executable, "-B", source, action, receipt, exit_code,
            int(mutate_receipt), int(mutate_source), extra, sentinel or "",
            *extra_args,
        ))

    def log_action(receipt, recommendation, source, action="deploy-canary", exit_code=0, *,
                   mutate_receipt=False, mutate_source=False, extra="", sentinel=None,
                   extra_args=()):
        result, _ = run("work-log", [
            "--work-id", wid,
            "--pathway", "release",
            "--kind", "release-provider-action",
            "--gate", f"release-{recommendation}",
            "--evidence", str(receipt),
            "--result", "pass",
            "--proof-type", "executed",
            "--project", str(proj),
            "--recommendation-id", recommendation,
            "--verify-cmd", verifier(
                source, receipt, action, exit_code,
                mutate_receipt=mutate_receipt, mutate_source=mutate_source,
                extra=extra, sentinel=sentinel, extra_args=extra_args),
        ])
        return next(record for record in result.get("records", [])
                    if record.get("source") == "operating-layer proof registry")

    # A failed verifier cannot burn the matching ticket.
    failed_source = verifier_source("failed-action")
    failed_receipt = authorization("failed-action", failed_source)
    failed_issue = issue(failed_receipt, "approve failed action fixture")
    failed_proof = log_action(
        failed_receipt, "REC-provider-failed", failed_source, exit_code=7,
    )
    events = [json.loads(line) for line in approvals_path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    check(failed_proof.get("release_approval_verified") is False
          and not any(event.get("event") == "consumed"
                      and event.get("subject_digest") == failed_issue.get("subject_digest")
                      for event in events),
          "failed provider verifier leaves its ticket unused")

    # A verifier that changes the authorization cannot burn its matching ticket.
    mutated_source = verifier_source("mutated-action")
    mutated_receipt = authorization("mutated-action", mutated_source)
    mutated_issue = issue(mutated_receipt, "approve snapshot mutation fixture")
    mutated_proof = log_action(
        mutated_receipt, "REC-provider-mutated", mutated_source,
        mutate_receipt=True,
    )
    events = [json.loads(line) for line in approvals_path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    check(mutated_proof.get("release_snapshot_stable") is False
          and mutated_proof.get("release_approval_verified") is False
          and not any(event.get("event") == "consumed"
                      and event.get("subject_digest") == mutated_issue.get("subject_digest")
                      for event in events),
          "provider-action authorization mutation leaves its ticket unused")

    # A ticket for different bytes cannot authorize this evidence.
    mismatch_source = verifier_source("ticket-mismatch")
    other_source = verifier_source("ticket-mismatch-other")
    mismatch_receipt = authorization("ticket-mismatch", mismatch_source)
    other_receipt = authorization(
        "ticket-mismatch-other", other_source, "promote-public-stage")
    mismatch_issue = issue(other_receipt, "approve other authorization bytes")
    mismatch_proof = log_action(
        mismatch_receipt, "REC-provider-ticket-mismatch", mismatch_source,
    )
    events = [json.loads(line) for line in approvals_path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    check(mismatch_proof.get("release_approval_verified") is False
          and not any(event.get("event") == "consumed"
                      and event.get("subject_digest") == mismatch_issue.get("subject_digest")
                      for event in events),
          "provider action refuses a ticket bound to different authorization bytes")

    # Extra final-release claims fail closed and leave the exact ticket live.
    extra_source = verifier_source("extra-marker")
    extra_receipt = authorization("extra-marker", extra_source)
    extra_issue = issue(extra_receipt, "approve extra marker fixture")
    extra_proof = log_action(
        extra_receipt, "REC-provider-extra-marker", extra_source,
        extra="RELEASE_DECISION=RELEASE\n",
    )
    events = [json.loads(line) for line in approvals_path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    check(extra_proof.get("release_approval_verified") is False
          and not any(event.get("event") == "consumed"
                      and event.get("subject_digest") == extra_issue.get("subject_digest")
                      for event in events),
          "extra final-release marker cannot consume a provider-action ticket")

    def ticket_unused(issue_result):
        events = [
            json.loads(line)
            for line in approvals_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return not any(
            event.get("event") == "consumed"
            and event.get("subject_digest") == issue_result.get("subject_digest")
            for event in events
        )

    # The reviewed authorization must name one canonical source digest. Missing, malformed,
    # or multi-source values fail before any operator-controlled verifier code runs.
    malformed_cases = [
        ("missing-source-binding", True, None),
        ("short-source-binding", False, "abc123"),
        ("uppercase-source-binding", False, "A" * 64),
        ("multiple-source-bindings", False, ["a" * 64, "b" * 64]),
    ]
    for name, omit_field, field_value in malformed_cases:
        malformed_source = verifier_source(name)
        malformed_receipt = authorization(
            name,
            malformed_source,
            verifier_field=field_value,
            omit_verifier_field=omit_field,
        )
        malformed_issue = issue(malformed_receipt, f"approve {name} fixture")
        sentinel = ROOT / "out" / f"{name}-executed"
        malformed_proof = log_action(
            malformed_receipt,
            f"REC-provider-{name}",
            malformed_source,
            sentinel=sentinel,
        )
        check(
            malformed_proof.get("release_approval_verified") is False
            and malformed_proof.get("exit_code") is None
            and not sentinel.exists()
            and ticket_unused(malformed_issue),
            f"provider action rejects {name} before verifier execution",
        )

    # A generated wrapper cannot ride a ticket that approved another verifier, even when it
    # emits the exact four markers. The unapproved source must not execute at all.
    reviewed_source = verifier_source("reviewed-source")
    generated_source = verifier_source("generated-wrapper", "# generated wrapper\n")
    generated_receipt = authorization("generated-wrapper", reviewed_source)
    generated_issue = issue(generated_receipt, "approve only the reviewed verifier source")
    generated_sentinel = ROOT / "out" / "generated-wrapper-executed"
    generated_proof = log_action(
        generated_receipt,
        "REC-provider-generated-wrapper",
        generated_source,
        sentinel=generated_sentinel,
    )
    check(
        generated_proof.get("release_approval_verified") is False
        and generated_proof.get("exit_code") is None
        and not generated_sentinel.exists()
        and ticket_unused(generated_issue),
        "provider action rejects an arbitrary generated verifier before execution",
    )

    # A second existing Python source cannot ride as a command argument. Non-Python data paths
    # remain valid, but executable Python source is a closed one-file contract.
    one_source = verifier_source("one-authorized-source")
    extra_python_source = verifier_source("unapproved-extra-source")
    extra_source_receipt = authorization("extra-python-source", one_source)
    extra_source_issue = issue(
        extra_source_receipt, "approve one verifier source only")
    extra_source_sentinel = ROOT / "out" / "extra-source-command-executed"
    extra_source_proof = log_action(
        extra_source_receipt,
        "REC-provider-extra-python-source",
        one_source,
        sentinel=extra_source_sentinel,
        extra_args=(extra_python_source,),
    )
    check(
        extra_source_proof.get("release_approval_verified") is False
        and extra_source_proof.get("exit_code") is None
        and not extra_source_sentinel.exists()
        and ticket_unused(extra_source_issue),
        "provider action rejects an extra existing Python source before execution",
    )

    # An existing positional path may itself contain '='. Checking only the text after '=' lets
    # that second source hide from an option-value-only scan.
    equals_python_source = verifier_source("positional-extra=source")
    equals_source_receipt = authorization("equals-python-source", one_source)
    equals_source_issue = issue(
        equals_source_receipt, "approve no positional Python source")
    equals_source_sentinel = ROOT / "out" / "equals-source-command-executed"
    equals_source_proof = log_action(
        equals_source_receipt,
        "REC-provider-equals-python-source",
        one_source,
        sentinel=equals_source_sentinel,
        extra_args=(equals_python_source,),
    )
    check(
        equals_source_proof.get("release_approval_verified") is False
        and equals_source_proof.get("exit_code") is None
        and not equals_source_sentinel.exists()
        and ticket_unused(equals_source_issue),
        "provider action rejects a positional Python source whose path contains equals",
    )

    # The approved source cannot import unapproved Python beside itself. Cover direct modules,
    # local packages, from-imports, and both common dynamic import forms.
    local_import_cases = [
        (
            "direct-local-import",
            "import direct_local_helper\n",
            [("direct_local_helper.py", "VALUE = 1\n")],
        ),
        (
            "local-package-import",
            "import local_package.submodule\n",
            [
                ("local_package/__init__.py", "VALUE = 1\n"),
                ("local_package/submodule.py", "VALUE = 2\n"),
            ],
        ),
        (
            "local-from-import",
            "from local_from_helper import VALUE\n",
            [("local_from_helper.py", "VALUE = 1\n")],
        ),
        (
            "local-importlib-import",
            "import importlib\nimportlib.import_module('local_dynamic_helper')\n",
            [("local_dynamic_helper.py", "VALUE = 1\n")],
        ),
        (
            "local-dunder-import",
            "__import__('local_dunder_helper')\n",
            [("local_dunder_helper.py", "VALUE = 1\n")],
        ),
    ]
    for name, prefix, local_files in local_import_cases:
        for relative_path, content in local_files:
            write(f"out/test-verifiers/{relative_path}", content)
        importing_source = verifier_source(name, prefix)
        importing_receipt = authorization(name, importing_source)
        importing_issue = issue(importing_receipt, f"approve one source for {name}")
        importing_sentinel = ROOT / "out" / f"{name}-executed"
        importing_proof = log_action(
            importing_receipt,
            f"REC-provider-{name}",
            importing_source,
            sentinel=importing_sentinel,
        )
        check(
            importing_proof.get("release_approval_verified") is False
            and importing_proof.get("exit_code") is None
            and not importing_sentinel.exists()
            and ticket_unused(importing_issue),
            f"provider action rejects {name} before verifier execution",
        )

    # Defense in depth: even if a caller bypassed the provider-action AST decision, the isolated
    # snapshot loader itself does not make the verifier directory importable.
    write("out/test-verifiers/isolation_helper.py", "VALUE = 1\n")
    isolation_source = verifier_source(
        "isolated-loader", "import isolation_helper\n")
    isolation_receipt = authorization("isolated-loader", isolation_source)
    isolation_sentinel = ROOT / "out" / "isolated-loader-executed"
    isolation_binding = opl.parse_generic_verifier_command(
        verifier(
            isolation_source,
            isolation_receipt,
            sentinel=isolation_sentinel,
        ),
        str(proj),
    )
    isolation_exit, _, _, _ = opl.run_generic_verifier_snapshot(
        isolation_binding, str(proj), isolate_source_dir=True)
    check(
        isolation_exit != 0 and not isolation_sentinel.exists(),
        "provider-action isolated loader leaves the verifier directory off sys.path",
    )

    # `-I` still imports global or virtual-environment site startup files. Provider actions need
    # `-S` too, so a writable `.pth` file cannot run before the approved source snapshot.
    startup_source = verifier_source("site-startup-guard")
    startup_receipt = authorization("site-startup-guard", startup_source)
    startup_binding = opl.parse_generic_verifier_command(
        verifier(startup_source, startup_receipt), str(proj))
    check(
        startup_binding.get("isolated_argv", [])[1:4] == ["-I", "-B", "-S"],
        "provider-action isolated argv disables Python site startup",
    )
    fake_venv = ROOT / "out" / "writable-site-python"
    (fake_venv / "bin").mkdir(parents=True)
    fake_python = fake_venv / "bin" / "python"
    os.symlink(sys.executable, fake_python)
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    (fake_venv / "pyvenv.cfg").write_text(
        f"home = {Path(sys.executable).parent}\n"
        "include-system-site-packages = false\n"
        f"version = {sys.version_info.major}.{sys.version_info.minor}."
        f"{sys.version_info.micro}\n",
        encoding="utf-8",
    )
    writable_site = fake_venv / "lib" / f"python{python_version}" / "site-packages"
    writable_site.mkdir(parents=True)
    startup_marker = fake_venv / "site-startup-ran"
    (writable_site / "unapproved-startup.pth").write_text(
        f"import pathlib; pathlib.Path({str(startup_marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )
    startup_argv = list(startup_binding["isolated_argv"])
    startup_argv[0] = str(fake_python)
    startup_proc = subprocess.run(
        startup_argv,
        cwd=str(proj),
        input=startup_binding["source_bytes"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        env={
            key: value for key, value in os.environ.items()
            if not key.upper().startswith("PYTHON") and key != "__PYVENV_LAUNCHER__"
        },
    )
    check(
        startup_proc.returncode == 0 and not startup_marker.exists(),
        "provider-action interpreter cannot run writable site startup code",
    )

    # Execute the resolved trusted interpreter, but preserve the spelling that the approved
    # command supplied. A verifier may bind historical commands built from ``sys.executable``;
    # resolving a Homebrew symlink inside the isolated child must not change that command.
    lexical_python = ROOT / "out" / "lexical-python"
    os.symlink(sys.executable, lexical_python)
    lexical_source = write(
        "out/test-verifiers/lexical-interpreter.py",
        "import sys\nsys.stdout.write(sys.executable + '\\n')\n",
    )
    lexical_binding = opl.parse_generic_verifier_command(
        f"{shlex.quote(str(lexical_python))} {shlex.quote(str(lexical_source))}",
        str(proj),
    )
    lexical_exit, _, _, lexical_stdout = opl.run_generic_verifier_snapshot(
        lexical_binding, str(proj), isolate_source_dir=True)
    check(
        lexical_exit == 0
        and lexical_stdout.strip() == str(lexical_python)
        and lexical_binding["isolated_argv"][0] == str(Path(sys.executable).resolve()),
        "provider-action snapshot preserves the trusted lexical interpreter spelling",
    )

    # Changing the reviewed source after ticket issue changes the captured digest. It must fail
    # before the changed source can run.
    changed_source = verifier_source("changed-after-approval")
    changed_receipt = authorization("changed-after-approval", changed_source)
    changed_issue = issue(changed_receipt, "approve original verifier source bytes")
    changed_source.write_text("# changed after approval\n" + verifier_body, encoding="utf-8")
    changed_sentinel = ROOT / "out" / "changed-source-executed"
    changed_proof = log_action(
        changed_receipt,
        "REC-provider-changed-source",
        changed_source,
        sentinel=changed_sentinel,
    )
    check(
        changed_proof.get("release_approval_verified") is False
        and changed_proof.get("exit_code") is None
        and not changed_sentinel.exists()
        and ticket_unused(changed_issue),
        "provider action rejects verifier source changed after approval",
    )

    # A source that changes its own on-disk bytes during snapshot execution still cannot consume
    # the ticket, even though the captured bytes matched at process start.
    self_mutating_source = verifier_source("self-mutating-source")
    self_mutating_receipt = authorization("self-mutating-source", self_mutating_source)
    self_mutating_issue = issue(
        self_mutating_receipt, "approve stable verifier source snapshot")
    self_mutating_proof = log_action(
        self_mutating_receipt,
        "REC-provider-self-mutating-source",
        self_mutating_source,
        mutate_source=True,
    )
    check(
        self_mutating_proof.get("release_approval_verified") is False
        and self_mutating_proof.get("verifier_snapshot_stable") is False
        and ticket_unused(self_mutating_issue),
        "provider action rejects verifier source changed during execution",
    )

    # The exact executed action consumes once and records the join fields.
    approved_source = verifier_source("approved-action")
    approved_receipt = authorization("approved-action", approved_source)
    approved_issue = issue(approved_receipt, "approve exact canary deploy action")
    approved_proof = log_action(
        approved_receipt, "REC-provider-approved", approved_source,
    )
    check(approved_proof.get("release_provider_action_verified") is True
          and approved_proof.get("release_provider_action") == "deploy-canary"
          and approved_proof.get("verifier_source_sha256")
          == approved_proof.get("release_receipt", {}).get("verifier_source_sha256")
          and approved_proof.get("release_receipt_sha256") == opl.sha256_file(approved_receipt)
          and approved_proof.get("release_approval_verified") is True
          and approved_proof.get("release_approval_digest") == approved_issue.get("subject_digest")
          and bool(approved_proof.get("release_approval_consumed_id")),
          "approved provider action records the exact digest and approval consumption join")
    check(approved_proof.get("release_credit_scope") == ""
          and approved_proof.get("release_verifier_markers") == {}
          and approved_proof.get("release_verifier_bound") is False
          and not opl.proof_is_verified(approved_proof),
          "provider-action proof cannot impersonate or credit a final release")

    status, _ = run("work-status", ["--work-id", wid])
    check({entry["pathway"]: entry["status"]
           for entry in status["summary"]["itinerary"]}["release"] == "required",
          "approved provider action leaves final release coverage open")

    # Reusing the consumed ticket under another proof id fails, with no second consumption.
    replay_proof = log_action(
        approved_receipt, "REC-provider-replay", approved_source,
    )
    events = [json.loads(line) for line in approvals_path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    consumptions = [
        event for event in events
        if event.get("event") == "consumed"
        and event.get("subject_digest") == approved_issue.get("subject_digest")
    ]
    check(replay_proof.get("release_approval_verified") is False
          and replay_proof.get("release_approval_error") == "approval_consumed"
          and len(consumptions) == 1,
          "provider-action ticket replay cannot authorize a second proof")
    persisted = [json.loads(line) for line in proofs_path.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    check(any(proof.get("proof_id") == approved_proof.get("proof_id") for proof in persisted),
          "approved provider-action proof persists for the downstream release join")


def test_approval_authority_survives_review_findings():
    """Regressions for the 2026-08-16 adversarial review. Each check fails on the pre-fix code:
    a long project slug redacted the ledger join key, a spent ticket locked the subject out
    forever, a widened window was honored, forged corroboration credited, and proof-add could
    never credit release."""
    opl = load_cli("approval_findings")
    reset()
    # A slug long enough that "work-cover:<work_id>:<pathway>" crosses the 64-char entropy
    # pattern — this is the exact shape that silently redacted the consumption key.
    proj = ROOT / "projects" / "pathway-operating-layer-approval-regression"
    proj.mkdir(parents=True, exist_ok=True)
    approvals_path = ROOT / "out/operator-intelligence/approvals.ndjson"

    data, _ = run("work-start", ["--project", str(proj),
                                 "--goal", "production secure long slug waiver regression",
                                 "--tier", "production-secure"])
    wid = data["work_id"]
    consumer = f"work-cover:{wid}:observability"
    check(len(consumer) >= 64,
          f"the fixture consumer key is long enough to trip the entropy redactor ({len(consumer)})")
    check(opl.redact_obj({"consumed_by": consumer})["consumed_by"] == consumer,
          "the ledger join key survives redaction verbatim")

    reason = "runtime monitoring is live and does not match the runtime receipt contract"
    run("approval-issue", ["--kind", "production-secure-waiver", "--work-id", wid,
                           "--pathway", "observability", "--reason", reason])
    covered, _ = run("work-cover", ["--work-id", wid, "--pathway", "observability", "--na",
                                    "--reason", reason])
    entry = next(e for e in covered["records"][0]["itinerary"] if e["pathway"] == "observability")
    check(entry["status"] == "na" and bool(entry.get("waiver_digest")),
          "a long-work-id waiver consumes and stamps its row")
    status, _ = run("work-status", ["--work-id", wid])
    check({e["pathway"]: e["status"]
           for e in status["summary"]["itinerary"]}["observability"] == "na",
          "a long-work-id waived row stays corroborated through status recomputation")

    ledger = [json.loads(line) for line in approvals_path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    issued_event = next(e for e in ledger if e.get("event") == "issued")
    check(bool(issued_event.get("ticket_id")) and bool(issued_event.get("issued_by")),
          "an issued ticket records its own id and an attributable issuer")

    # A spent ticket must not lock the subject out: a deliberate re-issue is consumable again.
    reissued, _ = run("approval-issue", ["--kind", "production-secure-waiver", "--work-id", wid,
                                         "--pathway", "observability", "--reason", reason])
    check(bool(reissued.get("subject_digest")), "the same subject can be deliberately re-issued")
    recovered, _ = run("work-cover", ["--work-id", wid, "--pathway", "observability", "--na",
                                      "--reason", reason])
    check(bool(recovered.get("records")),
          "a re-issued ticket is consumable after an earlier ticket was spent")

    # A hand-widened validity window in the ledger is not honored.
    run("approval-issue", ["--kind", "production-secure-waiver", "--work-id", wid,
                           "--pathway", "techdebt", "--reason", "debt paid in the same change"])
    ledger = [json.loads(line) for line in approvals_path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    for event in ledger:
        if (event.get("event") == "issued"
                and (event.get("subject") or {}).get("pathway") == "techdebt"):
            event["expires_at"] = "2036-01-01T00:00:00Z"
    approvals_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in ledger), encoding="utf-8")
    widened, _ = run("work-cover", ["--work-id", wid, "--pathway", "techdebt", "--na",
                                    "--reason", "debt paid in the same change"])
    check("work-cover-production-secure-na-blocked" in ids(widened),
          "a ledger window widened beyond the authority's TTL is refused")

    # A secret-shaped reason is refused at issue time rather than dying as a mismatch later.
    unstorable, _ = run("approval-issue", ["--kind", "production-secure-waiver", "--work-id", wid,
                                           "--pathway", "docs", "--reason", "token: abcdefghijkl"])
    check("approval-issue-reason-not-storable" in ids(unstorable),
          "a reason the redactor would rewrite is refused at issue time")

    # Forged corroboration: approval fields on a proof row with no ledger evidence never credit.
    forged = {
        "pathway": "release", "result": "pass", "verifier_strength": "executed",
        "exit_code": 0, "trivial_verifier": False, "canary_mutant_failed": True,
        "release_snapshot_stable": True, "release_snapshot_errors": [],
        "template_check": {"valid": True}, "release_credit_scope": "production",
        "release_receipt_errors": [], "release_verifier_errors": [],
        "release_verifier_bound": True,
        "release_artifact_sha256": {f: "a" * 64 for f in opl.RELEASE_RECEIPT_ARTIFACT_FIELDS},
        "release_approval_verified": True, "release_approval_digest": "b" * 64,
        "release_approval_consumed_id": "AC-forged", "proof_id": "P-forged",
        "work_id": wid, "project": proj.name, "release_receipt_sha256": "c" * 64,
    }
    check(opl.proof_is_verified(forged) and not opl.proof_credits_pathway(forged, []),
          "a forged release approval passes the verifier gate but never credits")
    check(not opl.proved_pathways_from_proofs(wid, [forged], []),
          "an uncorroborated release proof stays out of the proved map")


def test_design_findings_route_to_design_pathway():
    """design-guard ids must reach the design pathway, not quality/implementation.

    Before the "ds-" prefix existed, pathway_for_finding fell through to keyword
    matching and mis-filed four of nine: "regression" and "coverage" hit quality
    first, so a missing visual-regression suite was filed as a testing problem.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("opl_design_routing", str(CLI))
    ol = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ol)

    check(ol.GUARD_PREFIX_PATHWAY.get("ds-") == "design",
          "GUARD_PREFIX_PATHWAY maps the ds- prefix to design")
    for fid in ("ds-raw-values", "ds-primitive-misuse", "ds-no-tokens",
                "ds-dtcg-nonconformant", "ds-no-a11y", "ds-no-stories",
                "ds-no-visual-regression", "ds-low-story-coverage",
                "ds-no-api-stability"):
        got = ol.pathway_for_finding({"id": fid, "message": fid.replace("-", " ")})
        check(got == "design", f"{fid} routes to design (got {got})")


def test_design_gate_is_derived_from_repo_not_goal_wording():
    """A repo either renders an interface or it does not.

    Design used to enter an itinerary only when the goal sentence happened to say
    "ui"/"screen"/"page", so a live Next.js app whose goal read "ship the affiliate
    portal" closed having never passed a design gate.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("opl_design_gate", str(CLI))
    ol = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ol)

    ui_repo = ROOT / "ui-repo" / "app"
    ui_repo.mkdir(parents=True)
    (ui_repo / "page.tsx").write_text("export default function P(){return null}\n")

    api_repo = ROOT / "api-repo" / "src"
    api_repo.mkdir(parents=True)
    (api_repo / "main.py").write_text("print('no interface here')\n")

    # Harvested third-party code is somebody else's interface, not ours to gate.
    vendored = ROOT / "api-repo" / "templates" / "someone-elses-app"
    vendored.mkdir(parents=True)
    (vendored / "page.tsx").write_text("export default function P(){return null}\n")

    check(ol.repo_has_ui(str(ROOT / "ui-repo")) is True,
          "repo_has_ui detects a repo containing .tsx components")
    check(ol.repo_has_ui(str(ROOT / "api-repo")) is False,
          "repo_has_ui ignores .tsx living under templates/ (harvested third-party)")
    check(ol.repo_has_ui("") is False, "repo_has_ui is False for an empty path")
    check(ol.repo_has_ui(str(ROOT / "does-not-exist")) is False,
          "repo_has_ui is False for a missing directory")

    # The goal sentence deliberately avoids every design keyword.
    goal = "ship the affiliate portal"
    check(not re.search(ol.PATHWAY_KEYWORD_GATES["design"], goal),
          "the test goal genuinely misses the design keyword gate")

    contract = ol.outcome_contract(goal=goal, project_path=str(ROOT / "ui-repo"),
                                   project_name="ui-repo")
    itinerary = ol.compute_itinerary(contract["tier"], goal,
                                     contract["outcome_profile"],
                                     contract["risk_overlays"])
    names = [e["pathway"] if isinstance(e, dict) else e for e in itinerary]
    check("design" in names,
          f"a UI repo gets design in its itinerary without design wording (got {names})")

    api_contract = ol.outcome_contract(goal=goal, project_path=str(ROOT / "api-repo"),
                                       project_name="api-repo")
    api_names = [e["pathway"] if isinstance(e, dict) else e
                 for e in ol.compute_itinerary(api_contract["tier"], goal,
                                               api_contract["outcome_profile"],
                                               api_contract["risk_overlays"])]
    check("design" not in api_names,
          f"a non-UI repo is not burdened with a design gate (got {api_names})")

    # The profile dicts are module-level constants shared across every call.
    for profile in ol.OUTCOME_PROFILES:
        check("design" not in profile.get("required_pathways", []) or
              profile["id"] != "customer-field-review",
              "outcome_contract did not mutate the shared OUTCOME_PROFILES constant")



def main():
    tests = [
        test_design_findings_route_to_design_pathway,
        test_design_gate_is_derived_from_repo_not_goal_wording,
        test_resolve_project_dir_nesting_and_unverified_proof_loudness,
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
        test_pathway_metric_reuses_generic_verifier_binding,
        test_pathway_audit_is_read_only_explainable_and_below_target_is_not_an_error,
        test_proof_registry_and_proved_metric,
        test_project_scoping_no_substring_bleed,
        test_pathway_execution_profile_invariants,
        test_itinerary_coverage_guarantee,
        test_approval_issue_guard_blocks_agent_shell_issuance,
        test_approval_issue_guard_allows_non_issuance_text_and_fail_open_inputs,
        test_approval_issue_guard_installer_uses_one_canonical_source,
        test_approval_issue_guard_repeatable_verifier,
        test_approval_ledger_strict_reader_and_authority_refusal_exit_codes,
        test_approval_authority_single_use_waiver_and_release_credit,
        test_production_secure_closed_view_rechecks_current_readiness,
        test_live_closed_view_reopens_when_release_proof_is_missing,
        test_approval_invalidation_revokes_exact_ticket_credit,
        test_release_provider_action_consumes_approval_without_release_credit,
        test_approval_authority_survives_review_findings,
        test_proof_add_flips_itinerary_coverage,
        test_proof_add_resolves_bare_project_name_and_flags_invalid_cwd,
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
        test_generic_python_verifier_source_freshness_reopens_pathway,
        test_generic_python_verifier_binds_symlinked_ancestor_target,
        test_generic_python_verifier_executes_exact_source_snapshot,
        test_generic_python_verifier_isolates_python_startup_environment,
        test_verifier_receipt_canary_mutant_catches_noop_verifier,
        test_redact_obj_exempts_only_real_sha256_digests,
        test_redaction_covers_bearer_and_provider_prefixed_credentials,
        test_release_receipt_distinguishes_preview_production_rollback_and_send,
        test_release_hold_carries_constraints_without_credit_or_repeat,
        test_release_proof_rejects_mid_verification_evidence_mutation,
        test_observability_pre_runtime_hold_carries_without_credit_or_repeat,
        test_observability_runtime_receipt_completeness_binding_and_replay_guards,
        test_observability_proof_rejects_verifier_that_ignores_one_bound_artifact,
        test_observability_proof_rejects_stateful_invocation_counter_verifier,
        test_observability_proof_revalidates_receipt_freshness_after_canaries,
        test_observability_proof_rejects_mid_verification_artifact_mutation,
        test_verifier_templates_reject_hollow_artifacts_and_accept_complete_contracts,
        test_phase1_g1_verifier_rejects_ambiguous_receipts,
        test_audit_proof_integrity_uses_active_outcomes_and_reports_history,
        test_canary_mutant_is_symlink_safe,
        test_canary_explicit_target_rejects_outside_and_unchanged_files,
        test_canary_mutant_resolves_repo_root_from_subdir,
        test_canary_selects_relevant_target_in_dirty_registered_checkout,
        test_canary_run_guard_skips_trivial_and_slow_verifiers,
        test_proof_canary_observability_report,
        test_observability_contract_loader_fails_closed_and_gates_schema,
        test_cohens_kappa_inter_rater_agreement,
        test_fleiss_kappa_multi_rater_agreement,
        test_kappa_reliability_thresholds,
        test_jury_collapses_same_family_votes,
        test_position_swap_and_rubric_fingerprint,
        test_pathway_evaluate_records_independent_verdicts_and_precision,
        test_recommender_engages_findings_over_foundation_on_untracked_project,
        test_learning_dampener_never_suppresses_a_pathway_with_live_findings,
        test_pathway_prompt_never_retiers_an_existing_outcome_via_work_start,
        test_artifact_filename_dates_use_local_day_not_utc,
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
