#!/usr/bin/env python3
"""
operating-layer.py - consolidated operating intelligence above the pathway suite.

This tool is intentionally local-first and read-only for product/client repos. It
writes only to a central output root, defaulting to ~/Projects/memory-vault. The
goal is to make the environment self-aware: logs, tools, projects, evidence,
AI/agent readiness, and client/workspace boundaries.
"""
import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEFAULT_CLAUDE_HOME = Path("/Users/alexhale/.claude")
DEFAULT_CODEX_HOME = Path("/Users/alexhale/.codex")
DEFAULT_PROJECTS_ROOT = Path("/Users/alexhale/Projects")
DEFAULT_OUTPUT_ROOT = Path("/Users/alexhale/Projects/memory-vault")
RENDERER = DEFAULT_CLAUDE_HOME / "scripts" / "operator-md-to-html.py"

PRUNE_DIRS = {
    ".git",
    "node_modules",
    ".next",
    "dist",
    "build",
    ".cache",
    ".pytest_cache",
    ".venv",
    "venv",
    "__pycache__",
    "vendor",
    "_archive",
    "coverage",
}
MAX_TEXT_BYTES = 262_144
MAX_SCAN_FILES = 20_000
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|pwd)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\b[A-Za-z0-9_-]{64,}={0,2}\b"),
]
FALSE_PAUSE_RE = re.compile(
    r"ready to (?:proceed|implement)|would you like me to|shall i continue|do you want me to",
    re.I,
)
PROVIDER_DRIFT_RE = re.compile(
    r"model_not_found|not\s+found.*model|unknown model|invalid model|provider.*unavailable|quota|rate.?limit",
    re.I,
)
ARTIFACT_INGEST_FAIL_RE = re.compile(r"(?:ingest\s+)?http=(?!200\b)\d{3,6}|invalid_payload", re.I)
CLIENT_TOKENS = ("koho", "yehovah", "sfdph", "excerpa", "prettyfly", "consultops", "athena")
AI_PROJECT_HINTS = ("local-ai", "laik", "rainman", "sportsbook", "agent", "hermes", "llm", "ml", "open-generative-ai", "anti-ai")
EVIDENCE_DIRS = {
    ".runs": "run",
    "test-results": "test",
    "coverage": "coverage",
    ".promptfoo": "prompt-eval",
    "evals": "eval",
    "artifacts": "artifact",
    "screenshots": "screenshot",
    "playwright-report": "browser-test",
    "lhci": "lighthouse",
}
LEGACY_SKILL_HINTS = {"close-day", "pause-work", "_archive/jr-dev"}
AUTH_SENSITIVE_NAMES = {
    "figma",
    "slack",
    "sentry",
    "cloudflare",
    "apollo",
    "github",
    "gmail",
    "sharepoint",
    "teams",
}
HIGH_LEVERAGE_SKILLS = {
    "1pct",
    "karpathy",
    "research-stack",
    "planning-stack",
    "build-stack",
    "review-stack",
    "closeout-stack",
    "project-registry",
    "staged-review",
    "pfos-standard-protocol",
}
SEVERITY_WEIGHT = {"info": 1, "warn": 3, "critical": 5}
PATHWAY_ORDER = [
    "research",
    "govern",
    "data",
    "security",
    "release",
    "implementation",
    "quality",
    "observability",
    "techdebt",
    "design",
    "docs",
]
WORK_STALE_DAYS = 14
REVIEW_STALE_DAYS = 14  # a .planning/review/latest-findings.json older than this is not trusted as current

# Per-pathway Karpathy doctrine: the decision each pathway answers, what "good"
# looks like, the real artifact that proves it, and the smallest end-to-end move.
# Drives `pathway-next` recommendations. research + govern are foundation gates.
PATHWAY_DOCTRINE = {
    "research": {
        "title": "Research & Context Acquisition",
        "foundation": True,
        "decision": "What must we know for certain before a plan can be trusted?",
        "good": "A planning-ready dossier: every high-impact claim cited, every unknown classified blocker/warn/info.",
        "artifact": ".planning/<feature>/research/ dossier + VERIFICATION_REPORT.md",
        "move": "Run research in dossier mode against the single top open question; stop when claims stabilize.",
        "skill": "/research-stack --deep",
    },
    "govern": {
        "title": "Govern — decision & metric",
        "foundation": True,
        "decision": "What business outcome and falsifiable metric does this work move?",
        "good": "One decision recorded with a measurable target and a cost/risk note before any build.",
        "artifact": "govern ledger entry with metric + acceptance criteria",
        "move": "Pin the single metric this work must move and state the gate number before building.",
        "skill": "/planning-stack --deep",
    },
    "data": {
        "title": "Data — model & boundaries",
        "foundation": False,
        "decision": "Is the entity model, lineage, and data boundary correct and safe to build on?",
        "good": "Schema/migration verified against the real artifact (a row), no cross-client boundary ambiguity.",
        "artifact": "migration applied + verified DB row + clean data-boundary report",
        "move": "Resolve the highest-risk boundary/schema gap, prove it on one real record.",
        "skill": "/planning-stack --tech",
    },
    "security": {
        "title": "Security — trust boundaries",
        "foundation": False,
        "decision": "What can an untrusted actor reach, and is every secret and authz surface closed?",
        "good": "Threat surface enumerated; no exposed secret, no anon-read, no open SSRF/authz hole.",
        "artifact": "security review findings + proof the hole is closed in prod",
        "move": "Close the single highest-severity exposure and verify it against the live surface.",
        "skill": "/review-stack --audit",
    },
    "release": {
        "title": "Release — rollout & rollback",
        "foundation": False,
        "decision": "How does this ship safely and how do we undo it if it's wrong?",
        "good": "A rollout path with a flag/canary and a proven, reversible rollback.",
        "artifact": "deploy run + rollback rehearsal evidence",
        "move": "Define the flag/canary and rehearse the rollback before flipping it on.",
        "skill": "/ship",
    },
    "implementation": {
        "title": "Implementation — build one slice",
        "foundation": False,
        "decision": "What is the smallest slice that ships one thing end-to-end against the metric?",
        "good": "A runnable slice that moves the govern metric, verified on the user-visible artifact.",
        "artifact": "merged slice + served/deployed proof, not a unit return",
        "move": "Build the dumbest end-to-end version of the next slice, then measure it.",
        "skill": "/build-stack",
    },
    "quality": {
        "title": "Quality — verify & gate",
        "foundation": False,
        "decision": "What proves this is correct, and what gate stops regressions?",
        "good": "Golden paths covered with a falsifiable gate; second-model critic run before merge.",
        "artifact": "passing eval/test gate + regression corpus entry",
        "move": "Add the one test/eval that would have caught the last failure, wire it as a gate.",
        "skill": "/review-stack",
    },
    "observability": {
        "title": "Observability — see it in prod",
        "foundation": False,
        "decision": "Could we diagnose this at 3am from signals alone?",
        "good": "Critical journeys carry metrics/logs/traces with alerts and a runbook delta.",
        "artifact": "live metric/log/trace + alert wired to the failure mode",
        "move": "Instrument the one signal that exposes the current top failure; alert on it.",
        "skill": "/planning-stack --tech",
    },
    "techdebt": {
        "title": "Tech Debt — lifecycle risk",
        "foundation": False,
        "decision": "What dependency or duplication will cost most if left?",
        "good": "Highest-leverage debt deleted before abstraction; canonical roles stable.",
        "artifact": "tool-registry showing stable canonical roles / removed dead code",
        "move": "Delete or canonicalize the single highest-risk duplicated/ambiguous asset.",
        "skill": "/build-stack",
    },
    "design": {
        "title": "Design — UX & system",
        "foundation": False,
        "decision": "Does the interface serve the workflow and the design system?",
        "good": "Screens map to real workflows; tokens conform; a11y contracts met.",
        "artifact": "design-stack export + token-conformance pass",
        "move": "Fix the one screen/flow most off-workflow against the design tokens.",
        "skill": "/design-stack --refactor",
    },
    "docs": {
        "title": "Docs — onboarding & ADRs",
        "foundation": False,
        "decision": "What does the next operator need that isn't written down?",
        "good": "Onboarding gap closed; key decision captured as an ADR/runbook.",
        "artifact": "updated README/runbook/ADR matching reality",
        "move": "Write the one doc/ADR that removes a recurring question.",
        "skill": "/closeout-stack",
    },
}

# Keyword -> pathway routing for findings. First match wins, scanned in order.
FINDING_PATHWAY_KEYWORDS = [
    ("security", ["secret", "rls", "anon-read", "anon_read", "auth", "ssrf", "leak", "credential", "exposure", "vuln", "service_role", "service-role"]),
    ("observability", ["slo", "trace", "metric", "log", "observ", "ingest", "http=4", "http=5", "invalid_payload", "alert", "telemetry"]),
    ("quality", ["test", "eval", "coverage", "verify", "verification", "regress", "flake", "calibration", "false-positive", "false_positive"]),
    ("data", ["migration", "schema", "boundary", "lineage", "retention", "cross-client", "cross_client", "drift", "data-boundary"]),
    ("release", ["deploy", "release", "canary", "rollback", "rollout", "preview", "feature-flag", "feature_flag"]),
    ("techdebt", ["debt", "dependency", "duplicate", "duplicated", "dead-code", "dead_code", "stale", "ambiguous", "canonical", "lockfile", "upgrade"]),
    ("design", ["design", "ui", "ux", "token", "a11y", "accessib", "layout", "component"]),
    ("docs", ["doc", "readme", "adr", "runbook", "onboarding"]),
    ("govern", ["decision", "objective", "metric", "cost", "budget", "next_action", "next-action", "ledger", "portfolio"]),
]

# Guard-script finding-id prefixes -> pathway (deterministic; review-stack guards).
GUARD_PREFIX_PATHWAY = {
    "sec-": "security",
    "mig-": "data",
    "gov-": "govern",
    "rel-": "release",
    "impl-": "implementation",
    "q-": "quality",
    "obs-": "observability",
    "td-": "techdebt",
    "ff-": "research",
    "rs-": "research",
}

# Scan-workflow -> pathway fallback when no keyword matches.
FINDING_WORKFLOW_PATHWAY = {
    "tools": "techdebt",
    "ai-contract": "quality",
    "boundary": "data",
    "evidence": "quality",
    "portfolio": "govern",
    "intel": "observability",
    "agent-cards": "docs",
    "daily-work": "govern",
}


def utc_now():
    return datetime.now(timezone.utc)


def iso_now():
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value):
    if not value:
        return None
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(str(value)[: len(fmt)], fmt)
                break
            except Exception:
                dt = None
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_log_ts(line):
    m = re.search(r"\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)", line)
    return parse_ts(m.group(1)) if m else None


def redact(value):
    text = str(value)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def is_secret_like(text):
    return any(pattern.search(str(text)) for pattern in SECRET_PATTERNS)


def safe_read_text(path, max_bytes=MAX_TEXT_BYTES):
    try:
        with open(path, "rb") as fh:
            data = fh.read(max_bytes + 1)
        return data[:max_bytes].decode("utf-8", errors="replace")
    except Exception:
        return ""


def mkdir(path):
    Path(path).mkdir(parents=True, exist_ok=True)


def rel_to(path, root):
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except Exception:
        return str(path)


def mtime_iso(path):
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def line_evidence(path, line=None, snippet=None, source=None):
    ev = {"path": str(path)}
    if line:
        ev["line"] = line
    if snippet:
        ev["snippet"] = redact(snippet)[:500]
    if source:
        ev["source"] = source
    return ev


def finding(fid, workflow, severity, message, evidence=None, recommendation=None,
            static_or_runtime="static", confidence="medium"):
    return {
        "id": fid,
        "workflow": workflow,
        "severity": severity,
        "message": redact(message),
        "evidence": evidence or [],
        "recommendation": redact(recommendation or ""),
        "static_or_runtime": static_or_runtime,
        "confidence": confidence,
    }


def unique_findings(findings):
    seen = set()
    out = []
    for item in findings:
        key = (
            item.get("id"),
            item.get("workflow"),
            item.get("message"),
            json.dumps(item.get("evidence", [])[:2], sort_keys=True),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def append_records(path, records):
    mkdir(Path(path).parent)
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            line = json.dumps(redact_obj(rec), sort_keys=True)
            fh.write(line + "\n")


def write_json(path, obj):
    mkdir(Path(path).parent)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(redact_obj(obj), fh, indent=2, sort_keys=True)
        fh.write("\n")


def write_text(path, text):
    mkdir(Path(path).parent)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(redact(text))


def redact_obj(value):
    if isinstance(value, dict):
        generated_id_keys = {"work_id", "run_id", "measurement_id", "control_id", "evidence_id", "created_by_run_id", "resolved_by_run_id", "resolution_evidence_id"}
        return {k: (v if k in generated_id_keys else redact_obj(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_obj(v) for v in value]
    if isinstance(value, str):
        return redact(value)
    return value


def yaml_scalar(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = redact(str(value))
    if not text:
        return '""'
    if re.search(r"[:#\n\[\]\{\},]|^\s|\s$", text):
        return json.dumps(text)
    return text


def dump_yaml_records(path, records):
    mkdir(Path(path).parent)
    lines = []
    for rec in records:
        lines.append("-")
        for key, value in rec.items():
            if isinstance(value, list):
                lines.append(f"  {key}:")
                for item in value:
                    lines.append(f"    - {yaml_scalar(item)}")
            else:
                lines.append(f"  {key}: {yaml_scalar(value)}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def iter_files(root, names=None, suffixes=None, max_files=MAX_SCAN_FILES):
    root = Path(root)
    if not root.exists():
        return
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS and not d.startswith(".Trash")]
        for name in filenames:
            if names and name not in names:
                continue
            if suffixes and not any(name.endswith(s) for s in suffixes):
                continue
            count += 1
            if count > max_files:
                return
            yield Path(dirpath) / name


def iter_project_tree(root, max_entries=5000):
    """Bounded project walk that prunes dependency/build directories."""
    root = Path(root)
    if not root.exists():
        return
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        for dirname in list(dirnames):
            count += 1
            if count > max_entries:
                return
            yield Path(dirpath) / dirname, True
        for filename in filenames:
            count += 1
            if count > max_entries:
                return
            yield Path(dirpath) / filename, False


def iter_recent_lines(path, since=None, limit=5000):
    path = Path(path)
    if not path.exists() or not path.is_file():
        return []
    lines = safe_read_text(path, max_bytes=2_000_000).splitlines()
    out = []
    for idx, line in enumerate(lines[-limit:], max(1, len(lines) - limit + 1)):
        ts = parse_log_ts(line)
        if since and ts and ts < since:
            continue
        out.append((idx, line, ts))
    return out


def find_first_line(path, pattern):
    rx = re.compile(pattern, re.I)
    for i, line in enumerate(safe_read_text(path).splitlines(), 1):
        if rx.search(line):
            return i, line
    return None, None


class Paths:
    def __init__(self, args):
        self.claude_home = Path(args.claude_home).expanduser()
        self.codex_home = Path(args.codex_home).expanduser()
        self.projects_root = Path(args.projects_root).expanduser()
        self.output_root = Path(args.output_root).expanduser()
        self.operator_intel = self.output_root / "operator-intelligence"
        self.operator_artifacts = self.output_root / "operator-artifacts"
        self.agent_cards = self.operator_intel / "agent-capability-cards"
        self.findings_path = self.operator_intel / "findings.ndjson"
        self.tool_registry_path = self.operator_intel / "tool-registry.json"
        self.portfolio_path = self.operator_intel / "portfolio-registry.yaml"
        self.evidence_path = self.operator_intel / "evidence-registry.ndjson"
        self.improvement_queue_path = self.operator_intel / "improvement-queue.json"
        self.compare_path = self.operator_intel / "compare.json"
        self.history_dir = self.operator_intel / "history"
        self.work_items_path = self.operator_intel / "work-items.ndjson"
        self.pathway_runs_path = self.operator_intel / "pathway-runs.ndjson"
        self.pathway_measurements_path = self.operator_intel / "pathway-measurements.ndjson"
        self.controls_path = self.operator_intel / "controls.ndjson"
        self.daily_dashboard_path = self.operator_intel / "daily-work-dashboard.json"
        self.recommendations_path = self.operator_intel / "pathway-recommendations.ndjson"


def cutoff_from_args(args):
    return utc_now() - timedelta(days=args.since_days)


def write_findings(paths, findings):
    append_records(paths.findings_path, unique_findings(findings))


def read_ndjson(path):
    records = []
    p = Path(path)
    if not p.exists():
        return records
    for line in safe_read_text(p, max_bytes=5_000_000).splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    return records


def write_ndjson(path, records):
    append_records(path, records)


def sha_text(text, length=12):
    return hashlib.sha256(str(text).encode("utf-8", errors="replace")).hexdigest()[:length]


def short_hash(*parts, length=6):
    return sha_text("|".join(str(p) for p in parts), length=length)


def project_name_from_path(project_path):
    return safe_slug(Path(project_path).expanduser().resolve().name)


def stable_work_id(project_path, goal, now=None):
    day = (now or utc_now()).strftime("%Y%m%d")
    project_slug = project_name_from_path(project_path)
    goal_slug = safe_slug(goal)[:24] or "work"
    h = short_hash(Path(project_path).expanduser().resolve(), goal, day)
    return f"W-{day}-{project_slug}-{goal_slug}-{h}"


def evidence_id_for_path(path):
    p = Path(path).expanduser()
    basis = str(p)
    if p.exists() and p.is_file():
        try:
            basis += f"|{p.stat().st_mtime_ns}|{p.stat().st_size}|{safe_read_text(p, max_bytes=64_000)}"
        except Exception:
            pass
    return f"E-{sha_text(basis, 12)}"


def next_run_id(paths, work_id, pathway):
    runs = [r for r in read_ndjson(paths.pathway_runs_path) if r.get("work_id") == work_id and r.get("pathway") == pathway]
    return f"R-{work_id}-{safe_slug(pathway)}-{len(runs) + 1:03d}"


def measurement_id(run_id, gate):
    return f"M-{run_id}-{safe_slug(gate)[:40]}"


def control_id(source_pathway, risk, work_id):
    return f"C-{safe_slug(source_pathway)}-{safe_slug(risk)[:40]}-{short_hash(work_id, source_pathway, risk)}"


def upsert_by_key(path, records, key):
    existing = read_ndjson(path)
    by_key = {item.get(key): item for item in existing if item.get(key)}
    for record in records:
        by_key[record.get(key)] = record
    write_ndjson(path, list(by_key.values()))


def update_work_item(paths, work_id, **updates):
    items = read_ndjson(paths.work_items_path)
    found = False
    now = iso_now()
    for item in items:
        if item.get("work_id") == work_id:
            item.update(redact_obj(updates))
            item["updated_at"] = now
            found = True
            break
    if not found:
        item = {"work_id": work_id, "created_at": now, "updated_at": now, **redact_obj(updates)}
        items.append(item)
    write_ndjson(paths.work_items_path, items)
    return item


def finding_key(item):
    return f"{item.get('workflow', '')}:{item.get('id', '')}"


def first_int(text, default=1):
    m = re.search(r"\b(\d+)\b", str(text))
    return int(m.group(1)) if m else default


def finding_magnitude(item):
    return max(first_int(item.get("message", ""), 1), len(item.get("evidence", [])))


def latest_history_file(paths):
    if not paths.history_dir.exists():
        return None
    files = sorted(paths.history_dir.glob("*-findings.ndjson"))
    return files[-1] if files else None


def save_findings_snapshot(paths, findings):
    mkdir(paths.history_dir)
    stamp = utc_now().strftime("%Y%m%dT%H%M%S.%fZ")
    path = paths.history_dir / f"{stamp}-findings.ndjson"
    append_records(path, unique_findings(findings))
    return path


def compare_findings(old_findings, new_findings):
    old = {finding_key(f): f for f in unique_findings(old_findings)}
    new = {finding_key(f): f for f in unique_findings(new_findings)}
    old_keys = set(old)
    new_keys = set(new)
    added = [new[k] for k in sorted(new_keys - old_keys)]
    resolved = [old[k] for k in sorted(old_keys - new_keys)]
    worsened = []
    unchanged = []
    for key in sorted(old_keys & new_keys):
        old_item = old[key]
        new_item = new[key]
        old_severity = SEVERITY_WEIGHT.get(old_item.get("severity"), 1)
        new_severity = SEVERITY_WEIGHT.get(new_item.get("severity"), 1)
        if new_severity > old_severity or finding_magnitude(new_item) > finding_magnitude(old_item):
            worsened.append({
                "key": key,
                "old_count": finding_magnitude(old_item),
                "new_count": finding_magnitude(new_item),
                "old_severity": old_item.get("severity"),
                "new_severity": new_item.get("severity"),
                "finding": new_item,
            })
        else:
            unchanged.append(new_item)
    return {
        "generated_at": iso_now(),
        "added": added,
        "resolved": resolved,
        "unchanged": unchanged,
        "worsened": worsened,
        "summary": {
            "added": len(added),
            "resolved": len(resolved),
            "unchanged": len(unchanged),
            "worsened": len(worsened),
        },
    }


def trend_from_history(paths, current_findings=None):
    history = sorted(paths.history_dir.glob("*-findings.ndjson")) if paths.history_dir.exists() else []
    if len(history) >= 2:
        old_path, new_path = history[-2], history[-1]
        trend = compare_findings(read_ndjson(old_path), read_ndjson(new_path))
        trend["baseline"] = str(old_path)
        trend["candidate"] = str(new_path)
        return trend
    if len(history) == 1:
        candidate = current_findings if current_findings is not None else read_ndjson(paths.findings_path)
        trend = compare_findings(read_ndjson(history[-1]), candidate)
        trend["baseline"] = str(history[-1])
        trend["candidate"] = "current"
        return trend
    trend = compare_findings([], current_findings or read_ndjson(paths.findings_path))
    trend["baseline"] = None
    trend["candidate"] = "current"
    return trend


def improvement_components(item):
    fid = item.get("id", "")
    workflow = item.get("workflow", "")
    severity = SEVERITY_WEIGHT.get(item.get("severity"), 1)
    count = finding_magnitude(item)
    blast_radius = severity
    recurrence = min(5, 1 + count // 5)
    reversibility = 3
    unblock_value = 2
    fix_cost = 2

    if "artifact-ingest" in fid:
        blast_radius, unblock_value, reversibility, fix_cost = 5, 5, 4, 2
    elif "provider-model-drift" in fid:
        blast_radius, unblock_value, reversibility, fix_cost = 5, 4, 4, 2
    elif workflow == "evidence":
        blast_radius, unblock_value, reversibility, fix_cost = 4, 5, 4, 2
    elif workflow in {"ai-contract", "agent-cards"}:
        blast_radius, unblock_value, reversibility, fix_cost = 4, 4, 3, 3
    elif workflow == "tools":
        blast_radius, unblock_value, reversibility, fix_cost = 3, 3, 3, 3
    elif workflow in {"portfolio", "boundary"}:
        blast_radius, unblock_value, reversibility, fix_cost = 4, 4, 2, 4

    return {
        "blast_radius": blast_radius,
        "recurrence": recurrence,
        "reversibility": reversibility,
        "unblock_value": unblock_value,
        "fix_cost": fix_cost,
        "score": blast_radius + recurrence + reversibility + unblock_value - fix_cost,
    }


def improvement_move(item):
    fid = item.get("id", "")
    if "artifact-ingest" in fid:
        return {
            "move": "Make the evidence radar trustworthy by fixing or quarantining this ingest root cause.",
            "acceptance": "Rerun `operating-layer.py all --since-days 7`; this root-cause bucket drops materially or points to one precise owner.",
        }
    if "provider-model-drift" in fid:
        return {
            "move": "Run the provider/model doctor and remove unavailable model ids from configured routes.",
            "acceptance": "Local provider check shows no configured references to unavailable model ids.",
        }
    if fid == "tools-duplicate-skill-families":
        return {
            "move": "Resolve only the top ranked duplicate skill routing risks; leave low-risk plugin-cache copies alone.",
            "acceptance": "`tool-registry.json` shows stable canonical roles and fewer high-risk ambiguous entries.",
        }
    if fid.startswith("ai-contract") or fid.startswith("agent-cards"):
        return {
            "move": "Complete eval evidence, kill switch, allowed tools, and mutation policy for the highest-priority AI/agent systems.",
            "acceptance": "LAIK, Rainman/Sportsbook, and one active automation have complete readiness cards.",
        }
    if fid.startswith("evidence"):
        return {
            "move": "Refresh or demote stale evidence before using it as planning truth.",
            "acceptance": "The evidence registry distinguishes current proof from archival proof for the target project.",
        }
    if fid.startswith("portfolio"):
        return {
            "move": "Resolve canonical checkout ambiguity before allowing edits, deploys, or planning claims.",
            "acceptance": "The selected active project has one canonical checkout and stale alternates are labeled.",
        }
    if fid.startswith("boundary"):
        return {
            "move": "Add explicit client/data boundary declarations where path or project signals are ambiguous.",
            "acceptance": "`boundary --check-write PATH` can explain allow/block decisions without relying on name guesses.",
        }
    return {
        "move": "Reduce this finding with the smallest verified change that improves future operating decisions.",
        "acceptance": "The next report shows this finding resolved, reduced, or explicitly reclassified with evidence.",
    }


def build_improvement_queue(findings):
    items = []
    for item in unique_findings(findings):
        if item.get("severity") == "info" and item.get("id", "").endswith("-no-findings"):
            continue
        components = improvement_components(item)
        move = improvement_move(item)
        items.append({
            "rank": 0,
            "score": components["score"],
            "components": {k: v for k, v in components.items() if k != "score"},
            "id": item.get("id"),
            "workflow": item.get("workflow"),
            "severity": item.get("severity"),
            "move": move["move"],
            "why": item.get("message"),
            "acceptance": move["acceptance"],
            "source_finding": item,
        })
    items.sort(key=lambda r: (-r["score"], r["workflow"], r["id"]))
    for idx, item in enumerate(items, 1):
        item["rank"] = idx
    return items


def extract_field(line, name):
    m = re.search(rf"\b{name}\b\s*[:=]\s*[\"']?([^\"'\s,}}]+)", line, re.I)
    return m.group(1) if m else "unknown"


def artifact_ingest_cause(line):
    lower = line.lower()
    status = None
    m = re.search(r"http=(\d{3,6})", lower)
    if m:
        status = m.group(1)
    if status == "000000":
        return "http-000000", "transport/no-response"
    if "invalid_payload" in lower or status == "400":
        return "http-400-invalid-payload", "invalid payload"
    if status == "500":
        return "http-500", "server error"
    if status and status != "200":
        return f"http-{status}", f"http {status}"
    return "invalid-payload", "invalid payload"


def artifact_surface(path, paths):
    p = str(path)
    if str(paths.codex_home) in p:
        return "codex"
    if str(paths.claude_home) in p:
        return "claude"
    return "unknown"


def scan_intel(args, paths, write_outputs=True):
    since = cutoff_from_args(args)
    findings = []
    counts = Counter()

    ingest_logs = [
        paths.claude_home / "hooks" / "ingest.log",
        paths.codex_home / "hooks" / "ingest.log",
    ]
    ingest_groups = {}
    for log in ingest_logs:
        for line_no, line, ts in iter_recent_lines(log, since=since):
            if ARTIFACT_INGEST_FAIL_RE.search(line):
                cause, label = artifact_ingest_cause(line)
                surface = artifact_surface(log, paths)
                key = (surface, cause)
                group = ingest_groups.setdefault(key, {
                    "surface": surface,
                    "cause": cause,
                    "label": label,
                    "count": 0,
                    "first_seen": None,
                    "last_seen": None,
                    "cwds": Counter(),
                    "sessions": Counter(),
                    "evidence": [],
                })
                seen = ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None
                group["count"] += 1
                group["first_seen"] = min([v for v in (group["first_seen"], seen) if v], default=seen)
                group["last_seen"] = max([v for v in (group["last_seen"], seen) if v], default=seen)
                group["cwds"][extract_field(line, "cwd")] += 1
                group["sessions"][extract_field(line, "session")] += 1
                if len(group["evidence"]) < 8:
                    source = {
                        "surface": surface,
                        "cause": cause,
                        "cwd": extract_field(line, "cwd"),
                        "session": extract_field(line, "session"),
                        "seen": seen or "unknown",
                    }
                    group["evidence"].append(line_evidence(log, line_no, line, source=json.dumps(source, sort_keys=True)))
    for (surface, cause), group in sorted(ingest_groups.items()):
        count = group["count"]
        counts[f"artifact_ingest_{surface}_{cause}"] = count
        top_cwd = group["cwds"].most_common(1)[0][0] if group["cwds"] else "unknown"
        top_session = group["sessions"].most_common(1)[0][0] if group["sessions"] else "unknown"
        findings.append(finding(
            f"opintel-artifact-ingest-{cause}-{surface}",
            "intel",
            "warn",
            f"Artifact ingest root cause {cause} on {surface}: {count} events; cwd={top_cwd}; session={top_session}; first_seen={group['first_seen'] or 'unknown'}; last_seen={group['last_seen'] or 'unknown'}.",
            group["evidence"],
            "Fix the exact ingest surface/root cause or quarantine it before trusting historical run evidence completeness.",
            "runtime",
            "high",
        ))

    pause_log = paths.claude_home / "logs" / "1pct-violations.log"
    pause_hits = []
    for line_no, line, _ts in iter_recent_lines(pause_log, since=since):
        if FALSE_PAUSE_RE.search(line) or "ready-to" in line or "fresh-session" in line:
            pause_hits.append(line_evidence(pause_log, line_no, line))
    if pause_hits:
        counts["false_pause_hits"] = len(pause_hits)
        findings.append(finding(
            "opintel-false-pause-hits",
            "intel",
            "info",
            f"1pct violation log has {len(pause_hits)} recent false-pause or fresh-session flags.",
            pause_hits[:8],
            "Use the approved plan as execution authority; reserve questions for real forks or irreversible actions.",
            "static",
            "medium",
        ))

    provider_logs = [
        paths.claude_home / "sensory-memory" / "groq-failures.log",
        paths.claude_home / "logs" / "groq-failures.log",
    ]
    drift_hits = []
    for log in provider_logs:
        for line_no, line, _ts in iter_recent_lines(log, since=since):
            if PROVIDER_DRIFT_RE.search(line):
                drift_hits.append(line_evidence(log, line_no, line))
    if drift_hits:
        counts["provider_drift_hits"] = len(drift_hits)
        findings.append(finding(
            "opintel-provider-model-drift",
            "intel",
            "warn",
            f"Provider/model drift appears in {len(drift_hits)} recent log lines.",
            drift_hits[:8],
            "Run the provider/model doctor and update stale model ids or fallback routes.",
            "runtime",
            "high",
        ))

    session_index = paths.codex_home / "session_index.jsonl"
    session_counts = Counter()
    for _line_no, line, _ts in iter_recent_lines(session_index, since=since, limit=20000):
        try:
            obj = json.loads(line)
        except Exception:
            continue
        name = str(obj.get("thread_name", "")).lower()
        for term in ("review", "audit", "pathway", "workflow", "research", "agent", "rainman", "koho", "codex", "claude"):
            if term in name:
                session_counts[term] += 1
    if session_counts:
        counts.update({f"sessions_{k}": v for k, v in session_counts.items()})
        findings.append(finding(
            "opintel-session-patterns",
            "intel",
            "info",
            "Codex session index shows repeated review/audit/workflow activity in the selected window.",
            [line_evidence(session_index, source=json.dumps(dict(session_counts.most_common(10))))],
            "Use session pattern counts to prioritize workflow consolidation and evidence indexing.",
            "static",
            "medium",
        ))

    if not findings:
        findings.append(finding(
            "opintel-no-recent-findings",
            "intel",
            "info",
            "No recent operating-intelligence findings matched the configured local logs.",
            [line_evidence(paths.codex_home / "session_index.jsonl", source="No matching recent lines found.")],
            "Keep the scheduled scan; absence of local evidence is reported explicitly.",
            "static",
            "medium",
        ))

    if write_outputs:
        write_findings(paths, findings)
    return {"findings": findings, "counts": dict(counts)}


def parse_skill_name(path):
    text = safe_read_text(path, max_bytes=20_000)
    m = re.search(r"(?m)^name:\s*[\"']?([^\"'\n]+)", text)
    if m:
        return m.group(1).strip()
    return path.parent.name


def parse_skill_desc(path):
    text = safe_read_text(path, max_bytes=20_000)
    m = re.search(r"(?m)^description:\s*(.+)", text)
    return m.group(1).strip().strip('"')[:300] if m else ""


def auth_state_for_tool(name, path, text=""):
    blob = f"{name} {path} {text}".lower()
    if "not logged in" in blob or "unauthorized" in blob or "invalid token" in blob or "auth = \"missing\"" in blob:
        return "broken"
    if any(token in blob for token in AUTH_SENSITIVE_NAMES):
        return "unknown"
    return "not_required"


def source_root_for_tool(path, paths):
    p = str(path)
    if "/.codex/plugins/cache/" in p:
        return "plugin-cache"
    if "/.agents/skills/" in p:
        return "custom-agents"
    if "/.claude/skills/" in p:
        return "custom-claude"
    if "/.codex/skills/" in p:
        return "custom-codex"
    if p in {str(paths.codex_home / "config.toml"), str(paths.claude_home / "settings.json")}:
        return "local-config"
    return "other"


def canonical_skill_path(name, skill_paths, paths):
    def rank(path):
        p = str(path)
        if "_archive" in p or "backup" in p or "old" in p:
            archive_penalty = 10
        else:
            archive_penalty = 0
        root = source_root_for_tool(path, paths)
        root_rank = {
            "custom-agents": 0,
            "custom-claude": 1,
            "custom-codex": 2,
            "plugin-cache": 3,
            "other": 4,
        }.get(root, 5)
        return archive_penalty + root_rank, len(p), p

    return str(sorted(skill_paths, key=rank)[0])


def skill_copy_role(path, canonical_path, paths):
    p = str(path)
    if "_archive" in p or "backup" in p:
        return "backup-copy"
    root = source_root_for_tool(path, paths)
    if p == str(canonical_path):
        return "canonical-custom" if root.startswith("custom") else "canonical-plugin"
    if root == "plugin-cache":
        return "plugin-copy"
    if "old" in p or "stale" in p:
        return "stale-copy"
    return "custom-copy"


def skill_risk_rank(name, skill_paths, path, copy_role):
    risk = 0
    if len(skill_paths) > 1:
        risk += 35 + min(25, len(skill_paths) * 4)
    if name in HIGH_LEVERAGE_SKILLS:
        risk += 30
    if copy_role in {"plugin-copy", "backup-copy", "stale-copy"}:
        risk += 15
    if any(h in str(path) or h == name for h in LEGACY_SKILL_HINTS):
        risk += 15
    if copy_role.startswith("canonical"):
        risk = max(0, risk - 20)
    return min(100, risk)


def scan_tools(args, paths, write_outputs=True):
    findings = []
    records = []
    skill_roots = [
        paths.claude_home / "skills",
        paths.claude_home.parent / ".agents" / "skills",
        paths.codex_home / "skills",
        paths.codex_home / "plugins" / "cache",
    ]
    by_name = defaultdict(list)
    record_by_path = {}
    for root in skill_roots:
        if not root.exists():
            continue
        for skill in iter_files(root, names={"SKILL.md"}, max_files=5000):
            name = parse_skill_name(skill)
            desc = parse_skill_desc(skill)
            by_name[name].append(str(skill))
            status = "legacy" if any(h in str(skill) or h == name for h in LEGACY_SKILL_HINTS) else "present"
            rec = {
                "id": name,
                "canonical_id": safe_slug(name),
                "kind": "skill",
                "path": str(skill),
                "source_root": source_root_for_tool(skill, paths),
                "copy_role": "canonical-custom",
                "risk_rank": 0,
                "status": status,
                "auth_state": "not_required",
                "duplicates": [],
                "recommended_action": "retire" if status == "legacy" else "keep",
                "reason": desc or "Skill file discovered.",
            }
            records.append(rec)
            record_by_path[str(skill)] = rec

    duplicate_names = {name: paths_ for name, paths_ in by_name.items() if len(paths_) > 1}
    if duplicate_names:
        cleanup_candidates = []
        for name, skill_paths in duplicate_names.items():
            canonical_path = canonical_skill_path(name, skill_paths, paths)
            for skill_path in skill_paths:
                rec = record_by_path.get(skill_path)
                if not rec:
                    continue
                role = skill_copy_role(skill_path, canonical_path, paths)
                risk = skill_risk_rank(name, skill_paths, skill_path, role)
                rec["duplicates"] = [p for p in skill_paths if p != rec["path"]]
                rec["canonical_id"] = safe_slug(name)
                rec["copy_role"] = role
                rec["risk_rank"] = risk
                if role.startswith("canonical"):
                    rec["recommended_action"] = "keep-canonical"
                    rec["reason"] = "Canonical skill copy selected by source-root precedence."
                else:
                    rec["recommended_action"] = "route-to-canonical"
                    rec["reason"] = f"Duplicate skill copy; canonical path is {canonical_path}."
                    cleanup_candidates.append(rec)
        cleanup_candidates.sort(key=lambda r: (-r["risk_rank"], r["id"], r["path"]))
        evidence = [
            line_evidence(
                rec["path"],
                source=f"{rec['id']}: role={rec['copy_role']} risk_rank={rec['risk_rank']} canonical_id={rec['canonical_id']}",
            )
            for rec in cleanup_candidates[:10]
        ]
        findings.append(finding(
            "tools-duplicate-skill-families",
            "tools",
            "warn",
            f"{len(duplicate_names)} skill names appear in more than one location; top {len(evidence)} routing risks are ranked.",
            evidence,
            "Clean only the highest-risk ambiguous routing copies first; keep plugin-cache copies unless they are actively confusing dispatch.",
            "static",
            "high",
        ))

    config_files = [paths.codex_home / "config.toml", paths.claude_home / "settings.json"]
    for cfg in config_files:
        text = safe_read_text(cfg, max_bytes=500_000)
        if not text:
            continue
        current_tool = None
        for line_no, line in enumerate(text.splitlines(), 1):
            section = re.search(r"\[(?:mcp_servers|mcpServers)\.([^\]]+)\]", line)
            if section:
                current_tool = section.group(1).strip("\"'")
            if "mcp" not in line.lower() and "enabledplugins" not in line.lower() and "plugin" not in line.lower():
                if current_tool and re.search(r"auth\s*=\s*[\"']missing[\"']|not logged in|unauthorized|invalid token", line, re.I):
                    records.append({
                        "id": current_tool,
                        "canonical_id": safe_slug(current_tool),
                        "kind": "mcp_or_plugin",
                        "path": str(cfg),
                        "source_root": source_root_for_tool(cfg, paths),
                        "copy_role": "configured-tool",
                        "risk_rank": 75,
                        "status": "configured",
                        "auth_state": "broken",
                        "duplicates": [],
                        "recommended_action": "fix-auth",
                        "reason": redact(line.strip())[:300],
                    })
                continue
            name_match = re.search(r'["\']?([A-Za-z0-9_.-]*(?:figma|slack|sentry|cloudflare|apollo|github|gmail|sharepoint|teams)[A-Za-z0-9_.-]*)["\']?', line, re.I)
            if name_match:
                name = name_match.group(1)
            elif current_tool:
                name = current_tool
            else:
                continue
            auth_state = auth_state_for_tool(name, cfg, line)
            action = "fix-auth" if auth_state == "broken" else "verify-auth" if auth_state == "unknown" else "keep"
            records.append({
                "id": name,
                "canonical_id": safe_slug(name),
                "kind": "mcp_or_plugin",
                "path": str(cfg),
                "source_root": source_root_for_tool(cfg, paths),
                "copy_role": "configured-tool",
                "risk_rank": 70 if auth_state == "broken" else 25 if auth_state == "unknown" else 0,
                "status": "configured",
                "auth_state": auth_state,
                "duplicates": [],
                "recommended_action": action,
                "reason": redact(line.strip())[:300],
            })

    broken = [r for r in records if r["auth_state"] == "broken"]
    unknown_auth = [r for r in records if r["auth_state"] == "unknown"]
    if broken:
        findings.append(finding(
            "tools-auth-broken",
            "tools",
            "warn",
            f"{len(broken)} configured tool references appear auth-broken from local config/log text.",
            [line_evidence(r["path"], source=r["id"]) for r in broken[:12]],
            "Repair or disable auth-broken tools before relying on them in an overnight workflow.",
            "static",
            "high",
        ))
    elif unknown_auth:
        findings.append(finding(
            "tools-auth-unknown",
            "tools",
            "info",
            f"{len(unknown_auth)} auth-sensitive tool references need live readiness confirmation.",
            [line_evidence(r["path"], source=r["id"]) for r in unknown_auth[:12]],
            "Run the relevant doctor/auth check before routing important work through these tools.",
            "static",
            "medium",
        ))

    legacy = [r for r in records if r["status"] == "legacy"]
    if legacy:
        findings.append(finding(
            "tools-legacy-skills",
            "tools",
            "info",
            f"{len(legacy)} legacy or archived skills were discovered.",
            [line_evidence(r["path"], source=r["id"]) for r in legacy[:12]],
            "Retire stale entries or make their deprecated status explicit in the routing layer.",
            "static",
            "medium",
        ))

    if write_outputs:
        write_json(paths.tool_registry_path, records)
        write_findings(paths, findings or [finding(
            "tools-no-findings",
            "tools",
            "info",
            "Tool lifecycle scan completed with no duplicate, legacy, or auth-readiness findings.",
            [line_evidence(paths.tool_registry_path, source="tool-registry.json")],
            "Keep weekly registry generation as drift monitoring.",
            "static",
            "medium",
        )])
    return {"records": records, "findings": findings}


def classify_project(path):
    name = path.name.lower()
    text = " ".join(
        p.name.lower()
        for p in path.iterdir()
        if not p.name.startswith(".") and p.name not in PRUNE_DIRS
    ) if path.exists() else ""
    blob = f"{name} {text}"
    if any(t in blob for t in ("local-ai", "laik", "llm", "ai-search")):
        return "ai-infra"
    if any(t in blob for t in ("koho", "prettyfly", "yehovah", "b2b", "marketing", "ctox")):
        return "client-revenue"
    if any(t in blob for t in ("rainman", "sportsbook")):
        return "ml-decision"
    if name in {"agents", "agent-browser", "agent-coordination", "mission-control", "gravity-stack", "gravity-claw"} or "hermes" in blob:
        return "agent-runtime"
    if any(t in blob for t in ("design", "atelier")):
        return "design-tooling"
    if any(t in blob for t in ("research", "vault", "memory")):
        return "research-memory"
    return "project"


def is_ai_project_record(record):
    name = record["name"].lower()
    kind = record["kind"]
    if kind in {"agent-runtime", "ai-infra", "ml-decision"}:
        return True
    if any(token in name for token in AI_PROJECT_HINTS):
        return True
    return bool(re.search(r"(^|[-_])ai($|[-_])", name))


def detect_stack(path):
    markers = {
        "package.json": "node",
        "pnpm-lock.yaml": "pnpm",
        "pyproject.toml": "python",
        "requirements.txt": "python",
        "uv.lock": "uv",
        "Cargo.toml": "rust",
        "go.mod": "go",
        "supabase": "supabase",
        ".vercel": "vercel",
    }
    stack = []
    for marker, label in markers.items():
        if (path / marker).exists() and label not in stack:
            stack.append(label)
    return stack


def project_boundary(path):
    name = path.name.lower()
    hits = [t for t in CLIENT_TOKENS if t in name]
    for doc in ("CLAUDE.md", "AGENTS.md", "README.md"):
        text = safe_read_text(path / doc, max_bytes=80_000).lower()
        for token in CLIENT_TOKENS:
            if token in text and token not in hits:
                hits.append(token)
        if any(word in text for word in ("tenant", "pii", "client data", "ip silo", "canonical data")):
            return ",".join(hits) if hits else "declared"
    return ",".join(hits) if hits else "unknown"


def canonical_group(name):
    n = name.lower()
    n = re.sub(r"(-copy|-backup|-wt|-worktree|-v\d+|-\d+\.\d+|-\d+)$", "", n)
    n = n.replace("consult-ops", "consultops")
    return n


def quick_evidence_refs(path):
    refs = []
    for p, is_dir in iter_project_tree(path, max_entries=1500):
        if not is_dir:
            continue
        if p.name in EVIDENCE_DIRS and str(p) not in refs:
            refs.append(str(p))
        if len(refs) >= 10:
            break
    return refs[:10]


def scan_projects(paths):
    records = []
    if not paths.projects_root.exists():
        return records
    dirs = [p for p in sorted(paths.projects_root.iterdir()) if p.is_dir() and not p.name.startswith(".")]
    groups = defaultdict(list)
    for p in dirs:
        groups[canonical_group(p.name)].append(p)
    for p in dirs:
        stack = detect_stack(p)
        deploy_targets = []
        if (p / ".vercel").exists():
            deploy_targets.append("vercel")
        if (p / "supabase").exists():
            deploy_targets.append("supabase")
        if any((p / d).exists() for d in ("deploy", "ops", ".github")):
            deploy_targets.append("ops_or_ci")
        group = groups[canonical_group(p.name)]
        canonical_status = "unresolved" if len(group) > 1 else "canonical" if (p / ".git").exists() else "untracked"
        records.append({
            "name": p.name,
            "path": str(p),
            "kind": classify_project(p),
            "stack": stack,
            "canonical_status": canonical_status,
            "deploy_targets": sorted(set(deploy_targets)),
            "data_boundary": project_boundary(p),
            "evidence_refs": quick_evidence_refs(p),
            "last_verified": mtime_iso(p / ".planning") or mtime_iso(p / "README.md") or mtime_iso(p),
            "next_action": "resolve canonical checkout" if canonical_status == "unresolved" else "index evidence" if not quick_evidence_refs(p) else "keep current",
        })
    return records


def scan_portfolio(args, paths, write_outputs=True):
    records = scan_projects(paths)
    findings = []
    unresolved = [r for r in records if r["canonical_status"] == "unresolved"]
    if unresolved:
        findings.append(finding(
            "portfolio-unresolved-canonical-checkout",
            "portfolio",
            "warn",
            f"{len(unresolved)} project paths have ambiguous canonical checkout status.",
            [line_evidence(r["path"], source=r["name"]) for r in unresolved[:12]],
            "Pick one canonical path before editing/deploying; keep alternates archived or explicitly labeled.",
            "static",
            "high",
        ))
    stale_focus = paths.projects_root / "personal-vault" / "context" / "current-focus.md"
    if stale_focus.exists():
        age_days = (time.time() - stale_focus.stat().st_mtime) / 86400
        if age_days > 45:
            findings.append(finding(
                "portfolio-stale-current-focus",
                "portfolio",
                "info",
                "Personal-vault current-focus is stale relative to recent operator work.",
                [line_evidence(stale_focus, source=f"age_days={age_days:.0f}")],
                "Refresh current-focus or demote it as a planning source when newer operator artifacts disagree.",
                "static",
                "medium",
            ))
    if not records:
        findings.append(finding(
            "portfolio-no-projects",
            "portfolio",
            "warn",
            "No projects were found under the configured projects root.",
            [line_evidence(paths.projects_root)],
            "Check --projects-root before relying on portfolio output.",
            "static",
            "high",
        ))
    if write_outputs:
        dump_yaml_records(paths.portfolio_path, records)
        write_findings(paths, findings or [finding(
            "portfolio-no-findings",
            "portfolio",
            "info",
            "Portfolio scan completed with no canonical checkout or stale-focus findings.",
            [line_evidence(paths.portfolio_path, source="portfolio-registry.yaml")],
            "Keep this registry current before project planning.",
            "static",
            "medium",
        )])
    return {"records": records, "findings": findings}


def scan_evidence_records(paths, stale_days=30):
    records = []
    for project in scan_projects(paths):
        root = Path(project["path"])
        for p, is_dir in iter_project_tree(root, max_entries=5000):
            if is_dir and p.name in EVIDENCE_DIRS:
                kind = EVIDENCE_DIRS[p.name]
                records.append({
                    "project": project["name"],
                    "path": str(p),
                    "kind": kind,
                    "timestamp": mtime_iso(p),
                    "command_or_source": "filesystem",
                    "result": "present",
                    "is_live": kind in {"run", "browser-test", "lighthouse"},
                    "stale_after_days": stale_days,
                })
                if len(records) > 5000:
                    return records
                continue
            if is_dir:
                continue
            lname = p.name.lower()
            if any(token in lname for token in ("backtest", "ragas", "promptfoo", "playwright", "review", "smoke", "verification")) and p.suffix.lower() in {".md", ".json", ".jsonl", ".txt", ".html"}:
                records.append({
                    "project": project["name"],
                    "path": str(p),
                    "kind": "evidence-file",
                    "timestamp": mtime_iso(p),
                    "command_or_source": "filename-signal",
                    "result": "present",
                    "is_live": any(token in lname for token in ("smoke", "playwright", "verification")),
                    "stale_after_days": stale_days,
                })
                if len(records) > 5000:
                    return records
    return records


def scan_evidence(args, paths, write_outputs=True):
    records = scan_evidence_records(paths)
    findings = []
    now = utc_now()
    stale = []
    for rec in records:
        ts = parse_ts(rec.get("timestamp"))
        if ts and (now - ts).days > rec.get("stale_after_days", 30):
            stale.append(rec)
    if stale:
        findings.append(finding(
            "evidence-stale-records",
            "evidence",
            "info",
            f"{len(stale)} evidence records are older than their stale threshold.",
            [line_evidence(r["path"], source=f"{r['project']} {r['timestamp']}") for r in stale[:12]],
            "Refresh stale evidence before treating the project as live-ready.",
            "static",
            "medium",
        ))
    if not records:
        findings.append(finding(
            "evidence-no-records",
            "evidence",
            "warn",
            "No local evidence directories or verification artifacts were discovered.",
            [line_evidence(paths.projects_root)],
            "Run tests, evals, or smoke checks and capture outputs under standard evidence paths.",
            "static",
            "high",
        ))
    if write_outputs:
        append_records(paths.evidence_path, records)
        write_findings(paths, findings or [finding(
            "evidence-no-findings",
            "evidence",
            "info",
            "Evidence scan completed with no stale or missing-evidence findings.",
            [line_evidence(paths.evidence_path, source="evidence-registry.ndjson")],
            "Use the registry during closeout and review.",
            "static",
            "medium",
        )])
    return {"records": records, "findings": findings}


def text_for_project(path):
    chunks = []
    for name in ("CLAUDE.md", "AGENTS.md", "README.md", "package.json", "pyproject.toml", "requirements.txt"):
        p = Path(path) / name
        if p.exists():
            chunks.append(safe_read_text(p, max_bytes=120_000))
    return "\n".join(chunks)


def readiness_gaps(contract):
    gaps = []
    if not contract.get("eval_refs"):
        gaps.append("missing eval/backtest evidence")
    if contract.get("kill_switch") == "missing":
        gaps.append("missing kill switch or rollback")
    if not contract.get("allowed_tools"):
        gaps.append("missing allowed tools")
    if contract.get("mutation_policy") == "unknown":
        gaps.append("missing mutation policy")
    if contract.get("approval_level") == "unspecified":
        gaps.append("missing approval level")
    if not contract.get("telemetry_refs"):
        gaps.append("missing telemetry")
    if contract.get("cost_ceiling") == "missing":
        gaps.append("missing cost ceiling")
    if contract.get("boundary") == "unknown":
        gaps.append("missing data boundary")
    return gaps


def readiness_score(contract):
    score = 0
    if contract.get("eval_refs"):
        score += 25
    if contract.get("kill_switch") == "declared":
        score += 20
    if contract.get("allowed_tools"):
        score += 15
    if contract.get("mutation_policy") != "unknown":
        score += 10
    if contract.get("approval_level") != "unspecified":
        score += 10
    if contract.get("telemetry_refs"):
        score += 10
    if contract.get("cost_ceiling") == "declared":
        score += 5
    if contract.get("boundary") != "unknown":
        score += 5
    return min(100, score)


def readiness_status(score):
    if score >= 80:
        return "safe for supervised"
    if score >= 55:
        return "safe for read-only"
    return "not ready"


def contract_for_project(project, evidence_records):
    path = Path(project["path"])
    text = text_for_project(path).lower()
    eval_refs = [r["path"] for r in evidence_records if r["project"] == project["name"] and r["kind"] in {"eval", "prompt-eval", "evidence-file"}][:12]
    telemetry_refs = []
    for token in ("langfuse", "sentry", "opentelemetry", "otel", "posthog", "pino"):
        if token in text:
            telemetry_refs.append(token)
    allowed_tools = []
    for token in ("mcp", "browser", "supabase", "vercel", "github", "filesystem", "postgres"):
        if token in text:
            allowed_tools.append(token)
    mutation_policy = "propose-first" if "propose" in text or "read-only" in text else "unknown"
    approval_level = "human-required" if any(t in text for t in ("approval", "human", "supervised")) else "unspecified"
    kill_switch = "declared" if any(t in text for t in ("kill switch", "killswitch", "disable", "rollback", "stop automation")) else "missing"
    graduation = "production" if "production" in text and eval_refs and kill_switch == "declared" else "supervised" if eval_refs else "internal"
    contract = {
        "system": project["name"],
        "path": project["path"],
        "graduation_rung": graduation,
        "allowed_tools": allowed_tools,
        "mutation_policy": mutation_policy,
        "approval_level": approval_level,
        "eval_refs": eval_refs,
        "telemetry_refs": telemetry_refs,
        "cost_ceiling": "declared" if "cost" in text or "budget" in text else "missing",
        "kill_switch": kill_switch,
        "boundary": project["data_boundary"],
    }
    score = readiness_score(contract)
    contract["readiness_score"] = score
    contract["readiness_status"] = readiness_status(score)
    contract["readiness_gaps"] = readiness_gaps(contract)
    return contract


def scan_ai_contract(args, paths, write_outputs=True):
    projects = [p for p in scan_projects(paths) if is_ai_project_record(p)]
    evidence_records = scan_evidence_records(paths)
    contracts = [contract_for_project(p, evidence_records) for p in projects]
    findings = []
    missing_eval = [c for c in contracts if not c["eval_refs"]]
    missing_kill = [c for c in contracts if c["kill_switch"] == "missing"]
    not_ready = [c for c in contracts if c["readiness_status"] == "not ready"]
    if missing_eval:
        findings.append(finding(
            "ai-contract-missing-eval",
            "ai-contract",
            "warn",
            f"{len(missing_eval)} AI/agent/ML systems have no discovered eval/backtest evidence references.",
            [line_evidence(c["path"], source=c["system"]) for c in missing_eval[:12]],
            "Add or index eval/backtest/golden-set evidence before raising autonomy.",
            "static",
            "high",
        ))
    if missing_kill:
        findings.append(finding(
            "ai-contract-missing-kill-switch",
            "ai-contract",
            "warn",
            f"{len(missing_kill)} AI/agent/ML systems have no discovered kill switch or rollback reference.",
            [line_evidence(c["path"], source=c["system"]) for c in missing_kill[:12]],
            "Document a disable/rollback path before supervised or autonomous operation.",
            "static",
            "high",
        ))
    if not_ready:
        findings.append(finding(
            "ai-contract-low-readiness-score",
            "ai-contract",
            "warn",
            f"{len(not_ready)} AI/agent/ML systems score below read-only readiness.",
            [line_evidence(c["path"], source=f"{c['system']} score={c['readiness_score']} gaps={'; '.join(c['readiness_gaps'][:4])}") for c in not_ready[:12]],
            "Keep these systems below autonomous or supervised mutation until score-critical gaps are closed.",
            "static",
            "high",
        ))
    if write_outputs:
        write_json(paths.operator_intel / "ai-contracts.json", contracts)
        write_findings(paths, findings or [finding(
            "ai-contract-no-findings",
            "ai-contract",
            "info",
            "AI contract scan completed with no missing eval or kill-switch findings.",
            [line_evidence(paths.operator_intel / "ai-contracts.json")],
            "Keep readiness contracts generated from repo evidence.",
            "static",
            "medium",
        )])
    return {"records": contracts, "findings": findings}


def boundary_for_path(path, projects_root):
    p = Path(path)
    parts = [part.lower() for part in p.parts]
    client_hits = [token for token in CLIENT_TOKENS if any(token in part for part in parts)]
    project = None
    try:
        rel = p.resolve().relative_to(Path(projects_root).resolve())
        project = rel.parts[0] if rel.parts else None
    except Exception:
        project = None
    ambiguous = len(set(client_hits)) > 1
    return {
        "path": str(path),
        "project": project,
        "client_tokens": sorted(set(client_hits)),
        "allowed": not ambiguous,
        "severity": "warn" if ambiguous else "info",
        "reason": "cross-client boundary ambiguity" if ambiguous else "no cross-client ambiguity detected",
    }


def scan_boundary(args, paths, write_outputs=True):
    if args.check_write:
        result = boundary_for_path(args.check_write, paths.projects_root)
        print(json.dumps(redact_obj(result), indent=2, sort_keys=True))
        return {"records": [result], "findings": []}
    projects = scan_projects(paths)
    findings = []
    ambiguous = []
    unknown_client = []
    for p in projects:
        tokens = [t for t in CLIENT_TOKENS if t in p["name"].lower()]
        if len(tokens) > 1:
            ambiguous.append(p)
        elif p["kind"] in {"client-revenue", "ai-infra"} and p["data_boundary"] == "unknown":
            unknown_client.append(p)
    if ambiguous:
        findings.append(finding(
            "boundary-cross-client-ambiguous-project",
            "boundary",
            "warn",
            f"{len(ambiguous)} project names contain multiple client tokens.",
            [line_evidence(p["path"], source=p["name"]) for p in ambiguous[:12]],
            "Resolve naming or add an explicit data-boundary policy before agents write.",
            "static",
            "high",
        ))
    if unknown_client:
        findings.append(finding(
            "boundary-missing-policy",
            "boundary",
            "info",
            f"{len(unknown_client)} client/AI projects have no detected boundary declaration.",
            [line_evidence(p["path"], source=p["name"]) for p in unknown_client[:12]],
            "Add a concise boundary statement to CLAUDE.md or AGENTS.md.",
            "static",
            "medium",
        ))
    if write_outputs:
        write_json(paths.operator_intel / "data-boundary-report.json", {
            "projects": projects,
            "generated_at": iso_now(),
        })
        write_findings(paths, findings or [finding(
            "boundary-no-findings",
            "boundary",
            "info",
            "Boundary scan completed with no cross-client or missing-policy findings.",
            [line_evidence(paths.operator_intel / "data-boundary-report.json")],
            "Use --check-write for future hook planning.",
            "static",
            "medium",
        )])
    return {"records": projects, "findings": findings}


def scan_agents(args, paths, write_outputs=True):
    sources = []
    candidates = [
        paths.projects_root / "agents",
        paths.projects_root / "mission-control",
        paths.codex_home / "automations",
    ]
    for root in candidates:
        if not root.exists():
            continue
        for p in root.iterdir():
            if not p.is_dir() or p.name.startswith(".") or p.name in PRUNE_DIRS:
                continue
            has_profile_doc = any((p / name).exists() for name in ("README.md", "CLAUDE.md", "AGENTS.md", "automation.toml", "memory.md"))
            if root == paths.codex_home / "automations" or has_profile_doc:
                sources.append(p)
    evidence_records = scan_evidence_records(paths)
    cards = []
    findings = []
    if write_outputs:
        mkdir(paths.agent_cards)
        for old_card in paths.agent_cards.glob("*.md"):
            try:
                old_card.unlink()
            except OSError:
                pass
    for source in sources:
        project = {
            "name": source.name,
            "path": str(source),
            "kind": "agent-runtime",
            "data_boundary": project_boundary(source),
        }
        contract = contract_for_project(project, evidence_records)
        cards.append(contract)
        md = render_agent_card(contract)
        if write_outputs:
            write_text(paths.agent_cards / f"{safe_slug(contract['system'])}.md", md)
    missing = [c for c in cards if c["readiness_status"] == "not ready" or not c["allowed_tools"] or not c["eval_refs"] or c["kill_switch"] == "missing"]
    if missing:
        findings.append(finding(
            "agent-cards-incomplete-readiness",
            "agent-cards",
            "warn",
            f"{len(missing)} agent/automation cards are missing allowed tools, eval evidence, or kill switch.",
            [line_evidence(c["path"], source=c["system"]) for c in missing[:12]],
            "Keep agents below autonomous operation until cards are complete from file/log evidence.",
            "static",
            "high",
        ))
    if write_outputs:
        write_json(paths.operator_intel / "agent-capability-cards.json", cards)
        write_findings(paths, findings or [finding(
            "agent-cards-no-findings",
            "agent-cards",
            "info",
            "Agent card generation completed with no readiness gaps.",
            [line_evidence(paths.agent_cards)],
            "Review generated cards before overnight automation.",
            "static",
            "medium",
        )])
    return {"records": cards, "findings": findings}


def safe_slug(text):
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(text)).strip("-").lower() or "item"


def render_agent_card(contract):
    return f"""# {contract['system']} Capability Card

Generated: {iso_now()}

| Field | Value |
|---|---|
| Path | `{contract['path']}` |
| Readiness score | {contract['readiness_score']} |
| Readiness status | {contract['readiness_status']} |
| Readiness gaps | {', '.join(contract['readiness_gaps']) or 'none'} |
| Graduation rung | {contract['graduation_rung']} |
| Allowed tools | {', '.join(contract['allowed_tools']) or 'missing'} |
| Mutation policy | {contract['mutation_policy']} |
| Approval level | {contract['approval_level']} |
| Eval refs | {len(contract['eval_refs'])} discovered |
| Telemetry refs | {', '.join(contract['telemetry_refs']) or 'missing'} |
| Cost ceiling | {contract['cost_ceiling']} |
| Kill switch | {contract['kill_switch']} |
| Boundary | {contract['boundary']} |
"""


def memory_validation(paths):
    script = paths.projects_root / "memory-vault" / "scripts" / "memory_hub.py"
    if not script.exists():
        return {"status": "missing", "summary": "memory_hub.py not found", "details": ""}
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--validate", "--strict-wiki"],
            capture_output=True,
            text=True,
            timeout=90,
        )
        text = redact((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else ""))
        summary = "exit_code=%s" % proc.returncode
        m = re.search(r"errors:\s*(\d+).*warnings:\s*(\d+).*strict wiki blockers:\s*(\d+)", text, re.S | re.I)
        if m:
            summary = f"errors={m.group(1)}, warnings={m.group(2)}, strict_wiki_blockers={m.group(3)}"
        return {"status": "ran", "summary": summary, "details": text[:4000]}
    except Exception as exc:
        return {"status": "error", "summary": str(exc), "details": ""}


def report_path(paths):
    day = utc_now().strftime("%Y-%m-%d")
    return paths.operator_artifacts / f"{day}-operating-layer-report.md"


def dated_artifact_path(paths, suffix):
    day = utc_now().strftime("%Y-%m-%d")
    return paths.operator_artifacts / f"{day}-{suffix}.md"


def render_improvement_plan(paths, items):
    lines = [
        "# Operating Layer 1% Improvement Queue",
        "",
        f"Generated: {iso_now()}",
        "",
        "```mermaid",
        "flowchart LR",
        '  A["Run operating-layer all"] --> B["Rank findings by leverage"]',
        '  B --> C["Fix one constraint"]',
        '  C --> D["Prove with tests + artifact"]',
        '  D --> E["Rerun operating-layer"]',
        '  E --> F["Compare trend"]',
        '  F --> G["Promote repeated objective rules"]',
        '  G --> A',
        "```",
        "",
        "## Top Moves",
        "",
        "| Rank | Score | Workflow | Finding | Move | Acceptance |",
        "|---:|---:|---|---|---|---|",
    ]
    for item in items[:12]:
        lines.append(
            f"| {item['rank']} | {item['score']} | {item['workflow']} | `{item['id']}` | {item['move']} | {item['acceptance']} |"
        )
    if not items:
        lines.append("| - | - | - | - | No ranked findings. | Keep scheduled scans running. |")
    lines.extend([
        "",
        "## Source",
        "",
        f"- Findings: `{paths.findings_path}`",
        f"- Queue JSON: `{paths.improvement_queue_path}`",
    ])
    return "\n".join(lines) + "\n"


def render_compare_report(paths, trend):
    summary = trend.get("summary", {})
    lines = [
        "# Operating Layer Trend Compare",
        "",
        f"Generated: {iso_now()}",
        "",
        "## Summary",
        "",
        f"- Baseline: `{trend.get('baseline')}`",
        f"- Candidate: `{trend.get('candidate')}`",
        f"- Added: {summary.get('added', 0)}",
        f"- Resolved: {summary.get('resolved', 0)}",
        f"- Unchanged: {summary.get('unchanged', 0)}",
        f"- Worsened: {summary.get('worsened', 0)}",
        "",
    ]
    for label in ("worsened", "added", "resolved"):
        lines.extend([f"## {label.title()}", ""])
        items = trend.get(label, [])
        if not items:
            lines.append("No entries.")
            lines.append("")
            continue
        for item in items[:20]:
            finding_obj = item.get("finding", item) if isinstance(item, dict) else item
            lines.append(f"- `{finding_obj.get('id')}` ({finding_obj.get('workflow')}): {finding_obj.get('message')}")
        lines.append("")
    lines.extend([
        "## Source",
        "",
        f"- Compare JSON: `{paths.compare_path}`",
        f"- History: `{paths.history_dir}`",
    ])
    return "\n".join(lines) + "\n"


def select_planning_project(records):
    priority = ("local-ai-kit", "rainman", "sportsbook", "hermes", "koho", "agents")

    def score(record):
        name = record.get("name", "").lower()
        value = 0
        for idx, token in enumerate(priority):
            if token in name:
                value = 100 - idx * 10
                break
        if record.get("kind") in {"ai-infra", "ml-decision", "agent-runtime", "client-revenue"}:
            value += 20
        if record.get("evidence_refs"):
            value += 10
        if record.get("canonical_status") == "canonical":
            value += 5
        return value

    return sorted(records, key=lambda r: (-score(r), r.get("name", "")))[0] if records else None


def generate_planning_consumption_proof(paths, results, findings):
    records = results.get("portfolio", {}).get("records", [])
    evidence = results.get("evidence", {}).get("records", [])
    project = select_planning_project(records)
    md_path = dated_artifact_path(paths, "planning-consumption-proof")
    html_path = md_path.with_suffix(".html")
    if not project:
        write_text(md_path, "# Planning Consumption Proof\n\nNo project records were available to consume.\n")
        render_html(md_path, html_path)
        return {"markdown": str(md_path), "html": str(html_path), "project": None}

    project_evidence = [r for r in evidence if r.get("project") == project["name"]]
    relevant_findings = [
        f for f in findings
        if project["name"].lower() in json.dumps(f, sort_keys=True).lower()
        or f.get("workflow") in {"portfolio", "evidence", "ai-contract", "boundary"}
    ][:8]
    lines = [
        "# Planning Consumption Proof",
        "",
        f"Generated: {iso_now()}",
        "",
        "## Registries Consumed",
        "",
        f"- Portfolio: `{paths.portfolio_path}`",
        f"- Evidence: `{paths.evidence_path}`",
        f"- Findings: `{paths.findings_path}`",
        "",
        "## Selected Project",
        "",
        f"- Name: {project['name']}",
        f"- Path: `{project['path']}`",
        f"- Kind: {project['kind']}",
        f"- Stack: {', '.join(project['stack']) or 'unknown'}",
        f"- Canonical status: {project['canonical_status']}",
        f"- Data boundary: {project['data_boundary']}",
        f"- Latest verified: {project['last_verified']}",
        f"- Next action from registry: {project['next_action']}",
        "",
        "## Latest Proof",
        "",
    ]
    if project_evidence:
        for rec in project_evidence[:10]:
            lines.append(f"- `{rec['path']}` ({rec['kind']}, {rec['timestamp']}, live={rec['is_live']})")
    else:
        lines.append("- No evidence records found for this project; planning must treat live readiness as unproven.")
    lines.extend(["", "## Open Operating Risks", ""])
    if relevant_findings:
        for f in relevant_findings:
            lines.append(f"- `{f['id']}` ({f['workflow']}): {f['message']}")
    else:
        lines.append("- No project-specific operating-layer risks matched the selected project.")
    lines.extend([
        "",
        "## Plan Skeleton Using Live Truth",
        "",
        "1. Start from the canonical checkout and treat alternates as read-only until registry ambiguity is resolved.",
        "2. Use the latest evidence records as proof inputs; stale or missing evidence becomes an explicit plan risk.",
        "3. Keep AI/agent autonomy at or below the readiness status emitted by the current contract/card.",
        "4. Close the next slice by adding a new proof artifact, rerunning `operating-layer.py all`, and comparing trend.",
    ])
    write_text(md_path, "\n".join(lines) + "\n")
    render_html(md_path, html_path)
    return {"markdown": str(md_path), "html": str(html_path), "project": project["name"]}


def read_json_file(path, default):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(safe_read_text(p, max_bytes=5_000_000))
    except Exception:
        return default


def current_work_context(paths, project_path):
    project_path = str(Path(project_path).expanduser())
    project_name = Path(project_path).name
    findings = read_ndjson(paths.findings_path)
    evidence = read_ndjson(paths.evidence_path)
    tools = read_json_file(paths.tool_registry_path, [])
    ai_contracts = read_json_file(paths.operator_intel / "ai-contracts.json", [])
    project_evidence = [r for r in evidence if r.get("project") == project_name or str(r.get("path", "")).startswith(project_path)]
    now = utc_now()
    stale_evidence = []
    for rec in project_evidence:
        ts = parse_ts(rec.get("timestamp"))
        if ts and (now - ts).days > rec.get("stale_after_days", 30):
            stale_evidence.append(rec)
    tool_risks = sorted(
        [r for r in tools if int(r.get("risk_rank") or 0) >= 70],
        key=lambda r: (-(int(r.get("risk_rank") or 0)), r.get("id", "")),
    )[:8]
    ai_matches = [
        c for c in ai_contracts
        if c.get("path") == project_path or c.get("system") == project_name or c.get("system", "").lower() in project_name.lower()
    ][:8]
    return {
        "boundary": boundary_for_path(project_path, paths.projects_root),
        "findings": [{"id": f.get("id"), "workflow": f.get("workflow"), "severity": f.get("severity")} for f in findings[:12]],
        "findings_count": len(findings),
        "evidence_count": len(project_evidence),
        "stale_evidence_count": len(stale_evidence),
        "tool_risks": [{"id": r.get("id"), "risk_rank": r.get("risk_rank"), "copy_role": r.get("copy_role")} for r in tool_risks],
        "ai_readiness": [{"system": c.get("system"), "score": c.get("readiness_score"), "status": c.get("readiness_status")} for c in ai_matches],
    }


def load_work_records(paths):
    return {
        "items": read_ndjson(paths.work_items_path),
        "runs": read_ndjson(paths.pathway_runs_path),
        "measurements": read_ndjson(paths.pathway_measurements_path),
        "controls": read_ndjson(paths.controls_path),
    }


def stale_measurements(measurements):
    now = utc_now()
    stale = []
    for measurement in measurements:
        ts = parse_ts(measurement.get("timestamp"))
        stale_after = int(measurement.get("stale_after_days") or WORK_STALE_DAYS)
        if ts and (now - ts).days > stale_after:
            stale.append(measurement)
    return stale


def work_status_summary(paths, work_id):
    records = load_work_records(paths)
    item = next((w for w in records["items"] if w.get("work_id") == work_id), None)
    runs = [r for r in records["runs"] if r.get("work_id") == work_id]
    measurements = [m for m in records["measurements"] if m.get("work_id") == work_id]
    controls = [c for c in records["controls"] if c.get("work_id") == work_id]
    open_controls = [c for c in controls if c.get("status", "open") != "resolved"]
    missing_evidence = [m for m in measurements if not m.get("evidence_id")]
    stale = stale_measurements(measurements)
    pathways_seen = sorted(set(r.get("pathway") for r in runs if r.get("pathway")))
    missing_core_pathways = [p for p in PATHWAY_ORDER if p not in pathways_seen]
    ready = bool(item and runs and not open_controls and not missing_evidence and not stale)
    return {
        "work_item": item,
        "runs": runs,
        "measurements": measurements,
        "controls": controls,
        "pathway_coverage": {
            "seen": pathways_seen,
            "missing_core": missing_core_pathways,
            "count": len(pathways_seen),
        },
        "missing_evidence": missing_evidence,
        "stale_measurements": stale,
        "open_controls": open_controls,
        "closeout_readiness": "ready" if ready else "not_ready",
        "warnings": work_warnings(item, runs, measurements, open_controls, stale),
    }


def work_warnings(item, runs, measurements, open_controls, stale):
    warnings = []
    if not item:
        warnings.append("No linked work item exists for this work_id.")
    if not runs:
        warnings.append("No pathway runs have been logged for this outcome.")
    if any(not m.get("evidence_id") for m in measurements):
        warnings.append("One or more measurements lack evidence.")
    if stale:
        warnings.append(f"{len(stale)} measurements are stale.")
    if open_controls:
        warnings.append(f"{len(open_controls)} controls remain open.")
    return warnings


def build_daily_dashboard(paths):
    records = load_work_records(paths)
    work_items = sorted(records["items"], key=lambda w: w.get("updated_at", ""), reverse=True)
    active = [w for w in work_items if w.get("status", "active") != "closed"]
    summaries = [work_status_summary(paths, w.get("work_id")) for w in active[:25]]
    stuck = [
        s for s in summaries
        if s["open_controls"] or s["stale_measurements"] or any("No pathway runs" in w for w in s["warnings"])
    ]
    queue = read_json_file(paths.improvement_queue_path, {"items": []})
    dashboard = {
        "generated_at": iso_now(),
        "active_work_items": active,
        "active_count": len(active),
        "closed_count": len([w for w in work_items if w.get("status") == "closed"]),
        "work_summaries": summaries,
        "stuck_work_items": [
            {
                "work_id": s.get("work_item", {}).get("work_id") if s.get("work_item") else None,
                "goal": s.get("work_item", {}).get("goal") if s.get("work_item") else None,
                "warnings": s["warnings"],
            }
            for s in stuck
        ],
        "top_open_controls": [
            c for c in records["controls"]
            if c.get("status", "open") != "resolved"
        ][:12],
        "next_best_move": (queue.get("items") or [None])[0],
        "paths": {
            "work_items": str(paths.work_items_path),
            "pathway_runs": str(paths.pathway_runs_path),
            "measurements": str(paths.pathway_measurements_path),
            "controls": str(paths.controls_path),
        },
    }
    write_json(paths.daily_dashboard_path, dashboard)
    return dashboard


def render_daily_work_report(paths, dashboard):
    md_path = dated_artifact_path(paths, "daily-work-dashboard")
    html_path = md_path.with_suffix(".html")
    lines = [
        "# Daily Work Dashboard",
        "",
        f"Generated: {dashboard.get('generated_at')}",
        "",
        "## Summary",
        "",
        f"- Active work items: {dashboard.get('active_count', 0)}",
        f"- Closed work items: {dashboard.get('closed_count', 0)}",
        f"- Stuck work items: {len(dashboard.get('stuck_work_items', []))}",
        f"- Open controls: {len(dashboard.get('top_open_controls', []))}",
        "",
        "## Active Work",
        "",
    ]
    for summary in dashboard.get("work_summaries", [])[:12]:
        item = summary.get("work_item") or {}
        lines.append(f"- `{item.get('work_id')}` {item.get('goal')} — {summary.get('closeout_readiness')}; pathways={summary.get('pathway_coverage', {}).get('seen', [])}")
    if not dashboard.get("work_summaries"):
        lines.append("- No active work items.")
    lines.extend(["", "## Top Open Controls", ""])
    for control in dashboard.get("top_open_controls", [])[:12]:
        lines.append(f"- `{control.get('control_id')}` {control.get('risk')} from {control.get('source_pathway')} for `{control.get('work_id')}`")
    if not dashboard.get("top_open_controls"):
        lines.append("- No open controls.")
    move = dashboard.get("next_best_move") or {}
    lines.extend([
        "",
        "## Next Best Move",
        "",
        f"- `{move.get('id', 'none')}` {move.get('move', 'No ranked move available.')}",
        "",
        "## Source Ledgers",
        "",
        f"- Work items: `{paths.work_items_path}`",
        f"- Pathway runs: `{paths.pathway_runs_path}`",
        f"- Measurements: `{paths.pathway_measurements_path}`",
        f"- Controls: `{paths.controls_path}`",
        f"- Dashboard JSON: `{paths.daily_dashboard_path}`",
    ])
    write_text(md_path, "\n".join(lines) + "\n")
    render_html(md_path, html_path)
    return md_path, html_path


def render_report(paths, results, memory, improvement_items=None, trend=None, planning_proof=None, daily_dashboard=None):
    all_findings = []
    for res in results.values():
        all_findings.extend(res.get("findings", []))
    all_findings = unique_findings(all_findings)
    counts = Counter(f["workflow"] for f in all_findings)
    severity = Counter(f["severity"] for f in all_findings)
    lines = [
        "# Operating Layer Report",
        "",
        f"Generated: {iso_now()}",
        "",
        "## Summary",
        "",
        f"- Findings: {len(all_findings)}",
        f"- By workflow: {dict(counts)}",
        f"- By severity: {dict(severity)}",
        f"- Memory validation: {memory['summary']}",
        "",
        "## Output Files",
        "",
        f"- Findings: `{paths.findings_path}`",
        f"- Tool registry: `{paths.tool_registry_path}`",
        f"- Portfolio registry: `{paths.portfolio_path}`",
        f"- Evidence registry: `{paths.evidence_path}`",
        f"- Improvement queue: `{paths.improvement_queue_path}`",
        f"- Trend compare: `{paths.compare_path}`",
        f"- Agent cards: `{paths.agent_cards}`",
        f"- Work items: `{paths.work_items_path}`",
        f"- Pathway runs: `{paths.pathway_runs_path}`",
        f"- Pathway measurements: `{paths.pathway_measurements_path}`",
        f"- Controls: `{paths.controls_path}`",
        f"- Daily work dashboard: `{paths.daily_dashboard_path}`",
    ]
    if planning_proof:
        lines.append(f"- Planning consumption proof: `{planning_proof.get('markdown')}`")
    lines.extend([
        "",
        "## Next 1% Moves",
        "",
    ])
    if improvement_items:
        for item in improvement_items[:8]:
            lines.append(f"- #{item['rank']} score={item['score']} `{item['id']}`: {item['move']}")
    else:
        lines.append("- No ranked moves produced.")
    if trend:
        summary = trend.get("summary", {})
        lines.extend([
            "",
            "## Trend",
            "",
            f"- Added: {summary.get('added', 0)}",
            f"- Resolved: {summary.get('resolved', 0)}",
            f"- Unchanged: {summary.get('unchanged', 0)}",
            f"- Worsened: {summary.get('worsened', 0)}",
        ])
    if daily_dashboard:
        lines.extend([
            "",
            "## Daily Work",
            "",
            f"- Active work items: {daily_dashboard.get('active_count', 0)}",
            f"- Closed work items: {daily_dashboard.get('closed_count', 0)}",
            f"- Stuck work items: {len(daily_dashboard.get('stuck_work_items', []))}",
            f"- Open controls: {len(daily_dashboard.get('top_open_controls', []))}",
        ])
        for summary in daily_dashboard.get("work_summaries", [])[:8]:
            item = summary.get("work_item") or {}
            lines.append(
                f"- `{item.get('work_id')}` {item.get('goal')} — {summary.get('closeout_readiness')}; pathways={summary.get('pathway_coverage', {}).get('seen', [])}"
            )
    lines.extend([
        "",
        "## Findings",
        "",
    ])
    for f in all_findings:
        lines.extend([
            f"### {f['id']}",
            "",
            f"- Workflow: {f['workflow']}",
            f"- Severity: {f['severity']}",
            f"- Readiness: {f['static_or_runtime']}",
            f"- Confidence: {f['confidence']}",
            f"- Message: {f['message']}",
            f"- Recommendation: {f['recommendation'] or 'No action required.'}",
        ])
        if f.get("evidence"):
            lines.append("- Evidence:")
            for ev in f["evidence"][:8]:
                label = ev.get("path") or ev.get("source") or "evidence"
                detail = ev.get("snippet") or ev.get("source") or ""
                lines.append(f"  - `{label}` {detail}")
        lines.append("")
    lines.extend([
        "## Memory Validation",
        "",
        "```text",
        memory.get("details", "")[:4000],
        "```",
        "",
        "## Static Versus Live Readiness",
        "",
        "Static findings come from local files, configs, logs, and artifact paths. Live readiness still requires the relevant runtime checks, deploy probes, eval runs, or source retrievals named by the existing pathway suite.",
    ])
    return "\n".join(lines) + "\n"


def fallback_html(md_text, title):
    escaped = html.escape(md_text)
    body = re.sub(r"^# (.*)$", r"<h1>\1</h1>", escaped, flags=re.M)
    body = re.sub(r"^## (.*)$", r"<h2>\1</h2>", body, flags=re.M)
    body = re.sub(r"^### (.*)$", r"<h3>\1</h3>", body, flags=re.M)
    body = body.replace("\n", "<br>\n")
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title></head><body>{body}</body></html>"


def render_html(md_path, html_path):
    renderer = RENDERER
    if renderer.exists():
        try:
            subprocess.run([sys.executable, str(renderer), str(md_path), "--out", str(html_path)],
                           check=True, capture_output=True, text=True, timeout=60)
            return
        except Exception:
            pass
    md = safe_read_text(md_path, max_bytes=2_000_000)
    write_text(html_path, fallback_html(md, Path(md_path).stem))


def write_improvement_artifacts(paths, findings):
    items = build_improvement_queue(findings)
    write_json(paths.improvement_queue_path, {"generated_at": iso_now(), "items": items})
    md_path = dated_artifact_path(paths, "operating-layer-improvement-plan")
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_improvement_plan(paths, items))
    render_html(md_path, html_path)
    return items, md_path, html_path


def write_compare_artifacts(paths, trend):
    write_json(paths.compare_path, trend)
    md_path = dated_artifact_path(paths, "operating-layer-compare")
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_compare_report(paths, trend))
    render_html(md_path, html_path)
    return md_path, html_path


def run_work_start(args, paths):
    if not args.project or not args.goal:
        return {
            "findings": [finding(
                "work-start-missing-input",
                "daily-work",
                "warn",
                "work-start requires --project and --goal.",
                [line_evidence(paths.output_root)],
                "Run `work-start --project PATH --goal TEXT`.",
                "static",
                "high",
            )],
            "records": [],
        }
    project_path = str(Path(args.project).expanduser())
    work_id = stable_work_id(project_path, args.goal)
    context = current_work_context(paths, project_path)
    item = update_work_item(
        paths,
        work_id,
        status="active",
        mode="semi-automatic",
        project=project_path,
        project_name=Path(project_path).name,
        goal=args.goal,
        context=context,
        closeout_readiness="not_ready",
    )
    dashboard = build_daily_dashboard(paths)
    return {"records": [item], "findings": [], "work_id": work_id, "dashboard": str(paths.daily_dashboard_path), "daily": dashboard}


def run_work_status(args, paths):
    if not args.work_id:
        return {
            "findings": [finding(
                "work-status-missing-work-id",
                "daily-work",
                "warn",
                "work-status requires --work-id.",
                [line_evidence(paths.work_items_path)],
                "Pass the work_id created by work-start.",
                "static",
                "high",
            )],
            "records": [],
        }
    summary = work_status_summary(paths, args.work_id)
    return {"records": [summary], "findings": [], "summary": summary}


def run_work_log(args, paths):
    if not args.work_id or not args.pathway or not args.kind:
        return {
            "findings": [finding(
                "work-log-missing-input",
                "daily-work",
                "warn",
                "work-log requires --work-id, --pathway, and --kind.",
                [line_evidence(paths.pathway_runs_path)],
                "Log pathway work with a linked work_id, pathway, kind, and evidence when available.",
                "static",
                "high",
            )],
            "records": [],
        }
    records = load_work_records(paths)
    item = next((w for w in records["items"] if w.get("work_id") == args.work_id), None)
    findings = []
    if not item:
        findings.append(finding(
            "work-log-unlinked-work-id",
            "daily-work",
            "warn",
            f"Pathway run was logged against unknown work_id {args.work_id}.",
            [line_evidence(paths.work_items_path, source=args.work_id)],
            "Run work-start first or correct the work_id so later pathways inherit the right context.",
            "static",
            "medium",
        ))

    evidence_path = str(Path(args.evidence).expanduser()) if args.evidence else ""
    evidence_id = evidence_id_for_path(evidence_path) if evidence_path else ""
    run_id = next_run_id(paths, args.work_id, args.pathway)
    run = {
        "run_id": run_id,
        "work_id": args.work_id,
        "pathway": args.pathway,
        "kind": args.kind,
        "timestamp": iso_now(),
        "evidence_id": evidence_id,
        "evidence_path": evidence_path,
        "status": args.result or "recorded",
        "source": "operating-layer work-log",
    }
    measurement = {
        "measurement_id": measurement_id(run_id, args.gate or args.kind),
        "run_id": run_id,
        "work_id": args.work_id,
        "pathway": args.pathway,
        "gate": args.gate or args.kind,
        "kind": args.kind,
        "result": args.result or ("present" if evidence_id else "missing_evidence"),
        "timestamp": iso_now(),
        "evidence_id": evidence_id,
        "evidence_path": evidence_path,
        "stale_after_days": args.stale_after_days,
        "controls_seen": [c.get("control_id") for c in records["controls"] if c.get("work_id") == args.work_id and c.get("status", "open") != "resolved"],
    }
    all_runs = records["runs"] + [run]
    all_measurements = records["measurements"] + [measurement]
    controls = records["controls"]

    control = None
    if args.control_id and args.control_status:
        for existing in controls:
            if existing.get("control_id") == args.control_id:
                existing["status"] = args.control_status
                existing["updated_at"] = iso_now()
                existing["resolved_by_run_id"] = run_id if args.control_status == "resolved" else existing.get("resolved_by_run_id")
                existing["resolution_evidence_id"] = evidence_id or existing.get("resolution_evidence_id", "")
                control = existing
                break
    if args.control_risk:
        cid = control_id(args.pathway, args.control_risk, args.work_id)
        control = {
            "control_id": cid,
            "work_id": args.work_id,
            "source_pathway": args.pathway,
            "risk": args.control_risk,
            "target_pathways": [p.strip() for p in (args.target_pathways or "").split(",") if p.strip()],
            "status": args.control_status or "open",
            "created_at": iso_now(),
            "updated_at": iso_now(),
            "created_by_run_id": run_id,
            "evidence_id": evidence_id,
            "evidence_path": evidence_path,
        }
        controls = [c for c in controls if c.get("control_id") != cid] + [control]

    write_ndjson(paths.pathway_runs_path, all_runs)
    write_ndjson(paths.pathway_measurements_path, all_measurements)
    write_ndjson(paths.controls_path, controls)
    if item:
        update_work_item(paths, args.work_id, last_pathway=args.pathway, last_run_id=run_id)
    dashboard = build_daily_dashboard(paths)
    return {"records": [run, measurement] + ([control] if control else []), "findings": findings, "run_id": run_id, "dashboard": str(paths.daily_dashboard_path), "daily": dashboard}


def run_work_close(args, paths):
    if not args.work_id:
        return {
            "findings": [finding(
                "work-close-missing-work-id",
                "daily-work",
                "warn",
                "work-close requires --work-id.",
                [line_evidence(paths.work_items_path)],
                "Pass the work_id created by work-start.",
                "static",
                "high",
            )],
            "records": [],
        }
    summary = work_status_summary(paths, args.work_id)
    findings = []
    if summary["closeout_readiness"] != "ready":
        findings.append(finding(
            "work-close-not-ready",
            "daily-work",
            "warn",
            f"Work item {args.work_id} is not ready to close.",
            [line_evidence(paths.work_items_path, source="; ".join(summary.get("warnings", [])))],
            "Resolve open controls, stale measurements, and missing evidence before closeout.",
            "static",
            "high",
        ))
        dashboard = build_daily_dashboard(paths)
        return {"records": [summary], "findings": findings, "closed": False, "dashboard": str(paths.daily_dashboard_path), "daily": dashboard}
    item = update_work_item(paths, args.work_id, status="closed", closed_at=iso_now(), closeout_readiness="ready")
    dashboard = build_daily_dashboard(paths)
    return {"records": [item], "findings": [], "closed": True, "dashboard": str(paths.daily_dashboard_path), "daily": dashboard}


def run_work_daily(args, paths):
    dashboard = build_daily_dashboard(paths)
    md_path, html_path = render_daily_work_report(paths, dashboard)
    return {
        "records": dashboard.get("work_summaries", []),
        "findings": [],
        "dashboard": str(paths.daily_dashboard_path),
        "report": str(md_path),
        "html": str(html_path),
        "summary": {
            "active": dashboard.get("active_count", 0),
            "closed": dashboard.get("closed_count", 0),
            "stuck": len(dashboard.get("stuck_work_items", [])),
            "open_controls": len(dashboard.get("top_open_controls", [])),
        },
    }


def resolve_project_path(args, paths):
    raw = (args.project or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    if p.exists():
        return str(p.resolve())
    candidate = Path(paths.projects_root).expanduser() / raw
    if candidate.exists():
        return str(candidate.resolve())
    return str(p)


def pathway_for_finding(item):
    explicit = item.get("pathway")
    if explicit in PATHWAY_ORDER:
        return explicit
    fid = str(item.get("id", "")).lower()
    if fid.startswith("local:"):
        fid = fid[len("local:"):]
    for prefix, pathway in GUARD_PREFIX_PATHWAY.items():
        if fid.startswith(prefix):
            return pathway
    haystack = f"{item.get('id', '')} {item.get('message', '')} {item.get('workflow', '')}".lower()
    for pathway, keywords in FINDING_PATHWAY_KEYWORDS:
        if any(kw in haystack for kw in keywords):
            return pathway
    return FINDING_WORKFLOW_PATHWAY.get(item.get("workflow", ""), "implementation")


def _finding_in_project(f, project_path, project_name):
    """True if a finding's evidence belongs to this project. Uses path-prefix and
    path-component matching (not bare substring) so project 'ops' does not match
    '/x/consult-ops/y'."""
    prefix = project_path.rstrip("/") + "/"
    for e in (f.get("evidence", []) or []):
        p = str(e.get("path", ""))
        if p == project_path or p.startswith(prefix):
            return True
        if project_name and project_name in p.split("/"):
            return True
    return False


def project_scoped_findings(paths, project_path, project_name):
    findings = read_ndjson(paths.findings_path)
    return [f for f in findings if _finding_in_project(f, project_path, project_name)]


LOCAL_SEVERITY_ALIASES = {
    "error": ("crit", "high", "p0", "blocker", "error", "fail"),
    "warn": ("med", "p1", "warn", "major", "moderate"),
}


def normalize_local_severity(raw):
    s = str(raw).lower()
    for sev, tokens in LOCAL_SEVERITY_ALIASES.items():
        if any(t in s for t in tokens):
            return sev
    return "info"


def looks_like_finding(rec):
    return isinstance(rec, dict) and ("severity" in rec or "priority" in rec) and any(
        k in rec for k in ("id", "message", "title", "description", "rule")
    )


def records_from_file(path):
    """Pull finding-shaped records from a json/ndjson/jsonl file. Caps the read."""
    text = safe_read_text(path, max_bytes=2_000_000)
    out = []
    if path.suffix.lower() in (".ndjson", ".jsonl"):
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if looks_like_finding(rec):
                out.append(rec)
        return out
    try:
        data = json.loads(text)
    except Exception:
        return out
    candidates = []
    if isinstance(data, list):
        candidates = data
    elif isinstance(data, dict):
        for key in ("findings", "items", "results", "issues"):
            if isinstance(data.get(key), list):
                candidates = data[key]
                break
    return [rec for rec in candidates if looks_like_finding(rec)]


def review_generated_at(path):
    """Return the generated_at datetime for a review-stack findings file, else None.

    None means "not a review file" (ingest normally). A datetime lets the caller
    decide staleness. Malformed/unparseable timestamps return None (ingest, don't punish)."""
    if path.name != "latest-findings.json":
        return None
    try:
        data = json.loads(safe_read_text(path, max_bytes=2_000_000))
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("source") != "review-stack":
        return None
    return parse_ts(data.get("generated_at"))


def project_local_findings(project_path, max_files=40, max_records=200):
    """Ingest project-local signals (.planning findings + STATE.md freshness).

    Returns (findings_list, source_count). Each finding carries an explicit
    `pathway` when the source declared one, so it routes deterministically.
    """
    root = Path(project_path).expanduser()
    planning = root / ".planning"
    findings = []
    source_count = 0
    if planning.exists():
        files = []
        for pattern in ("*.json", "*.ndjson", "*.jsonl"):
            files.extend(sorted(planning.rglob(pattern)))
        for fpath in files[:max_files]:
            if len(findings) >= max_records:
                break
            gen_at = review_generated_at(fpath)
            if gen_at is not None and (utc_now() - gen_at).days > REVIEW_STALE_DAYS:
                age = (utc_now() - gen_at).days
                f = finding(
                    "local:stale-review",
                    "project-local",
                    "warn",
                    f"Review findings in {fpath.name} are {age} days stale and were not ingested.",
                    [line_evidence(fpath, source=Path(project_path).name)],
                    "Re-run review-stack to refresh findings before trusting this ranking.",
                    "static",
                    "medium",
                )
                f["pathway"] = "quality"
                findings.append(f)
                continue
            for rec in records_from_file(fpath):
                if len(findings) >= max_records:
                    break
                source_count += 1
                fid = rec.get("id") or rec.get("rule") or "local-finding"
                msg = rec.get("message") or rec.get("title") or rec.get("description") or ""
                sev = normalize_local_severity(rec.get("severity", rec.get("priority", "info")))
                f = finding(
                    f"local:{fid}",
                    "project-local",
                    sev,
                    str(msg)[:240],
                    [line_evidence(fpath, source=Path(project_path).name)],
                    "",
                    "static",
                    "low",
                )
                explicit = rec.get("pathway") or rec.get("dimension") or rec.get("category")
                if explicit in PATHWAY_ORDER:
                    f["pathway"] = explicit
                findings.append(f)
    # Present-state truth signal (koho doctrine: .planning/STATE.md is the truth).
    state = planning / "STATE.md"
    if planning.exists() and not state.exists() and len(findings) < max_records:
        f = finding(
            "local:no-state-md",
            "project-local",
            "warn",
            "No .planning/STATE.md present-state truth for this project.",
            [line_evidence(planning, source=Path(project_path).name)],
            "Record current state so planning does not rediscover context.",
            "static",
            "medium",
        )
        f["pathway"] = "govern"
        findings.append(f)
    elif state.exists():
        ts = state.stat().st_mtime
        age_days = (utc_now().timestamp() - ts) / 86400
        if age_days > 30 and len(findings) < max_records:
            f = finding(
                "local:stale-state-md",
                "project-local",
                "warn",
                f".planning/STATE.md is {int(age_days)} days stale.",
                [line_evidence(state, source=Path(project_path).name)],
                "Refresh present-state truth before planning the next slice.",
                "static",
                "medium",
            )
            f["pathway"] = "govern"
            findings.append(f)
    return findings, source_count


def active_work_for_project(paths, project_path, project_name):
    items = read_ndjson(paths.work_items_path)
    matches = [
        w for w in items
        if w.get("status", "active") != "closed"
        and (w.get("project") == project_path or w.get("project_name") == project_name)
    ]
    return sorted(matches, key=lambda w: w.get("updated_at", ""), reverse=True)


# Error findings escalate so a cluster of live fires can out-rank the foundation gates
# (research 100 / govern 80): 1 error stays below govern (foundation-first holds), 2 ties it,
# 3+ overrides everything — a pile of P0s beats "pin your metric / do research first".
# Distinct from the module-level SEVERITY_WEIGHT (compare/improvement) — this one is pathway-scoring only.
PATHWAY_SEVERITY_WEIGHT = {"critical": 40, "error": 40, "warn": 5, "info": 1}


def score_pathways(paths, project_path, project_name, scoped_findings, work_summaries):
    """Score each of the 11 pathways by how much it is the current constraint.

    Higher score = more urgent to run next. Foundation gates (research, govern)
    get a large boost when no run exists for the project, encoding the Karpathy
    rule: never start a serious plan from vague context.
    """
    scores = {p: {"pathway": p, "score": 0, "reasons": []} for p in PATHWAY_ORDER}

    def bump(pathway, amount, reason):
        if pathway not in scores:
            return
        scores[pathway]["score"] += amount
        scores[pathway]["reasons"].append(reason)

    # Pathways already exercised for this project's active work.
    seen = set()
    open_controls = []
    stale_count = 0
    missing_evidence_count = 0
    for summary in work_summaries:
        seen.update(summary.get("pathway_coverage", {}).get("seen", []))
        open_controls.extend(summary.get("open_controls", []))
        stale_count += len(summary.get("stale_measurements", []))
        missing_evidence_count += len(summary.get("missing_evidence", []))

    # Foundation gates first.
    if "research" not in seen:
        bump("research", 100, "Foundation gate: no verified research dossier for this project — cannot plan from vague context.")
    if "govern" not in seen:
        bump("govern", 80, "Foundation gate: no recorded decision/metric for this project's active work.")

    # Open controls are an explicit downstream-to-upstream signal.
    for c in open_controls:
        targets = c.get("target_pathways") or [c.get("source_pathway")]
        risk = c.get("risk", "open control")
        for t in targets:
            bump(t, 50, f"Open control [{c.get('control_id', '?')}]: {risk}")

    # Project-scoped findings, routed to pathways and weighted by severity.
    for f in scoped_findings:
        pathway = pathway_for_finding(f)
        weight = PATHWAY_SEVERITY_WEIGHT.get(f.get("severity", "info"), 1)
        bump(pathway, weight, f"{f.get('severity', 'info')} finding [{f.get('id', '?')}]: {f.get('message', '')[:80]}")

    # Verification health gaps push quality.
    if stale_count:
        bump("quality", 5 * stale_count, f"{stale_count} stale measurement(s) need re-verification.")
    if missing_evidence_count:
        bump("quality", 4 * missing_evidence_count, f"{missing_evidence_count} measurement(s) lack evidence.")

    # Missing core pathways (never run) get a small completeness nudge.
    for p in PATHWAY_ORDER:
        if p not in seen and p not in ("research", "govern"):
            bump(p, 4, "Pathway has no run for this project's active work yet.")

    ranked = sorted(scores.values(), key=lambda s: (-s["score"], PATHWAY_ORDER.index(s["pathway"])))
    return ranked


def karpathy_card(pathway, project_name, goal):
    doctrine = PATHWAY_DOCTRINE.get(pathway, {})
    return {
        "pathway": pathway,
        "title": doctrine.get("title", pathway),
        "spec_decision": doctrine.get("decision", ""),
        "verifier_good": doctrine.get("good", ""),
        "real_artifact": doctrine.get("artifact", ""),
        "one_percent_move": doctrine.get("move", ""),
        "skill": doctrine.get("skill", ""),
        "goal": goal or f"Advance {project_name} via the {pathway} pathway",
    }


def render_pathway_next_report(paths, project_name, recommended, ranked, card, work_id, next_command, has_context, sources=None):
    sources = sources or {}
    rec_pathway = recommended["pathway"]
    lines = [
        f"# Next-Best Pathway — {project_name}",
        "",
        f"Generated: {iso_now()}",
        "",
        f"**Recommended pathway: `{rec_pathway}` — {card['title']}**",
        "",
        "```mermaid",
        "flowchart LR",
        '  A["Gather state"] --> B["Score 11 pathways"]',
        '  B --> C["Apply foundation-first order"]',
        f'  C --> D["Run: {rec_pathway}"]',
        '  D --> E["Log measurement against work_id"]',
        "```",
        "",
        "## Karpathy path forward",
        "",
        f"- **Spec (the decision):** {card['spec_decision']}",
        f"- **Verifier (what good looks like):** {card['verifier_good']}",
        f"- **Real artifact (proof):** {card['real_artifact']}",
        f"- **Skill to run:** `{card['skill']}`",
        "",
        "## The 1% operator move",
        "",
        f"> {card['one_percent_move']}",
        "",
        "## Cohesion — log this pathway against the shared work_id",
        "",
        f"Work ID: `{work_id}`" if work_id else "No active work item yet — start one so every pathway measures against the same ID:",
        "",
        "```bash",
        next_command,
        "```",
        "",
        "## Ranked pathways (sorted by current constraint)",
        "",
        "| Rank | Pathway | Score | Top reason |",
        "|---|---|---|---|",
    ]
    for i, s in enumerate(ranked, 1):
        reason = s["reasons"][0] if s["reasons"] else "no active signal"
        lines.append(f"| {i} | `{s['pathway']}` | {s['score']} | {reason} |")
    lines += [
        "",
        "## Signal sources",
        "",
        f"- Operating-layer findings (env-scoped): {sources.get('operating_layer', 0)}",
        f"- Project-local findings (`.planning/`): {sources.get('project_local', 0)}",
    ]
    if not has_context:
        lines += [
            "",
            "> Note: no project-scoped findings or work items were found. Run `operating-layer all` to refresh "
            "evidence, then `work-start` to open a tracked outcome before relying on this ranking.",
        ]
    lines += [
        "",
        "## Plain-English Summary",
        "",
        f"**What we're building** — A way to ask one project, \"{project_name}, what should I work on next to move you forward at the highest level?\" and get a single, defensible answer.",
        "",
        "**Why this piece** — Until now the operating layer could tell us what was wrong across everything, but not which engineering move to make next for one specific app. This closes that gap.",
        "",
        f"**The surprise** — The strongest signal isn't always the loudest bug; it's often a missing foundation. Here the system recommends **{card['title'].lower()}** first.",
        "",
        "**The real problem I caught** — Pathways used to leave scattered notes. Now the recommendation hands you the exact command to log your work against one shared ID, so the next pathway can see what the last one did.",
        "",
        "**Where we are right now** — This is read-only advice. It reads the project's current state and ranks options. It changes nothing on its own and sends nothing anywhere.",
        "",
        f"**The one thing left** — Run the recommended move ({card['one_percent_move']}) and log it against the work ID. Fully reversible; nothing is published.",
    ]
    return "\n".join(lines) + "\n"


def run_pathway_next(args, paths):
    project_path = resolve_project_path(args, paths)
    if not project_path:
        return {
            "findings": [finding(
                "pathway-next-missing-project",
                "pathway-next",
                "warn",
                "pathway-next requires --project (a path or a project name under the projects root).",
                [line_evidence(paths.portfolio_path)],
                "Run `pathway-next --project consult-ops` or `--project /full/path`.",
                "static",
                "high",
            )],
            "records": [],
        }
    project_name = Path(project_path).name
    context = current_work_context(paths, project_path)
    ol_findings = project_scoped_findings(paths, project_path, project_name)
    local_findings, local_source_count = project_local_findings(project_path)
    scoped_findings = ol_findings + local_findings
    sources = {"operating_layer": len(ol_findings), "project_local": len(local_findings)}
    work_items = active_work_for_project(paths, project_path, project_name)
    work_summaries = [work_status_summary(paths, w.get("work_id")) for w in work_items]
    ranked = score_pathways(paths, project_path, project_name, scoped_findings, work_summaries)
    recommended = ranked[0]
    card = karpathy_card(recommended["pathway"], project_name, args.goal)

    work_id = work_items[0].get("work_id") if work_items else None
    if work_id:
        next_command = (
            f"python3 ~/.claude/scripts/operating-layer.py work-log \\\n"
            f"  --work-id {work_id} \\\n"
            f"  --pathway {recommended['pathway']} --kind verify \\\n"
            f"  --evidence <path-to-real-artifact> --gate {recommended['pathway']}-gate"
        )
    else:
        goal_text = args.goal or f"Advance {project_name} via {recommended['pathway']}"
        next_command = (
            f"python3 ~/.claude/scripts/operating-layer.py work-start \\\n"
            f"  --project {project_path} \\\n"
            f"  --goal \"{goal_text}\""
        )

    has_context = bool(scoped_findings or work_items)
    md_path = dated_artifact_path(paths, f"pathway-next-{safe_slug(project_name)}")
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_pathway_next_report(
        paths, project_name, recommended, ranked, card, work_id, next_command, has_context, sources))
    render_html(md_path, html_path)

    # Log the recommendation so pathway-metric can measure follow-through (govern metric).
    recommendations = read_ndjson(paths.recommendations_path)
    recommendations.append({
        "recommendation_id": f"REC-{safe_slug(project_name)}-{recommended['pathway']}-{len(recommendations) + 1:04d}",
        "project": project_name,
        "pathway": recommended["pathway"],
        "work_id": work_id or "",
        "timestamp": iso_now(),
    })
    write_ndjson(paths.recommendations_path, recommendations)

    rec_finding = finding(
        "pathway-next-recommendation",
        "pathway-next",
        "info",
        f"Next-best pathway for {project_name}: {recommended['pathway']} ({card['title']}) "
        f"— {recommended['reasons'][0] if recommended['reasons'] else 'lowest-coverage pathway'}.",
        [line_evidence(md_path, source=project_name)],
        card["one_percent_move"],
        "static",
        "high",
    )
    return {
        "records": ranked,
        "findings": [rec_finding],
        "project": project_name,
        "recommended_pathway": recommended["pathway"],
        "karpathy_card": card,
        "one_percent_move": card["one_percent_move"],
        "work_id": work_id,
        "next_command": next_command,
        "ranked": ranked,
        "signal_sources": sources,
        "report": str(md_path),
        "html": str(html_path),
    }


def run_ingest_review(args, paths):
    """Persist a review-stack --json finding pool into <project>/.planning/review/
    so pathway-next auto-discovers it. Overwrites latest-findings.json (current-state)."""
    project_path = resolve_project_path(args, paths)
    if not project_path:
        return {
            "findings": [finding(
                "ingest-review-missing-project",
                "ingest-review",
                "warn",
                "ingest-review requires --project (a path or a project name under the projects root).",
                [line_evidence(paths.portfolio_path)],
                "Run `ingest-review --project <name> --input <review.json>` (or pipe via stdin).",
                "static",
                "high",
            )],
            "records": [],
        }
    if not Path(project_path).exists():
        return {
            "findings": [finding(
                "ingest-review-unknown-project",
                "ingest-review",
                "warn",
                f"ingest-review target project does not exist: {project_path}",
                [line_evidence(paths.portfolio_path)],
                "Pass an existing project path/name so findings are not written into a typo'd tree.",
                "static",
                "high",
            )],
            "records": [],
        }
    if args.input and args.input != "-":
        raw = safe_read_text(Path(args.input).expanduser(), max_bytes=5_000_000)
    else:
        raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return {
            "findings": [finding(
                "ingest-review-bad-json",
                "ingest-review",
                "warn",
                "ingest-review could not parse the review-stack JSON input.",
                [line_evidence(Path(project_path))],
                "Pass review-stack `--json` output as --input <file> or on stdin.",
                "static",
                "high",
            )],
            "records": [],
        }
    raw_findings = []
    if isinstance(data, list):
        raw_findings = data
    elif isinstance(data, dict):
        for key in ("findings", "items", "results", "issues"):
            if isinstance(data.get(key), list):
                raw_findings = data[key]
                break

    normalized = []
    by_pathway = {}
    for rec in raw_findings:
        if not looks_like_finding(rec):
            continue
        fid = str(rec.get("id") or rec.get("rule") or "finding")
        msg = rec.get("message") or rec.get("title") or rec.get("description") or ""
        sev = normalize_local_severity(rec.get("severity", rec.get("priority", "info")))
        pathway = pathway_for_finding({"id": fid, "message": msg, "pathway": rec.get("pathway")})
        out = {
            "id": fid,
            "message": str(msg)[:240],
            "severity": sev,
            "pathway": pathway,
            "file": str(rec.get("file", "")),
            "line": rec.get("line", ""),
            "confidence": rec.get("confidence", "medium"),
            "source": "review-stack",
        }
        normalized.append(out)
        by_pathway[pathway] = by_pathway.get(pathway, 0) + 1

    out_path = Path(project_path) / ".planning" / "review" / "latest-findings.json"
    write_json(out_path, {
        "generated_at": iso_now(),
        "source": "review-stack",
        "project": Path(project_path).name,
        "finding_count": len(normalized),
        "by_pathway": by_pathway,
        "findings": normalized,
    })
    return {
        "records": normalized,
        "findings": [],
        "project": Path(project_path).name,
        "written": str(out_path),
        "finding_count": len(normalized),
        "by_pathway": by_pathway,
    }


def run_pathway_metric(args, paths):
    """Recommendation-action rate (the pathway system's govern metric):
    of pathway-next recommendations, the fraction that got a matching work-log run
    (same project+pathway) within --window-days. <gate-target means dashboard, not operating layer."""
    window_days = args.window_days if args.window_days is not None else 1
    gate_target = args.gate_target if args.gate_target is not None else 0.5
    recs = read_ndjson(paths.recommendations_path)
    runs = read_ndjson(paths.pathway_runs_path)
    items = read_ndjson(paths.work_items_path)
    project_of = {w.get("work_id"): w.get("project_name") for w in items if w.get("work_id")}

    def acted_on(rec):
        rec_ts = parse_ts(rec.get("timestamp"))
        for run in runs:
            if run.get("pathway") != rec.get("pathway"):
                continue
            same_work = rec.get("work_id") and run.get("work_id") == rec.get("work_id")
            same_proj = bool(rec.get("project")) and project_of.get(run.get("work_id")) == rec.get("project")
            if not (same_work or same_proj):
                continue
            run_ts = parse_ts(run.get("timestamp"))
            if rec_ts and run_ts:
                delta = (run_ts - rec_ts).total_seconds()
                if 0 <= delta <= window_days * 86400:
                    return True
        return False

    by_pathway = {}
    acted = 0
    total = 0
    skipped = 0
    for rec in recs:
        if parse_ts(rec.get("timestamp")) is None:
            skipped += 1  # can't evaluate the follow-through window; exclude from numerator AND denominator
            continue
        total += 1
        hit = acted_on(rec)
        acted += 1 if hit else 0
        bucket = by_pathway.setdefault(rec.get("pathway", "?"), {"total": 0, "acted_on": 0})
        bucket["total"] += 1
        bucket["acted_on"] += 1 if hit else 0
    for bucket in by_pathway.values():
        bucket["rate"] = round(bucket["acted_on"] / bucket["total"], 3) if bucket["total"] else 0.0

    rate = round(acted / total, 3) if total else 0.0
    metric = {
        "metric": "recommendation-action rate",
        "generated_at": iso_now(),
        "window_days": window_days,
        "total_recommendations": total,
        "skipped_no_timestamp": skipped,
        "acted_on": acted,
        "rate": rate,
        "gate_target": gate_target,
        "gate_pass": (total > 0 and rate >= gate_target),
        "by_pathway": by_pathway,
    }
    write_json(paths.operator_intel / "pathway-metric.json", metric)
    return {
        "records": recs,
        "findings": [],
        "metric": metric,
        "written": str(paths.operator_intel / "pathway-metric.json"),
    }


def run_improve(args, paths):
    findings = read_ndjson(paths.findings_path)
    if not findings:
        scan = run_all(args, paths)
        findings = scan.get("findings", [])
    items, md_path, html_path = write_improvement_artifacts(paths, findings)
    return {
        "records": items,
        "findings": [],
        "report": str(md_path),
        "html": str(html_path),
        "queue": str(paths.improvement_queue_path),
    }


def run_compare(args, paths):
    trend = trend_from_history(paths)
    md_path, html_path = write_compare_artifacts(paths, trend)
    return {
        "records": trend.get("added", []) + trend.get("resolved", []) + trend.get("worsened", []),
        "findings": [],
        "report": str(md_path),
        "html": str(html_path),
        "compare": str(paths.compare_path),
        "summary": trend.get("summary", {}),
    }


def run_all(args, paths):
    mkdir(paths.operator_intel)
    mkdir(paths.operator_artifacts)
    mkdir(paths.agent_cards)
    results = {}
    results["intel"] = scan_intel(args, paths, write_outputs=False)
    results["tools"] = scan_tools(args, paths, write_outputs=False)
    results["portfolio"] = scan_portfolio(args, paths, write_outputs=False)
    results["evidence"] = scan_evidence(args, paths, write_outputs=False)
    results["ai-contract"] = scan_ai_contract(args, paths, write_outputs=False)
    results["boundary"] = scan_boundary(args, paths, write_outputs=False)
    results["agent-cards"] = scan_agents(args, paths, write_outputs=True)

    all_findings = []
    for res in results.values():
        all_findings.extend(res.get("findings", []))
    if not all_findings:
        all_findings = [finding(
            "operating-layer-no-findings",
            "all",
            "info",
            "All operating-layer scans completed without findings.",
            [line_evidence(paths.output_root)],
            "Keep scheduled scans for drift monitoring.",
            "static",
            "medium",
        )]

    all_findings = unique_findings(all_findings)
    previous_history = latest_history_file(paths)
    trend = compare_findings(read_ndjson(previous_history), all_findings) if previous_history else compare_findings([], all_findings)
    trend["baseline"] = str(previous_history) if previous_history else None
    snapshot_path = save_findings_snapshot(paths, all_findings)
    trend["candidate"] = str(snapshot_path)

    write_findings(paths, all_findings)
    write_json(paths.tool_registry_path, results["tools"]["records"])
    dump_yaml_records(paths.portfolio_path, results["portfolio"]["records"])
    append_records(paths.evidence_path, results["evidence"]["records"])
    write_json(paths.operator_intel / "ai-contracts.json", results["ai-contract"]["records"])
    write_json(paths.operator_intel / "data-boundary-report.json", {
        "projects": results["boundary"]["records"],
        "generated_at": iso_now(),
    })
    write_json(paths.operator_intel / "agent-capability-cards.json", results["agent-cards"]["records"])

    improvement_items, improvement_md, improvement_html = write_improvement_artifacts(paths, all_findings)
    compare_md, compare_html = write_compare_artifacts(paths, trend)
    planning_proof = generate_planning_consumption_proof(paths, results, all_findings)
    daily_dashboard = build_daily_dashboard(paths)
    daily_md, daily_html = render_daily_work_report(paths, daily_dashboard)
    memory = memory_validation(paths)
    md_path = report_path(paths)
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_report(paths, results, memory, improvement_items, trend, planning_proof, daily_dashboard))
    render_html(md_path, html_path)
    return {
        "findings": all_findings,
        "report": str(md_path),
        "html": str(html_path),
        "memory": memory,
        "snapshot": str(snapshot_path),
        "improvement_queue": str(paths.improvement_queue_path),
        "improvement_report": str(improvement_md),
        "improvement_html": str(improvement_html),
        "compare": str(paths.compare_path),
        "compare_report": str(compare_md),
        "compare_html": str(compare_html),
        "planning_proof": planning_proof,
        "daily_dashboard": str(paths.daily_dashboard_path),
        "daily_report": str(daily_md),
        "daily_html": str(daily_html),
    }


def print_result(result, json_out=False):
    if json_out:
        print(json.dumps(redact_obj(result), indent=2, sort_keys=True))
        return
    summary = {
        "findings": len(result.get("findings", [])),
        "records": len(result.get("records", [])) if "records" in result else None,
        "report": result.get("report"),
        "html": result.get("html"),
    }
    print(json.dumps(redact_obj({k: v for k, v in summary.items() if v is not None}), indent=2, sort_keys=True))


def build_parser():
    parser = argparse.ArgumentParser(description="Operating layer workflow CLI")
    parser.add_argument("subcommand", choices=[
        "intel", "tools", "portfolio", "evidence", "ai-contract", "boundary", "agent-cards",
        "improve", "compare", "work-start", "work-status", "work-log", "work-close", "work-daily",
        "pathway-next", "ingest-review", "pathway-metric", "all"
    ])
    parser.add_argument("--claude-home", default=str(DEFAULT_CLAUDE_HOME))
    parser.add_argument("--codex-home", default=str(DEFAULT_CODEX_HOME))
    parser.add_argument("--projects-root", default=str(DEFAULT_PROJECTS_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--since-days", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check-write", help="Boundary check mode for a future write path.")
    parser.add_argument("--project", help="Project path for work-start.")
    parser.add_argument("--goal", help="User-visible outcome for work-start.")
    parser.add_argument("--work-id", help="Shared outcome identifier for daily work commands.")
    parser.add_argument("--pathway", help="Pathway name for work-log.")
    parser.add_argument("--kind", help="Run or measurement kind for work-log.")
    parser.add_argument("--evidence", help="Local evidence path for work-log.")
    parser.add_argument("--gate", help="Specific gate or measurement name for work-log.")
    parser.add_argument("--result", help="Measurement result/status for work-log.")
    parser.add_argument("--control-risk", help="Create a control from this pathway risk.")
    parser.add_argument("--control-id", help="Existing control id to update.")
    parser.add_argument("--control-status", choices=["open", "resolved"], help="Control status for creation or update.")
    parser.add_argument("--target-pathways", help="Comma-separated pathways affected by a control.")
    parser.add_argument("--stale-after-days", type=int, default=WORK_STALE_DAYS)
    parser.add_argument("--input", help="review-stack --json input file for ingest-review (or '-' / omit for stdin).")
    parser.add_argument("--window-days", type=int, help="pathway-metric: days after a recommendation to count a matching work-log as acted-on (default 1).")
    parser.add_argument("--gate-target", type=float, help="pathway-metric: minimum acted-on rate to pass the gate (default 0.5).")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = Paths(args)
    if args.subcommand == "boundary" and args.check_write:
        scan_boundary(args, paths, write_outputs=False)
        return 0
    mkdir(paths.operator_intel)
    if args.subcommand == "intel":
        result = scan_intel(args, paths)
    elif args.subcommand == "tools":
        result = scan_tools(args, paths)
    elif args.subcommand == "portfolio":
        result = scan_portfolio(args, paths)
    elif args.subcommand == "evidence":
        result = scan_evidence(args, paths)
    elif args.subcommand == "ai-contract":
        result = scan_ai_contract(args, paths)
    elif args.subcommand == "boundary":
        result = scan_boundary(args, paths)
    elif args.subcommand == "agent-cards":
        result = scan_agents(args, paths)
    elif args.subcommand == "improve":
        result = run_improve(args, paths)
    elif args.subcommand == "compare":
        result = run_compare(args, paths)
    elif args.subcommand == "work-start":
        result = run_work_start(args, paths)
    elif args.subcommand == "work-status":
        result = run_work_status(args, paths)
    elif args.subcommand == "work-log":
        result = run_work_log(args, paths)
    elif args.subcommand == "work-close":
        result = run_work_close(args, paths)
    elif args.subcommand == "work-daily":
        result = run_work_daily(args, paths)
    elif args.subcommand == "pathway-next":
        result = run_pathway_next(args, paths)
    elif args.subcommand == "ingest-review":
        result = run_ingest_review(args, paths)
    elif args.subcommand == "pathway-metric":
        result = run_pathway_metric(args, paths)
    else:
        result = run_all(args, paths)
    print_result(result, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
