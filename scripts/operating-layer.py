#!/usr/bin/env python3
"""
operating-layer.py - consolidated operating intelligence above the pathway suite.

This tool is intentionally local-first and read-only for product/client repos. It
writes only to a central output root, defaulting to ~/Projects/memory-vault. The
goal is to make the environment self-aware: logs, tools, projects, evidence,
AI/agent readiness, and client/workspace boundaries.
"""
import argparse
import ast
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


# Portable defaults — derived from $HOME (and overridable by env), never a hardcoded username, so
# the tool runs for anyone who clones it. Every default is also overridable by a CLI flag.
_HOME = Path(os.environ.get("PATHWAY_HOME") or Path.home())
DEFAULT_CLAUDE_HOME = Path(os.environ.get("CLAUDE_HOME") or (_HOME / ".claude"))
DEFAULT_CODEX_HOME = Path(os.environ.get("CODEX_HOME") or (_HOME / ".codex"))
DEFAULT_PROJECTS_ROOT = Path(os.environ.get("PROJECTS_ROOT") or (_HOME / "Projects"))


def _default_output_root():
    """Where the operator-intelligence store lives. Override with $OPERATING_LAYER_OUTPUT_ROOT.
    Otherwise reuse an existing legacy store if present (preserves continuity for an existing
    install) and fall back to a clean, neutral per-user location for a fresh clone."""
    env = os.environ.get("OPERATING_LAYER_OUTPUT_ROOT")
    if env:
        return Path(env)
    legacy = _HOME / "Projects" / "memory-vault"
    if (legacy / "operator-intelligence").exists():
        return legacy
    return _HOME / ".pathway-operating-layer"


DEFAULT_OUTPUT_ROOT = _default_output_root()
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

# === Itinerary: coverage by construction =====================================
# A "done" tier sizes the set of engineering pathways an outcome MUST cover before
# it can close. Tiers are cumulative supersets (live ⊃ demoable, production-secure ⊃
# live). The router seeds this onto the work item at START; work-close is hard-refused
# until every entry is `proved` (real artifact) or `na` (explicit reason). This is what
# turns "use every necessary pathway" from a hope into an enforced guarantee.
PATHWAY_TIERS = {
    "demoable": ["govern", "implementation", "quality"],
    "live": ["govern", "data", "implementation", "quality", "observability", "release", "docs"],
    "production-secure": [
        "research", "govern", "data", "security", "implementation",
        "quality", "observability", "techdebt", "release", "docs",
    ],
}

# Conditional pathways pulled into ANY tier when the goal's own words demand them
# (same keyword-gating idea the planning specialist-lenses use).
PATHWAY_KEYWORD_GATES = {
    "design": r"\b(ui|ux|screen|component|page|frontend|front-end|layout|form|dashboard|design|css|tailwind|figma)\b",
    "research": r"\b(new|evaluate|spike|investigate|unknown|unfamiliar|should we|which|compare|explore)\b",
    "data": r"\b(schema|migration|migrate|db|database|table|supabase|postgres|sql|index|column|boundary|tenant)\b",
}

# Canonical execution order: foundation-first, dependencies before dependents. The
# router walks the itinerary in this order so govern precedes the slice, research/data
# precede what builds on them — no skipped foundations.
PATHWAY_CANON_ORDER = [
    "govern", "research", "data", "security", "design", "implementation",
    "quality", "observability", "techdebt", "release", "docs",
]

DEFAULT_ITINERARY_TIER = "live"


def compute_itinerary(tier, goal):
    """Return the ordered required-pathway itinerary for an outcome.

    `tier` sizes the cumulative base set; keyword gates pull in design/research/data
    when the goal's own words demand them. Order is canonical (foundation-first). Every
    entry starts `required`; it becomes `proved` on a real-artifact work-log or `na`
    via work-cover, and the outcome cannot close while any entry is still `required`.
    """
    base = set(PATHWAY_TIERS.get((tier or DEFAULT_ITINERARY_TIER).lower(), PATHWAY_TIERS[DEFAULT_ITINERARY_TIER]))
    text = (goal or "").lower()
    for pathway, pattern in PATHWAY_KEYWORD_GATES.items():
        if re.search(pattern, text):
            base.add(pathway)
    ordered = [p for p in PATHWAY_CANON_ORDER if p in base]
    return [{"pathway": p, "status": "required", "reason": "", "proved_by_run": ""} for p in ordered]


def merge_itinerary(old, new):
    """Resize an itinerary to a new required set while preserving proof already earned.

    On a tier change, pathways that were already `proved`/`na` keep that status; pathways
    new to the tier come in `required`; pathways dropped by the tier fall off. A re-START
    must never silently discard coverage that was already paid for.
    """
    prior = {e.get("pathway"): e for e in (old or [])}
    new_pathways = {e["pathway"] for e in new}
    merged = []
    for entry in new:
        prev = prior.get(entry["pathway"])
        merged.append(prev if prev and prev.get("status") in ("proved", "na") else entry)
    # Never discard earned proof: a tier downgrade keeps proved/na pathways the new tier
    # dropped, as retained coverage (both critics flagged this). They no longer block
    # (proved/na), but the record of work done is preserved.
    for pathway, prev in prior.items():
        if pathway not in new_pathways and prev.get("status") in ("proved", "na"):
            merged.append(prev)
    merged.sort(key=lambda e: PATHWAY_CANON_ORDER.index(e["pathway"]) if e.get("pathway") in PATHWAY_CANON_ORDER else 99)
    return merged


def itinerary_coverage(item):
    """Return (covered_count, total, [open_required_pathways]) for a work item.

    Covered = proved or na. Open required = still owed proof. The list is foundation-
    first so the router's next pick walks dependencies in order.
    """
    itin = (item or {}).get("itinerary") or []
    covered = [e for e in itin if e.get("status") in ("proved", "na")]
    open_required = [e.get("pathway") for e in itin if e.get("status", "required") == "required"]
    open_required.sort(key=lambda p: PATHWAY_CANON_ORDER.index(p) if p in PATHWAY_CANON_ORDER else 99)
    return len(covered), len(itin), open_required


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
        "skill": "doc-coauthoring",
    },
}

# Per-pathway BEST-EXECUTION profile: the culmination of Alex's actual skills + env +
# plugins + MCP + subagents the loop should orchestrate on EXECUTE — not just the single
# card skill. Karpathy-wrapped: primary build action -> second-model critic -> real-artifact
# proof. Keyed to PATHWAY_DOCTRINE; surfaced through karpathy_card() so /pathway loop reads it.
PATHWAY_EXECUTION = {
    "research": {
        "stack": ["/research-stack --deep (primary)", "deep-research for adversarial fact-check", "/devilsadvocate to triage claims", "live-citation validation"],
        "tools": ["firecrawl MCP", "perplexity MCP", "web-search-prime + web-reader", "get-code-context-exa", "zread repo Q&A", "agent-reach", "research agent"],
    },
    "govern": {
        "stack": ["/planning-stack --deep (primary)", "/brainstorm-stack to pin the decision", "/premortem to stress it", "second-model critic on the metric"],
        "tools": ["govern.py ledger", "stakeholder-reviewer agent", "memory-vault decisions/"],
    },
    "data": {
        "stack": ["/planning-stack --tech (primary)", "supabase-patterns recipes", "verify on a real DB row"],
        "tools": ["supabase MCP", "supabase-ssh docs", "context7 schema-typed", "database-reviewer agent", "migration-guard"],
    },
    "security": {
        "stack": ["/review-stack --audit (primary)", "security-review skill", "/codex:adversarial-review (second model)", "prove the hole closed on the live surface"],
        "tools": ["security-reviewer agent", "sec- guards", "koho-guardrail + secret guards", "Vercel runtime logs"],
    },
    "release": {
        "stack": ["/ship (primary)", "/commit first", "deploy-verify on the deployed asset", "rollback rehearsal before flip"],
        "tools": ["Vercel MCP (deploy / build-logs / runtime-errors)", "feature-flag or canary", "betterstack uptime"],
    },
    "implementation": {
        "stack": ["/build-stack (primary)", "test-driven-development first", "subagent-driven-development for large slices", "/review-stack + /codex:review", "prove on served/deployed artifact"],
        "tools": ["context7 library docs", "implementer + quickfix agents", "build-error-resolver agent"],
    },
    "quality": {
        "stack": ["/review-stack (primary)", "/regression-test golden set", "eval-harness for LLM paths", "second-model critic before merge"],
        "tools": ["tester agent", "coverage gate (quality-guard)", "Langfuse / Promptfoo evals"],
    },
    "observability": {
        "stack": ["/planning-stack --tech (primary)", "wire the one signal that exposes the top failure", "alert on the failure mode", "runbook delta"],
        "tools": ["betterstack MCP", "sentry MCP + sentry-cli + seer", "Langfuse LLM traces"],
    },
    "techdebt": {
        "stack": ["/build-stack (primary)", "/simplify", "deletion before abstraction", "/review-stack to verify"],
        "tools": ["refactor-cleaner agent", "knip / depcheck / ts-prune", "tool-registry canonical-role map"],
    },
    "design": {
        "stack": ["/design-stack --refactor (primary)", "ua-ux for build", "ua-ux-critique before ship", "token-conformance + a11y gate"],
        "tools": ["Figma MCP", "pencil MCP", "design-library.json + design-vault", "brand-system-extractor agent", "DESIGN.md lint"],
    },
    "docs": {
        "stack": ["doc-coauthoring (primary, authors in place, no commit)", "ADR / runbook convention", "verify the doc matches reality"],
        "tools": ["docs/adr + docs/runbooks templates", "memory-vault handoffs (source, not substitute)"],
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


def _atomic_write(path, write_fn):
    """Write atomically: fill a tempfile in the same directory, fsync, then os.replace onto the
    target. A process killed mid-write leaves the original intact instead of truncating the store
    to zero records (the corruption mode a dual-critic audit flagged). os.replace is atomic on the
    same filesystem. Note: this prevents corruption/torn writes, not lost updates from two
    concurrent read-modify-write cycles — single-operator use, so that race is out of scope here."""
    p = Path(path)
    mkdir(p.parent)
    tmp = p.parent / f".{p.name}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            write_fn(fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    finally:
        if tmp.exists():
            tmp.unlink()


def append_records(path, records):
    def _w(fh):
        for rec in records:
            fh.write(json.dumps(redact_obj(rec), sort_keys=True) + "\n")
    _atomic_write(path, _w)


def write_json(path, obj):
    def _w(fh):
        json.dump(redact_obj(obj), fh, indent=2, sort_keys=True)
        fh.write("\n")
    _atomic_write(path, _w)


def write_text(path, text):
    _atomic_write(path, lambda fh: fh.write(redact(text)))


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
        self.pathway_trust_path = self.operator_intel / "pathway-trust.json"
        self.proofs_path = self.operator_intel / "proofs.ndjson"
        self.pathway_run_plans_path = self.operator_intel / "pathway-run-plans.ndjson"
        self.pathway_decisions_path = self.operator_intel / "pathway-decisions.ndjson"
        self.learning_candidates_path = self.operator_intel / "learning-candidates.ndjson"
        self.evaluations_path = self.operator_intel / "pathway-evaluations.ndjson"
        self.portfolio_next_path = self.operator_intel / "portfolio-next.json"
        self.rule_map_path = self.operator_intel / "rule-map.json"
        self.cockpit_path = self.operator_intel / "cockpit.json"
        self.pfos_cockpit_path = self.operator_intel / "pfos-cockpit.json"


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


def proof_id_for(evidence_path, work_id="", pathway="", proof_type="", recommendation_id=""):
    basis = "|".join(str(p) for p in (evidence_id_for_path(evidence_path), work_id, pathway, proof_type, recommendation_id))
    return f"P-{sha_text(basis, 12)}"


def upsert_proof(paths, proof):
    proofs = [p for p in read_ndjson(paths.proofs_path) if p.get("proof_id") != proof.get("proof_id")]
    proofs.append(proof)
    write_ndjson(paths.proofs_path, proofs)
    return proofs


def proof_is_verified(proof):
    """Keystone: a proof counts as REAL verification ONLY when a re-executed verifier exited 0
    on a non-failing result. Free-text attestation (a --verified-by string) and bare human
    attestation (a --reviewer name) are claims, not verifications — a name is not a verifiable
    receipt, so it cannot prove on its own (a dual-critic pass caught --reviewer as the same
    forgery under a different flag). Only `executed` proves; `signed`/`attested` are recorded for
    accountability but never flip a pathway to `proved` or raise the autonomy proof rate. This is
    what makes `proved` mean a verification actually passed. (Verifiable human sign-off — a real
    signature/approval receipt — is a future strengthening of the `signed` tier.)"""
    if not isinstance(proof, dict):
        return False
    if str(proof.get("result", "")).strip().lower() in ("fail", "failed", "error", "missing_evidence"):
        return False
    return proof.get("verifier_strength") == "executed" and proof.get("exit_code") == 0


def sha256_file(path):
    """Full-file SHA-256 (streamed), so the recorded artifact_sha256 binds the WHOLE artifact."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def run_verifier_command(command, cwd, timeout=120):
    """Re-execute an operator-supplied verifier command; return (exit_code, stdout_sha256). The
    command comes from the operator/agent at the CLI — the same trust boundary as running it in
    their own shell — so shell=True is acceptable; it is never fed untrusted input. Fail-closed:
    a command we cannot run returns a non-zero code, so it cannot prove."""
    try:
        proc = subprocess.run(command, shell=True, cwd=cwd or None, capture_output=True,
                              text=True, timeout=timeout)
        return proc.returncode, hashlib.sha256((proc.stdout or "").encode("utf-8", "replace")).hexdigest()
    except Exception:
        return 1, ""


def build_proof_record(args, work_item=None, run_id="", measurement_id_value=""):
    evidence_path = str(Path(args.evidence).expanduser()) if args.evidence else ""
    if not evidence_path or not Path(evidence_path).exists():
        return None, finding(
            "proof-add-missing-evidence",
            "proof-registry",
            "warn",
            "Proof registry requires --evidence pointing at an existing local artifact.",
            [line_evidence(evidence_path or "<missing>")],
            "Pass a real Markdown, JSON, screenshot, report, test output, or other verification artifact.",
            "static",
            "high",
        )
    proof_type = args.proof_type or "artifact"
    project_path = str(Path(args.project).expanduser()) if getattr(args, "project", None) else ""
    project_name = Path(project_path).name if project_path else ""
    if work_item:
        project_path = work_item.get("project", project_path)
        project_name = work_item.get("project_name", project_name)
    # Keystone: classify HOW the artifact was verified. `executed` = a re-run command (record its
    # exit code + stdout hash); `signed` = a named human reviewer over a hashed artifact; otherwise
    # `attested` = a bare --verified-by string, which is a claim, not a verification.
    reviewer = (getattr(args, "reviewer", None) or "").strip()
    verify_cmd = getattr(args, "verify_cmd", None)
    artifact_sha256 = sha256_file(evidence_path)
    verifier_strength, exit_code, verify_stdout_sha256, verify_command = "attested", None, "", ""
    if verify_cmd:
        verifier_strength, verify_command = "executed", verify_cmd
        exit_code, verify_stdout_sha256 = run_verifier_command(verify_cmd, project_path or str(Path(evidence_path).parent))
    elif reviewer:
        verifier_strength = "signed"
    proof = {
        "proof_id": proof_id_for(evidence_path, args.work_id or "", args.pathway or "", proof_type, args.recommendation_id or ""),
        "timestamp": iso_now(),
        "proof_type": proof_type,
        "evidence_id": evidence_id_for_path(evidence_path),
        "evidence_path": evidence_path,
        "work_id": args.work_id or "",
        "pathway": args.pathway or "",
        "gate": args.gate or args.kind or "",
        "result": args.result or "present",
        "stale_after_days": args.stale_after_days,
        "verified_by": args.verified_by or "",
        "verifier_strength": verifier_strength,
        "verify_command": verify_command,
        "exit_code": exit_code,
        "verify_stdout_sha256": verify_stdout_sha256,
        "artifact_sha256": artifact_sha256,
        "reviewer": reviewer,
        "recommendation_id": args.recommendation_id or "",
        "run_id": run_id,
        "measurement_id": measurement_id_value,
        "project": project_name,
        "project_path": project_path,
        "source": "operating-layer proof registry",
    }
    return proof, None


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
    covered, total, itinerary_open = itinerary_coverage(item)
    # Observability (Gap A): a required pathway that already has a run logged is "logged
    # but unverified" — evidence was recorded without a named verifier, so it didn't meet
    # the sufficiency bar. Surfacing it tells the operator WHY a pathway isn't proved
    # rather than leaving it indistinguishable from never-started.
    run_pathways = {r.get("pathway") for r in runs}
    unverified = [p for p in itinerary_open if p in run_pathways]
    # The coverage gate: an outcome is NOT ready while any itinerary pathway is still
    # owed proof. work-close reads this readiness, so it inherits the refusal for free.
    ready = bool(item and runs and not open_controls and not missing_evidence and not stale and not itinerary_open)
    return {
        "work_item": item,
        "runs": runs,
        "measurements": measurements,
        "controls": controls,
        "tier": (item or {}).get("tier", ""),
        "itinerary": (item or {}).get("itinerary", []),
        "itinerary_coverage": {"covered": covered, "total": total, "open": itinerary_open, "logged_unverified": unverified},
        "pathway_coverage": {
            "seen": pathways_seen,
            "missing_core": missing_core_pathways,
            "count": len(pathways_seen),
        },
        "missing_evidence": missing_evidence,
        "stale_measurements": stale,
        "open_controls": open_controls,
        "closeout_readiness": "ready" if ready else "not_ready",
        "warnings": work_warnings(item, runs, measurements, open_controls, stale, itinerary_open),
    }


def work_warnings(item, runs, measurements, open_controls, stale, itinerary_open=None):
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
    if itinerary_open:
        warnings.append(
            f"{len(itinerary_open)} required pathways still need proof or an explicit N/A: "
            + ", ".join(itinerary_open) + "."
        )
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


def explicit_runner_integrity(test_path):
    """Static check: every module-level test_* function is present in main()'s tests list."""
    try:
        source = safe_read_text(test_path, max_bytes=2_000_000)
        tree = ast.parse(source)
    except Exception as exc:
        return {"name": "operating_layer_test runner integrity", "status": "fail", "summary": str(exc)}

    discovered = {
        node.name for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }
    registered = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "main":
            continue
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Assign):
                if not any(isinstance(t, ast.Name) and t.id == "tests" for t in stmt.targets):
                    continue
                if isinstance(stmt.value, ast.List):
                    for elt in stmt.value.elts:
                        if isinstance(elt, ast.Name):
                            registered.add(elt.id)
    missing = sorted(discovered - registered)
    status = "fail" if missing else "pass"
    return {
        "name": "operating_layer_test runner integrity",
        "status": status,
        "summary": "all test_* callables registered" if not missing else f"missing: {', '.join(missing)}",
        "missing": missing,
        "discovered": len(discovered),
        "registered": len(registered),
    }


def run_trust_command(name, cmd, budget_sec):
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=max(20, int(budget_sec * 4)))
        elapsed = time.time() - t0
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "status": "fail",
            "elapsed_sec": round(time.time() - t0, 2),
            "budget_sec": budget_sec,
            "summary": f"timed out: {exc}",
        }
    status = "pass"
    if proc.returncode != 0:
        status = "fail"
    elif elapsed > budget_sec:
        status = "warn"
    return {
        "name": name,
        "status": status,
        "elapsed_sec": round(elapsed, 2),
        "budget_sec": budget_sec,
        "returncode": proc.returncode,
        "summary": (
            "ok" if status == "pass"
            else f"elapsed {elapsed:.2f}s exceeds budget {budget_sec:.2f}s" if status == "warn"
            else (proc.stderr or proc.stdout or "command failed")[:500]
        ),
    }


def aggregate_trust_status(checks):
    statuses = {c.get("status") for c in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def render_pathway_trust_report(result):
    lines = [
        "# Pathway Trust Report",
        "",
        f"Generated: {result['generated_at']}",
        "",
        f"**Status:** `{result['status']}`",
        "",
        "| Check | Status | Time | Summary |",
        "|---|---:|---:|---|",
    ]
    for check in result["checks"]:
        elapsed = check.get("elapsed_sec")
        elapsed_txt = f"{elapsed:.2f}s" if isinstance(elapsed, (int, float)) else "-"
        lines.append(f"| {check['name']} | `{check['status']}` | {elapsed_txt} | {check.get('summary', '')} |")
    lines += [
        "",
        "## Plain-English Summary",
        "",
        "Pathway trust checks whether the operating layer can trust its own recommendation inputs: "
        "test registration, guard trust smokes, shared scanner contract, and optional project guard timings.",
        "",
        "A `pass` means the harness found no missing tests, the guard trust suites passed, and any project timing probes stayed inside budget.",
        "A `warn` means the command worked but a timing budget needs attention. A `fail` means `/pathway` input trust is compromised.",
    ]
    return "\n".join(lines) + "\n"


def load_pathway_trust_summary(paths):
    data = read_json_file(paths.pathway_trust_path, {})
    if not isinstance(data, dict) or not data:
        return {"status": "unknown", "generated_at": "", "summary": "pathway-trust has not run yet"}
    return {
        "status": data.get("status", "unknown"),
        "generated_at": data.get("generated_at", ""),
        "summary": data.get("summary", ""),
        "json": str(paths.pathway_trust_path),
        "report": data.get("report", ""),
        "html": data.get("html", ""),
    }


def pathway_scripts_dir(paths):
    candidates = [
        paths.claude_home / "scripts",
        DEFAULT_CLAUDE_HOME / "scripts",
        Path(__file__).resolve().parent,
    ]
    for candidate in candidates:
        if (candidate / "techdebt-guard.py").exists() and (candidate / "tests").exists():
            return candidate
    return candidates[-1]


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
    existing = next((w for w in read_ndjson(paths.work_items_path) if w.get("work_id") == work_id), None)
    explicit_tier = getattr(args, "tier", None)
    existing_itin = (existing or {}).get("itinerary")
    if explicit_tier:
        # A tier was chosen → seed (or resize) the coverage itinerary. The /pathway skill
        # always passes a tier, so the coverage guarantee holds for every tracked outcome.
        tier = explicit_tier.lower()
        if tier not in PATHWAY_TIERS:
            tier = DEFAULT_ITINERARY_TIER
        itinerary = (merge_itinerary(existing_itin, compute_itinerary(tier, args.goal))
                     if existing_itin else compute_itinerary(tier, args.goal))
    elif existing_itin:
        # Re-START without a tier: preserve the in-progress itinerary and its earned proof.
        tier = (existing or {}).get("tier", DEFAULT_ITINERARY_TIER)
        itinerary = existing_itin
    else:
        # No tier chosen and no prior itinerary → loose tracking, no coverage gate
        # (backward-compatible: bare `work-start` behaves as it did before the feature).
        tier = (existing or {}).get("tier", "")
        itinerary = []
    item = update_work_item(
        paths,
        work_id,
        status="active",
        mode="semi-automatic",
        project=project_path,
        project_name=Path(project_path).name,
        goal=args.goal,
        context=context,
        tier=tier,
        itinerary=itinerary,
        closeout_readiness="not_ready",
    )
    dashboard = build_daily_dashboard(paths)
    return {"records": [item], "findings": [], "work_id": work_id, "dashboard": str(paths.daily_dashboard_path), "daily": dashboard}


def run_work_cover(args, paths):
    """Edit an outcome's itinerary: mark a pathway not-applicable (--na, with --reason)
    or append a newly-revealed required pathway (--add). Every drop is an explicit
    recorded reason and every addition is deliberate — that is the coverage guarantee."""
    if not args.work_id or not args.pathway:
        return {
            "findings": [finding(
                "work-cover-missing-input",
                "daily-work",
                "warn",
                "work-cover requires --work-id and --pathway (plus --na --reason, or --add).",
                [line_evidence(paths.work_items_path)],
                "Run `work-cover --work-id ID --pathway NAME --na --reason TEXT` or `--add`.",
                "static",
                "high",
            )],
            "records": [],
        }
    records = load_work_records(paths)
    item = next((w for w in records["items"] if w.get("work_id") == args.work_id), None)
    if not item:
        return {
            "findings": [finding(
                "work-cover-unknown-work-id",
                "daily-work",
                "warn",
                f"No work item found for work_id {args.work_id}.",
                [line_evidence(paths.work_items_path, source=args.work_id)],
                "Run work-start first, or correct the work_id.",
                "static",
                "high",
            )],
            "records": [],
        }
    # Validate inputs (Codex P2): a non-canonical pathway would be unrecommendable and
    # could leave the outcome unclosable; and exactly one action must be chosen.
    if args.pathway not in PATHWAY_CANON_ORDER:
        return {
            "findings": [finding(
                "work-cover-unknown-pathway",
                "daily-work",
                "warn",
                f"'{args.pathway}' is not a known pathway. Choose one of: {', '.join(PATHWAY_CANON_ORDER)}.",
                [line_evidence(paths.work_items_path, source=args.work_id)],
                "Re-run with a canonical pathway name.",
                "static",
                "high",
            )],
            "records": [],
        }
    if bool(args.add) == bool(args.na):
        return {
            "findings": [finding(
                "work-cover-needs-one-action",
                "daily-work",
                "warn",
                "work-cover needs exactly one of --na (mark not-applicable) or --add (append as required).",
                [line_evidence(paths.work_items_path, source=args.work_id)],
                "Re-run with exactly one of `--na --reason TEXT` or `--add`.",
                "static",
                "high",
            )],
            "records": [],
        }
    itinerary = list(item.get("itinerary") or [])
    entry = next((e for e in itinerary if e.get("pathway") == args.pathway), None)
    if args.add:
        if entry:
            # Never downgrade earned proof on --add (GLM P1 + reproduced): only an absent
            # or already-required entry stays required; proved/na is preserved as-is.
            if entry.get("status") not in ("proved", "na"):
                entry["status"] = "required"
            if args.reason:
                entry["reason"] = args.reason
        else:
            itinerary.append({
                "pathway": args.pathway,
                "status": "required",
                "reason": args.reason or "revealed during execution",
                "proved_by_run": "",
            })
        itinerary.sort(key=lambda e: PATHWAY_CANON_ORDER.index(e["pathway"]) if e.get("pathway") in PATHWAY_CANON_ORDER else 99)
    else:
        # Default action marks not-applicable, and it REQUIRES a reason — nothing is
        # ever dropped silently. That refusal is the point of the whole mechanism.
        if not args.reason:
            return {
                "findings": [finding(
                    "work-cover-na-needs-reason",
                    "daily-work",
                    "warn",
                    "Marking a pathway not-applicable requires --reason (why it does not apply).",
                    [line_evidence(paths.work_items_path, source=args.work_id)],
                    "Re-run with `--na --reason \"<why this pathway does not apply>\"`.",
                    "static",
                    "high",
                )],
                "records": [],
            }
        if entry:
            entry["status"] = "na"
            entry["reason"] = args.reason
        else:
            itinerary.append({"pathway": args.pathway, "status": "na", "reason": args.reason, "proved_by_run": ""})
    item = update_work_item(paths, args.work_id, itinerary=itinerary)
    covered, total, open_required = itinerary_coverage(item)
    return {
        "records": [item],
        "findings": [],
        "work_id": args.work_id,
        "itinerary_coverage": {"covered": covered, "total": total, "open": open_required},
    }


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


def render_learning_report(candidates):
    lines = [
        "# Pathway Learning Candidates",
        "",
        f"Generated: {iso_now()}",
        "",
        "| Learning | Project | Work | Changed thing | Proof | Global rule candidate |",
        "|---|---|---|---|---|---|",
    ]
    for item in sorted(candidates, key=lambda x: x.get("timestamp", ""), reverse=True)[:50]:
        lines.append(
            "| "
            + " | ".join([
                table_cell(item.get("learning_id")),
                table_cell(item.get("project")),
                table_cell(item.get("work_id")),
                table_cell(item.get("changed_thing")),
                table_cell(item.get("proof_that_mattered")),
                table_cell(item.get("possible_global_rule")),
            ])
            + " |"
        )
    if not candidates:
        lines += ["", "No learning candidates have been extracted yet."]
    return "\n".join(lines) + "\n"


def write_learning_report(paths, candidates):
    md_path = dated_artifact_path(paths, "learning-candidates")
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_learning_report(candidates))
    render_html(md_path, html_path)
    return md_path, html_path


def extract_learning_candidate(paths, summary, closed_item):
    item = closed_item or summary.get("work_item") or {}
    work_id = item.get("work_id", "")
    proofs = [p for p in read_ndjson(paths.proofs_path) if p.get("work_id") == work_id]
    latest_proof = sorted(proofs, key=lambda p: p.get("timestamp", ""), reverse=True)[0] if proofs else {}
    measurements = summary.get("measurements", [])
    latest_measurement = sorted(measurements, key=lambda m: m.get("timestamp", ""), reverse=True)[0] if measurements else {}
    pathways = summary.get("pathway_coverage", {}).get("seen", [])
    proof_path = latest_proof.get("evidence_path") or latest_measurement.get("evidence_path", "")
    verified_by = latest_proof.get("verified_by") or latest_measurement.get("gate", "")
    pathway = latest_proof.get("pathway") or latest_measurement.get("pathway") or (pathways[-1] if pathways else "")
    possible_rule = (
        f"Require proof metadata on {pathway} closeouts." if latest_proof
        else f"Require proof-add/work-log --proof-type before closing {pathway or 'pathway'} work."
    )
    return {
        "learning_id": f"L-{short_hash(work_id, proof_path, pathway, length=10)}",
        "timestamp": iso_now(),
        "work_id": work_id,
        "project": item.get("project_name", ""),
        "project_path": item.get("project", ""),
        "changed_thing": item.get("goal", ""),
        "proof_that_mattered": proof_path,
        "failure_caught": "; ".join(summary.get("warnings", [])) or "none at closeout",
        "guard_involved": verified_by,
        "pathways_seen": pathways,
        "project_learning": f"{item.get('project_name', 'project')} closed {pathway or 'pathway'} work with proof {Path(proof_path).name if proof_path else 'missing'}.",
        "possible_global_rule": possible_rule,
        "source": "operating-layer work-close",
    }


def write_learning_candidate(paths, candidate):
    candidates = [c for c in read_ndjson(paths.learning_candidates_path) if c.get("learning_id") != candidate.get("learning_id")]
    candidates.append(candidate)
    write_ndjson(paths.learning_candidates_path, candidates)
    md_path, html_path = write_learning_report(paths, candidates)
    return candidates, md_path, html_path


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
    proof = None
    if args.proof_type or args.verified_by or args.recommendation_id or getattr(args, "verify_cmd", None) or getattr(args, "reviewer", None):
        proof, proof_finding = build_proof_record(args, work_item=item, run_id=run_id, measurement_id_value=measurement["measurement_id"])
        if proof_finding:
            findings.append(proof_finding)
        if proof:
            run["proof_id"] = proof["proof_id"]
            measurement["proof_id"] = proof["proof_id"]
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
    if proof:
        upsert_proof(paths, proof)
        write_proof_report(paths, read_ndjson(paths.proofs_path))
    if item:
        updates = {"last_pathway": args.pathway, "last_run_id": run_id}
        # Mark the itinerary entry proved ONLY when this log carries (a) a real artifact on disk
        # AND (b) a proof that is genuinely VERIFIED — a re-executed verifier that exited 0, or a
        # named human sign-off over a hashed artifact (proof_is_verified). A bare --verified-by
        # string is attestation, not verification, and can no longer prove. This is the keystone
        # that makes `proved` — and everything gated on it (coverage, proof rate, autonomy,
        # learning, calibration) — mean a verification actually passed, not that a string was typed.
        proved = (bool(proof) and bool(evidence_path) and Path(evidence_path).is_file()
                  and proof_is_verified(proof))
        itinerary = item.get("itinerary") or []
        if proved and itinerary:
            for entry in itinerary:
                if entry.get("pathway") == args.pathway and entry.get("status") == "required":
                    entry["status"] = "proved"
                    entry["proved_by_run"] = run_id
                    updates["itinerary"] = itinerary
        update_work_item(paths, args.work_id, **updates)
    dashboard = build_daily_dashboard(paths)
    return {"records": [run, measurement] + ([proof] if proof else []) + ([control] if control else []), "findings": findings, "run_id": run_id, "dashboard": str(paths.daily_dashboard_path), "daily": dashboard}


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
    learning = extract_learning_candidate(paths, summary, item)
    _candidates, learning_md, learning_html = write_learning_candidate(paths, learning)
    dashboard = build_daily_dashboard(paths)
    return {
        "records": [item, learning],
        "findings": [],
        "closed": True,
        "learning": learning,
        "learning_report": str(learning_md),
        "learning_html": str(learning_html),
        "dashboard": str(paths.daily_dashboard_path),
        "daily": dashboard,
    }


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


def run_proof_add(args, paths):
    work_item = None
    if args.work_id:
        work_item = next((w for w in read_ndjson(paths.work_items_path) if w.get("work_id") == args.work_id), None)
    proof, proof_finding = build_proof_record(args, work_item=work_item)
    if proof_finding:
        return {
            "records": [],
            "findings": [proof_finding],
            "proofs_path": str(paths.proofs_path),
        }
    proofs = upsert_proof(paths, proof)
    md_path, html_path = write_proof_report(paths, proofs)
    return {
        "records": [proof],
        "findings": [],
        "proof_id": proof["proof_id"],
        "proofs_path": str(paths.proofs_path),
        "report": str(md_path),
        "html": str(html_path),
    }


def run_proof_report(args, paths):
    proofs = read_ndjson(paths.proofs_path)
    md_path, html_path = write_proof_report(paths, proofs)
    return {
        "records": proofs,
        "findings": [],
        "proofs_path": str(paths.proofs_path),
        "report": str(md_path),
        "html": str(html_path),
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

# Gap D (learning loop): each closed outcome that proved a pathway dampens that pathway's
# future urgency by LEARN_DAMPEN_PER_CLOSE, capped at LEARN_DAMPEN_CAP distinct closes. Bounded
# so it nudges ties and moderate stacks but never overrides a real finding (40), a foundation
# gate (80/100), or an open control (50) — learning shifts the ranking, it does not hijack it.
LEARN_DAMPEN_PER_CLOSE = 3
LEARN_DAMPEN_CAP = 3

# On an UNTRACKED project (no active work item) a foundation gate is a tiebreaker, not a dominator:
# big enough to beat a `warn` (5) so a bare project still leans foundation-first, but yielding to a
# single `error` (40) so real findings drive the pick. (Recommender fix for the 0/3 external miss.)
UNTRACKED_FOUNDATION_NUDGE = 8

# Reasons that are SCAFFOLDING, not real evidence — they must never count toward recommendation
# confidence, or a content-free pick gets inflated above `low`. One list so the next scaffolding
# reason can't silently leak in (a dual-critic caught the completeness-nudge + learning reasons leaking).
SCAFFOLDING_REASON_MARKERS = ("Foundation gate:", "lowest-coverage", "Pathway has no run", "Demonstrated:")


def learned_pathway_closures(paths, project_name, project_path):
    """Gap D learning signal: map each pathway to the set of THIS project's closed work_ids
    that proved it. Sourced from the learning candidates persisted at work-close, so the loop
    has no effect until the project has real closure history (keeps the scorer a no-op cold)."""
    closures = {}
    for cand in read_ndjson(paths.learning_candidates_path):
        if cand.get("project") != project_name and cand.get("project_path") != project_path:
            continue
        work_id = cand.get("work_id", "")
        for pathway in cand.get("pathways_seen", []) or []:
            closures.setdefault(pathway, set()).add(work_id)
    return closures


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

    # Foundation gates. For an ACTIVE tracked outcome, govern/research genuinely come first (don't
    # plan from vague context) — they dominate so the itinerary walks foundations before building.
    # But on an UNTRACKED project (a cold ASK), defaulting to a foundation gate BURIES the project's
    # real findings — the measured 0/3 external-precision failure (consult-ops had 36 findings and
    # got "pin a metric"). So the gate only dominates with active work; untracked, it is a small
    # tiebreaker and live findings drive the pick.
    has_active_work = bool(work_summaries)
    if "research" not in seen:
        bump("research", 100 if has_active_work else UNTRACKED_FOUNDATION_NUDGE, "Foundation gate: no verified research dossier for this project — cannot plan from vague context.")
    if "govern" not in seen:
        bump("govern", 80 if has_active_work else UNTRACKED_FOUNDATION_NUDGE, "Foundation gate: no recorded decision/metric for this project's active work.")

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

    # Learning loop (Gap D): closed outcomes reweight the ranking. A pathway this project has
    # repeatedly proved-and-closed is, by that demonstrated track record, less likely to be the
    # current constraint — dampen it so the recommender surfaces pathways not yet demonstrated.
    # No-op until the project has closure history; bounded so it never overrides a real signal.
    for pathway, closed_ids in learned_pathway_closures(paths, project_name, project_path).items():
        n = min(len(closed_ids), LEARN_DAMPEN_CAP)
        if n and pathway in scores:
            bump(pathway, -LEARN_DAMPEN_PER_CLOSE * n,
                 f"Demonstrated: {len(closed_ids)} closed outcome(s) proved {pathway} — "
                 "deprioritized in favor of pathways not yet demonstrated.")

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
        "execution_stack": list(PATHWAY_EXECUTION.get(pathway, {}).get("stack", [])),
        "execution_tools": list(PATHWAY_EXECUTION.get(pathway, {}).get("tools", [])),
        "goal": goal or f"Advance {project_name} via the {pathway} pathway",
    }


def recommendation_confidence(ranked, has_context, trust):
    recommended = ranked[0] if ranked else {"score": 0, "reasons": [], "pathway": ""}
    runner_up = ranked[1] if len(ranked) > 1 else {"score": 0, "reasons": [], "pathway": ""}
    score_gap = int(recommended.get("score", 0) or 0) - int(runner_up.get("score", 0) or 0)
    missing = []
    if not has_context:
        missing.append("No project-scoped findings or active work item were found.")
    trust_status = (trust or {}).get("status", "unknown")
    if trust_status != "pass":
        missing.append(f"pathway-trust status is {trust_status}.")
    # Gap B: confidence reflects EVIDENCE STRENGTH, not only score separation. A pick
    # backed by real live signals (findings/controls routed to it) is trustworthy even
    # when a runner-up sits close; a pick with no backing evidence is low even with a gap.
    # Foundation-gate and default "lowest-coverage" reasons are scaffolding, not evidence.
    top_reasons = recommended.get("reasons") or []
    evidence_reasons = [
        r for r in top_reasons
        if not any(marker in r for marker in SCAFFOLDING_REASON_MARKERS)
    ]
    evidence_count = len(evidence_reasons)
    # Confidence tracks EVIDENCE, not raw score separation. A foundation gate inflates score_gap
    # without adding real signal, which used to grant `medium` to a content-free pick on a project
    # with zero findings (prettyfly-os: research@medium, 0 signals). No real context, or a pick
    # backed only by scaffolding -> low, always. `high` needs ≥3 real signals and nothing missing.
    if not has_context or evidence_count == 0:
        level = "low"
    elif evidence_count >= 3 and not missing:
        level = "high"
    else:
        level = "medium"
    if trust_status == "fail":
        level = "low"
    top_reason = (recommended.get("reasons") or ["lowest-coverage pathway"])[0]
    runner_reason = (runner_up.get("reasons") or ["runner-up has weaker current evidence"])[0]
    return {
        "level": level,
        "score_gap": score_gap,
        "runner_up_pathway": runner_up.get("pathway", ""),
        "runner_up_reason": runner_reason,
        "why_this": top_reason,
        "why_not_runner_up": (
            f"{runner_up.get('pathway', 'runner-up')} lost by {score_gap} point(s): {runner_reason}"
            if runner_up.get("pathway") else "No runner-up pathway was available."
        ),
        "top_evidence": (recommended.get("reasons") or ["lowest-coverage pathway"])[:3],
        "missing_evidence": missing,
    }


def suggest_autonomy_tier(proved_rate, trust, confidence, gate_target=0.5):
    """Engine-side computation of the LOOP autonomy tier (see commands/pathway.md), so the
    /pathway skill reads ONE field instead of re-deriving the Tier-2 rule from three signals
    every turn. Tier-2 `execute-safe` unlocks ONLY when the proof track record clears the gate
    AND trust passes AND the pick is high-confidence; every other combination stays Tier-1
    `recommend`. Tier-3 `execute-build` is never suggested by the engine — it requires an
    explicit per-session human grant. Fail-closed: any missing/ambiguous signal -> recommend.

    Computed at determine time inside pathway-next, so the tier is fresh by construction —
    this is exactly the staleness fail-closed the skill warns about, now enforced in code.
    """
    rate = proved_rate if isinstance(proved_rate, (int, float)) else 0.0
    trust_status = (trust or {}).get("status", "unknown")
    level = (confidence or {}).get("level", "low")
    proved_ok = rate >= gate_target
    trust_ok = trust_status == "pass"
    conf_ok = level == "high"
    tier = "execute-safe" if (proved_ok and trust_ok and conf_ok) else "recommend"
    blockers = []
    if not proved_ok:
        blockers.append(f"proof rate {rate} is below the {gate_target} gate")
    if not trust_ok:
        blockers.append(f"trust is {trust_status}, not pass")
    if not conf_ok:
        blockers.append(f"confidence is {level}, not high")
    why = (
        "proof rate, trust, and confidence all clear the Tier-2 bar — the loop may auto-run the "
        "local, reversible portion of the safe pathways without waiting for a go"
        if tier == "execute-safe"
        else "stays in recommend (Tier 1) because " + "; ".join(blockers)
    )
    return {
        "tier": tier,
        "proved_rate": rate,
        "trust_status": trust_status,
        "confidence_level": level,
        "gate_target": gate_target,
        "fresh": True,
        "why": why,
    }


def render_pathway_next_report(paths, project_name, recommended, ranked, card, work_id, next_command, has_context, sources=None, trust=None, confidence=None, autonomy=None):
    sources = sources or {}
    trust = trust or {"status": "unknown", "summary": "pathway-trust has not run yet"}
    confidence = confidence or recommendation_confidence(ranked, has_context, trust)
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
        f"- **Best-execution stack:** {' → '.join(card.get('execution_stack', [])) or card['skill']}",
        f"- **Env / plugins / MCP:** {', '.join(card.get('execution_tools', [])) or '—'}",
        "",
        "## Pathway Trust",
        "",
        f"- **Status:** `{trust.get('status', 'unknown')}`",
        f"- **Summary:** {trust.get('summary', 'pathway-trust has not run yet')}",
        f"- **Report:** `{trust.get('report', '') or 'not generated'}`",
        "",
        "## Recommendation Confidence",
        "",
        f"- **Level:** `{confidence.get('level', 'unknown')}`",
        f"- **Why this, why not runner-up:** {confidence.get('why_this', '')} / {confidence.get('why_not_runner_up', '')}",
        f"- **Runner-up:** `{confidence.get('runner_up_pathway', '') or 'none'}`",
        f"- **Score gap:** {confidence.get('score_gap', 0)}",
        "",
        "Top evidence:",
    ]
    lines.extend(f"- {reason}" for reason in confidence.get("top_evidence", []))
    missing = confidence.get("missing_evidence", [])
    if missing:
        lines += ["", "Missing evidence:"]
        lines.extend(f"- {item}" for item in missing)
    if autonomy:
        lines += [
            "",
            "## Suggested Autonomy",
            "",
            f"- **Tier:** `{autonomy.get('tier', 'recommend')}`",
            f"- **Why:** {autonomy.get('why', '')}",
            f"- **Inputs:** proof rate {autonomy.get('proved_rate', 0)} · trust "
            f"`{autonomy.get('trust_status', 'unknown')}` · confidence "
            f"`{autonomy.get('confidence_level', 'unknown')}` (gate {autonomy.get('gate_target', 0.5)})",
        ]
    lines += [
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


def table_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")[:220]


def proof_is_stale(proof):
    ts = parse_ts(proof.get("timestamp"))
    if not ts:
        return False
    stale_after = int(proof.get("stale_after_days") or WORK_STALE_DAYS)
    return (utc_now() - ts).days > stale_after


def render_proof_report(proofs):
    stale_count = len([p for p in proofs if proof_is_stale(p)])
    lines = [
        "# Pathway Proof Registry",
        "",
        f"Generated: {iso_now()}",
        "",
        f"**Proofs:** {len(proofs)}",
        f"**Stale proofs:** {stale_count}",
        "",
        "```mermaid",
        "flowchart LR",
        '  A["Recommendation"] --> B["Work log"]',
        '  B --> C["Proof artifact"]',
        '  C --> D["Metric proved-rate"]',
        "```",
        "",
        "| Proof | Project | Pathway | Type | Result | Verified by | Evidence |",
        "|---|---|---|---|---|---|---|",
    ]
    for proof in sorted(proofs, key=lambda p: p.get("timestamp", ""), reverse=True)[:50]:
        lines.append(
            "| "
            + " | ".join([
                table_cell(proof.get("proof_id")),
                table_cell(proof.get("project")),
                table_cell(proof.get("pathway")),
                table_cell(proof.get("proof_type")),
                table_cell(proof.get("result")),
                table_cell(proof.get("verified_by")),
                table_cell(proof.get("evidence_path")),
            ])
            + " |"
        )
    if not proofs:
        lines += ["", "No proofs have been recorded yet."]
    return "\n".join(lines) + "\n"


def write_proof_report(paths, proofs):
    md_path = dated_artifact_path(paths, "proof-registry")
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_proof_report(proofs))
    render_html(md_path, html_path)
    return md_path, html_path


def guard_command_for_pathway(paths, pathway, project_path):
    script_name = "migration-guard.py" if pathway == "data" else f"{pathway}-guard.py"
    script = pathway_scripts_dir(paths) / script_name
    if not script.exists():
        return ""
    return f"python3 {script} --project {project_path} --json"


def render_pathway_run_plan(plan):
    lines = [
        f"# Pathway Run Plan - {plan['project']} / {plan['pathway']}",
        "",
        f"Generated: {plan['timestamp']}",
        "",
        f"- Work ID: `{plan['work_id']}`",
        f"- Recommendation ID: `{plan.get('recommendation_id', '')}`",
        f"- Confidence: `{plan.get('confidence', '')}`",
        f"- Goal: {plan.get('goal', '')}",
        "",
        "## Skill And Guard",
        "",
        f"- Skill: `{plan.get('skill', '') or 'none'}`",
        f"- Guard command: `{plan.get('guard_command', '') or 'none available'}`",
        "",
        "## 1% Move",
        "",
        f"> {plan.get('one_percent_move', '')}",
        "",
        "## Required Proof Before Closeout",
        "",
        f"- Proof type: `{plan.get('required_proof_type', 'artifact')}`",
        f"- Proof must satisfy: {plan.get('proof_requirement', '')}",
        "",
        "```bash",
        plan.get("proof_command", ""),
        "```",
        "",
        "## Source Recommendation",
        "",
        f"- Report: `{plan.get('pathway_next_report', '')}`",
        f"- HTML: `{plan.get('pathway_next_html', '')}`",
    ]
    return "\n".join(lines) + "\n"


def write_pathway_run_plan(paths, plan):
    md_path = dated_artifact_path(paths, f"pathway-run-{safe_slug(plan['project'])}-{safe_slug(plan['pathway'])}")
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_pathway_run_plan(plan))
    render_html(md_path, html_path)
    plans = [p for p in read_ndjson(paths.pathway_run_plans_path) if p.get("plan_id") != plan.get("plan_id")]
    plan = {**plan, "report": str(md_path), "html": str(html_path)}
    plans.append(plan)
    write_ndjson(paths.pathway_run_plans_path, plans)
    return plan, md_path, html_path


def run_pathway_trust(args, paths):
    script_dir = pathway_scripts_dir(paths)
    test_dir = script_dir / "tests"
    project_path = resolve_project_path(args, paths) if args.project else None

    checks = [
        explicit_runner_integrity(test_dir / "operating_layer_test.py"),
        run_trust_command("pathway_fs helper contract", [sys.executable, str(test_dir / "pathway_fs_test.py")], 2.0),
        run_trust_command("techdebt guard trust suite", [sys.executable, str(test_dir / "techdebt_guard_test.py")], 5.0),
        run_trust_command("design guard trust suite", [sys.executable, str(test_dir / "design_guard_test.py")], 5.0),
        run_trust_command("observability guard trust suite", [sys.executable, str(test_dir / "observability_guard_test.py")], 7.0),
    ]

    if project_path:
        probes = [
            ("techdebt project probe", [sys.executable, str(script_dir / "techdebt-guard.py"), "--project", project_path, "--json"], 5.0),
            ("design project probe", [sys.executable, str(script_dir / "design-guard.py"), "--project", project_path, "--json"], 5.0),
            ("observability project probe", [sys.executable, str(script_dir / "observability-guard.py"), "--project", project_path, "--profile", "multi-tenant-saas", "--json"], 7.0),
        ]
        checks.extend(run_trust_command(name, cmd, budget) for name, cmd, budget in probes)
    elif args.project:
        checks.append({
            "name": "project resolution",
            "status": "fail",
            "summary": f"project not found: {args.project}",
        })

    status = aggregate_trust_status(checks)
    summary = (
        "all trust checks passed" if status == "pass"
        else "trust checks passed with warnings" if status == "warn"
        else "one or more trust checks failed"
    )
    result = {
        "generated_at": iso_now(),
        "status": status,
        "summary": summary,
        "project": str(project_path or ""),
        "checks": checks,
    }
    write_json(paths.pathway_trust_path, result)
    md_path = dated_artifact_path(paths, "pathway-trust")
    html_path = md_path.with_suffix(".html")
    result["report"] = str(md_path)
    result["html"] = str(html_path)
    write_text(md_path, render_pathway_trust_report(result))
    render_html(md_path, html_path)
    write_json(paths.pathway_trust_path, result)

    result["records"] = checks
    result["findings"] = [finding(
        "pathway-trust-status",
        "pathway-trust",
        "info" if status == "pass" else "warn",
        f"Pathway trust status: {status}. {summary}.",
        [line_evidence(md_path)],
        "Fix failing trust checks before relying on pathway-next recommendations." if status == "fail"
        else "Use pathway-next with the recorded trust context.",
        "runtime",
        "high",
    )]
    return result


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
    # Itinerary override: when the active outcome still owes required pathways, the next
    # move comes from the committed itinerary (so coverage is never silently skipped) —
    # but WITHIN that set the order is evidence-driven, not a fixed list. Foundations
    # (govern/research) stay first while open, because they are prerequisites. Among the
    # remaining open-required pathways the router follows live EVIDENCE: it picks the
    # highest-scored one (ranked is score-sorted, with findings/controls already routed to
    # pathways), so the next move bends toward current risk instead of canonical order.
    # (Gap B part 2: coverage guarantee + evidence-grounded ordering, together.)
    active_summary = work_summaries[0] if work_summaries else None
    itinerary_open = (active_summary or {}).get("itinerary_coverage", {}).get("open", []) if active_summary else []
    if itinerary_open:
        FOUNDATIONS = ("govern", "research")
        open_foundations = [p for p in itinerary_open if p in FOUNDATIONS]
        if open_foundations:
            first = open_foundations[0]  # itinerary_open is canonical-ordered: govern before research
        else:
            first = next((r["pathway"] for r in ranked if r["pathway"] in itinerary_open), itinerary_open[0])
        recommended = next((r for r in ranked if r["pathway"] == first), recommended)
    card = karpathy_card(recommended["pathway"], project_name, args.goal)
    trust = load_pathway_trust_summary(paths)
    has_context = bool(scoped_findings or work_items)
    # Confidence must reflect the ACTUALLY recommended pathway and the field it competes
    # in. For a tracked outcome the router chooses among the open-required itinerary, so
    # confidence compares within that set (recommended is its highest-scored member) — not
    # against out-of-itinerary foundations. Otherwise why_this/evidence come from the wrong
    # pathway (e.g. research's foundation reason on an observability pick).
    ranked_for_confidence = (
        [r for r in ranked if r["pathway"] in itinerary_open] if itinerary_open else ranked
    )
    confidence = recommendation_confidence(ranked_for_confidence, has_context, trust)
    # Gap C (autonomy unlock): the engine — not the skill — computes the LOOP autonomy tier,
    # from the proof track record (fresh this turn), trust, and the recommended pick's
    # confidence. The /pathway loop reads `suggested_autonomy_tier` instead of re-deriving the
    # Tier-2 rule. proved_rate is measured over PRIOR recommendations (this run's rec is logged
    # below, after), so it reflects the established track record, never the just-issued pick.
    autonomy = suggest_autonomy_tier(
        compute_pathway_metric(paths).get("proved_rate", 0.0), trust, confidence)
    recommendations = read_ndjson(paths.recommendations_path)
    recommendation_id = f"REC-{safe_slug(project_name)}-{recommended['pathway']}-{len(recommendations) + 1:04d}"

    work_id = work_items[0].get("work_id") if work_items else None
    if work_id:
        next_command = (
            f"python3 ~/.claude/scripts/operating-layer.py work-log \\\n"
            f"  --work-id {work_id} \\\n"
            f"  --pathway {recommended['pathway']} --kind verify \\\n"
            f"  --evidence <path-to-real-artifact> --gate {recommended['pathway']}-gate \\\n"
            f"  --proof-type artifact --verified-by \"<verification-command>\" \\\n"
            f"  --recommendation-id {recommendation_id}"
        )
    else:
        goal_text = args.goal or f"Advance {project_name} via {recommended['pathway']}"
        next_command = (
            f"python3 ~/.claude/scripts/operating-layer.py work-start \\\n"
            f"  --project {project_path} \\\n"
            f"  --goal \"{goal_text}\""
        )

    md_path = dated_artifact_path(paths, f"pathway-next-{safe_slug(project_name)}")
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_pathway_next_report(
        paths, project_name, recommended, ranked, card, work_id, next_command, has_context,
        sources, trust, confidence, autonomy))
    render_html(md_path, html_path)

    # Log the recommendation so pathway-metric can measure follow-through (govern metric).
    recommendations.append({
        "recommendation_id": recommendation_id,
        "project": project_name,
        "pathway": recommended["pathway"],
        "work_id": work_id or "",
        "confidence": confidence.get("level", ""),
        "runner_up_pathway": confidence.get("runner_up_pathway", ""),
        "why_this": confidence.get("why_this", ""),
        "why_not_runner_up": confidence.get("why_not_runner_up", ""),
        "suggested_autonomy_tier": autonomy["tier"],
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
        "pathway_trust": trust,
        "recommendation_id": recommendation_id,
        "recommendation_confidence": confidence,
        "suggested_autonomy_tier": autonomy["tier"],
        "autonomy_rationale": autonomy,
        "itinerary": (active_summary or {}).get("itinerary", []) if active_summary else [],
        "itinerary_coverage": (active_summary or {}).get("itinerary_coverage", {}) if active_summary else {},
        "report": str(md_path),
        "html": str(html_path),
    }


def run_pathway_run(args, paths):
    project_path = resolve_project_path(args, paths)
    if not project_path:
        return {
            "findings": [finding(
                "pathway-run-missing-project",
                "pathway-run",
                "warn",
                "pathway-run requires --project (a path or a project name under the projects root).",
                [line_evidence(paths.portfolio_path)],
                "Run `pathway-run --project <name> --goal <outcome>`.",
                "static",
                "high",
            )],
            "records": [],
        }
    project_name = Path(project_path).name
    work_items = active_work_for_project(paths, project_path, project_name)
    goal_text = args.goal or f"Advance {project_name} through /pathway"
    if work_items:
        item = work_items[0]
        work_id = item.get("work_id")
    else:
        work_id = stable_work_id(project_path, goal_text)
        item = update_work_item(
            paths,
            work_id,
            status="active",
            mode="semi-automatic",
            project=project_path,
            project_name=project_name,
            goal=goal_text,
            context=current_work_context(paths, project_path),
            closeout_readiness="not_ready",
        )

    rec = run_pathway_next(args, paths)
    pathway = rec.get("recommended_pathway", "")
    card = rec.get("karpathy_card", {})
    guard_command = guard_command_for_pathway(paths, pathway, project_path)
    proof_command = (
        f"python3 ~/.claude/scripts/operating-layer.py work-log \\\n"
        f"  --work-id {work_id} \\\n"
        f"  --pathway {pathway} --kind verify \\\n"
        f"  --evidence <path-to-real-artifact> --gate {pathway}-gate \\\n"
        f"  --proof-type artifact --verified-by \"{guard_command or card.get('skill', '<verification-command>')}\" \\\n"
        f"  --recommendation-id {rec.get('recommendation_id', '')}"
    )
    plan = {
        "plan_id": f"PRUN-{short_hash(project_path, work_id, pathway, rec.get('recommendation_id', ''), length=10)}",
        "timestamp": iso_now(),
        "project": project_name,
        "project_path": project_path,
        "work_id": work_id,
        "goal": item.get("goal", goal_text),
        "pathway": pathway,
        "recommendation_id": rec.get("recommendation_id", ""),
        "confidence": rec.get("recommendation_confidence", {}).get("level", ""),
        "skill": card.get("skill", ""),
        "guard_command": guard_command,
        "one_percent_move": rec.get("one_percent_move", ""),
        "required_proof_type": "artifact",
        "proof_requirement": f"Run the {pathway} move and attach the real verification artifact before closeout.",
        "proof_command": proof_command,
        "pathway_next_report": rec.get("report", ""),
        "pathway_next_html": rec.get("html", ""),
    }
    plan, md_path, html_path = write_pathway_run_plan(paths, plan)
    dashboard = build_daily_dashboard(paths)
    return {
        "records": [item, plan],
        "findings": rec.get("findings", []),
        "work_id": work_id,
        "recommendation_id": rec.get("recommendation_id", ""),
        "recommended_pathway": pathway,
        "run_plan": plan,
        "report": str(md_path),
        "html": str(html_path),
        "dashboard": str(paths.daily_dashboard_path),
        "daily": dashboard,
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


def compute_pathway_metric(paths, window_days=1, gate_target=0.5):
    """Pure computation of the recommendation action+proof metric — no file write.

    Of pathway-next recommendations, the fraction that got a matching work-log run
    (acted_on) and the fraction proved (a linked proof record) within --window-days.
    Shared by run_pathway_metric (which persists it) and run_pathway_next (which reads
    proved_rate to suggest an autonomy tier — fresh by construction, computed this turn)."""
    recs = read_ndjson(paths.recommendations_path)
    runs = read_ndjson(paths.pathway_runs_path)
    proofs = read_ndjson(paths.proofs_path)
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

    def proved(rec):
        rec_ts = parse_ts(rec.get("timestamp"))
        for proof in proofs:
            if not proof_is_verified(proof):
                continue  # keystone: attested (free-text) proofs never raise the autonomy proof rate
            proof_rec = proof.get("recommendation_id")
            if proof_rec:
                if proof_rec != rec.get("recommendation_id"):
                    continue
            else:
                same_work = rec.get("work_id") and proof.get("work_id") == rec.get("work_id")
                same_proj = bool(rec.get("project")) and proof.get("project") == rec.get("project")
                same_pathway = proof.get("pathway") == rec.get("pathway")
                if not (same_pathway and (same_work or same_proj)):
                    continue
            if proof.get("pathway") and proof.get("pathway") != rec.get("pathway"):
                continue
            proof_ts = parse_ts(proof.get("timestamp"))
            if rec_ts and proof_ts:
                delta = (proof_ts - rec_ts).total_seconds()
                if 0 <= delta <= window_days * 86400:
                    return True
        return False

    by_pathway = {}
    acted = 0
    proved_count = 0
    total = 0
    skipped = 0
    for rec in recs:
        if parse_ts(rec.get("timestamp")) is None:
            skipped += 1  # can't evaluate the follow-through window; exclude from numerator AND denominator
            continue
        total += 1
        hit = acted_on(rec)
        proof_hit = proved(rec)
        acted += 1 if hit else 0
        proved_count += 1 if proof_hit else 0
        bucket = by_pathway.setdefault(rec.get("pathway", "?"), {"total": 0, "acted_on": 0, "proved": 0})
        bucket["total"] += 1
        bucket["acted_on"] += 1 if hit else 0
        bucket["proved"] += 1 if proof_hit else 0
    for bucket in by_pathway.values():
        bucket["rate"] = round(bucket["acted_on"] / bucket["total"], 3) if bucket["total"] else 0.0
        bucket["proved_rate"] = round(bucket["proved"] / bucket["total"], 3) if bucket["total"] else 0.0

    rate = round(acted / total, 3) if total else 0.0
    proved_rate = round(proved_count / total, 3) if total else 0.0
    metric = {
        "metric": "recommendation action and proof rate",
        "generated_at": iso_now(),
        "window_days": window_days,
        "total_recommendations": total,
        "skipped_no_timestamp": skipped,
        "acted_on": acted,
        "rate": rate,
        "acted_on_rate": rate,
        "proved": proved_count,
        "proved_rate": proved_rate,
        "gate_target": gate_target,
        "gate_pass": (total > 0 and rate >= gate_target),
        "proof_gate_pass": (total > 0 and proved_rate >= gate_target),
        "by_pathway": by_pathway,
    }
    return metric


def run_pathway_metric(args, paths):
    """Recommendation-action rate (the pathway system's govern metric):
    of pathway-next recommendations, the fraction that got a matching work-log run
    (same project+pathway) within --window-days. <gate-target means dashboard, not operating layer."""
    window_days = args.window_days if args.window_days is not None else 1
    gate_target = args.gate_target if args.gate_target is not None else 0.5
    metric = compute_pathway_metric(paths, window_days, gate_target)
    write_json(paths.operator_intel / "pathway-metric.json", metric)
    return {
        "records": read_ndjson(paths.recommendations_path),
        "findings": [],
        "metric": metric,
        "written": str(paths.operator_intel / "pathway-metric.json"),
    }


def portfolio_next_items(paths):
    projects = scan_projects(paths)
    work_records = load_work_records(paths)
    known_paths = {p.get("path") for p in projects}
    for work in work_records["items"]:
        project_path = work.get("project")
        if not project_path or project_path in known_paths:
            continue
        p = Path(project_path)
        projects.append({
            "name": work.get("project_name") or p.name,
            "path": project_path,
            "kind": classify_project(p) if p.exists() else "tracked-work",
            "stack": detect_stack(p) if p.exists() else [],
            "canonical_status": "tracked-work",
            "deploy_targets": [],
            "data_boundary": project_boundary(p) if p.exists() else "unknown",
            "evidence_refs": quick_evidence_refs(p) if p.exists() else [],
            "last_verified": mtime_iso(p / ".planning") or mtime_iso(p / "README.md") or mtime_iso(p) if p.exists() else None,
            "next_action": "continue active work",
        })
        known_paths.add(project_path)
    proofs = read_ndjson(paths.proofs_path)
    recs = read_ndjson(paths.recommendations_path)
    out = []
    for project in projects:
        name = project.get("name", "")
        work_items = [
            w for w in work_records["items"]
            if w.get("status", "active") != "closed"
            and (w.get("project") == project.get("path") or w.get("project_name") == name)
        ]
        work_ids = {w.get("work_id") for w in work_items}
        open_controls = [
            c for c in work_records["controls"]
            if c.get("work_id") in work_ids and c.get("status", "open") != "resolved"
        ]
        measurements = [m for m in work_records["measurements"] if m.get("work_id") in work_ids]
        stale_measurement_count = len(stale_measurements(measurements))
        project_proofs = [p for p in proofs if p.get("project") == name or p.get("project_path") == project.get("path")]
        stale_proof_count = len([p for p in project_proofs if proof_is_stale(p)])
        rec_count = len([r for r in recs if r.get("project") == name])
        score = 0
        reasons = []
        if project.get("canonical_status") == "unresolved":
            score += 25
            reasons.append("canonical checkout unresolved")
        if not project.get("evidence_refs"):
            score += 8
            reasons.append("no indexed evidence refs")
        if work_items:
            score += 10 * len(work_items)
            reasons.append(f"{len(work_items)} active work item(s)")
        if open_controls:
            score += 50 * len(open_controls)
            reasons.append(f"{len(open_controls)} open control(s)")
        if stale_measurement_count:
            score += 20 * stale_measurement_count
            reasons.append(f"{stale_measurement_count} stale measurement(s)")
        if stale_proof_count:
            score += 15 * stale_proof_count
            reasons.append(f"{stale_proof_count} stale proof(s)")
        if rec_count and not project_proofs:
            score += 12
            reasons.append("recommendations exist but no proof recorded")
        if rec_count:
            score += min(20, rec_count * 4)
            reasons.append(f"{rec_count} recommendation(s)")
        if not reasons:
            reasons.append(project.get("next_action", "keep current"))
        out.append({
            "project": name,
            "project_path": project.get("path"),
            "score": score,
            "reasons": reasons,
            "active_work": len(work_items),
            "open_controls": len(open_controls),
            "stale_measurements": stale_measurement_count,
            "stale_proofs": stale_proof_count,
            "recommendations": rec_count,
            "canonical_status": project.get("canonical_status"),
            "next_action": project.get("next_action"),
        })
    return sorted(out, key=lambda item: (-item["score"], item["project"]))


def render_portfolio_next_report(items):
    lines = [
        "# Portfolio Next Queue",
        "",
        f"Generated: {iso_now()}",
        "",
        "| Rank | Project | Score | Top reason | Active | Controls | Proofs stale |",
        "|---:|---|---:|---|---:|---:|---:|",
    ]
    for i, item in enumerate(items, 1):
        lines.append(
            f"| {i} | `{table_cell(item.get('project'))}` | {item.get('score', 0)} | "
            f"{table_cell((item.get('reasons') or [''])[0])} | {item.get('active_work', 0)} | "
            f"{item.get('open_controls', 0)} | {item.get('stale_proofs', 0)} |"
        )
    if not items:
        lines += ["", "No projects were discovered."]
    return "\n".join(lines) + "\n"


def run_portfolio_next(args, paths):
    items = portfolio_next_items(paths)
    result = {"generated_at": iso_now(), "items": items}
    write_json(paths.portfolio_next_path, result)
    md_path = dated_artifact_path(paths, "portfolio-next")
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_portfolio_next_report(items))
    render_html(md_path, html_path)
    return {
        "records": items,
        "findings": [],
        "queue": str(paths.portfolio_next_path),
        "report": str(md_path),
        "html": str(html_path),
        "top_project": items[0]["project"] if items else "",
    }


def rule_map_records(paths):
    script_dir = pathway_scripts_dir(paths)
    candidates = [
        {
            "rule": "Proof-backed closeout",
            "class": "always",
            "criticality": "critical",
            "description": "Closed work should emit learning from real proof, not transcript vibes.",
            "backing_candidates": [Path(__file__).resolve()],
        },
        {
            "rule": "Pathway guards are bounded and trusted",
            "class": "always",
            "criticality": "critical",
            "description": "Guard scripts must stay fast enough to be reliable recommendation inputs.",
            "backing_candidates": [script_dir / "tests" / "pathway_fs_test.py", script_dir / "tests" / "operating_layer_test.py"],
        },
        {
            "rule": "Secret redaction in operator outputs",
            "class": "never",
            "criticality": "critical",
            "description": "Operator artifacts must not leak tokens, passwords, or high-entropy secrets.",
            "backing_candidates": [Path(__file__).resolve(), script_dir / "tests" / "operating_layer_test.py"],
        },
        {
            "rule": "Confirm irreversible actions",
            "class": "ask-first",
            "criticality": "critical",
            "description": "Deletes, force pushes, production mutations, external sends, and data loss need explicit confirmation.",
            "backing_candidates": [],
        },
        {
            "rule": "Use apply_patch for manual edits",
            "class": "always",
            "criticality": "warn",
            "description": "Manual code edits should be visible, surgical patches.",
            "backing_candidates": [],
        },
        {
            "rule": "Do not mutate project repos from advisory commands",
            "class": "never",
            "criticality": "critical",
            "description": "pathway-next, pathway-run, and portfolio-next write central operator artifacts only.",
            "backing_candidates": [Path(__file__).resolve(), script_dir / "tests" / "operating_layer_test.py"],
        },
    ]
    records = []
    for item in candidates:
        backing = [str(p) for p in item["backing_candidates"] if Path(p).exists()]
        status = "enforced" if backing else "prose-only"
        records.append({
            "rule": item["rule"],
            "class": item["class"],
            "criticality": item["criticality"],
            "description": item["description"],
            "enforcement_status": status,
            "backing_paths": backing,
        })
    return records


def render_rule_map_report(records):
    lines = [
        "# Rule Enforcement Map",
        "",
        f"Generated: {iso_now()}",
        "",
        "| Rule | Class | Criticality | Status | Backing |",
        "|---|---|---|---|---|",
    ]
    for record in records:
        backing = ", ".join(record.get("backing_paths", [])) or "none"
        lines.append(
            f"| {table_cell(record.get('rule'))} | `{record.get('class')}` | `{record.get('criticality')}` | "
            f"`{record.get('enforcement_status')}` | {table_cell(backing)} |"
        )
    gaps = [r for r in records if r.get("enforcement_status") == "prose-only" and r.get("criticality") == "critical"]
    lines += ["", "## Critical Prose-Only Gaps", ""]
    if gaps:
        for gap in gaps:
            lines.append(f"- `{gap['rule']}`: {gap['description']}")
    else:
        lines.append("- No critical prose-only gaps found.")
    return "\n".join(lines) + "\n"


def run_rule_map(args, paths):
    records = rule_map_records(paths)
    result = {"generated_at": iso_now(), "rules": records}
    write_json(paths.rule_map_path, result)
    md_path = dated_artifact_path(paths, "rule-map")
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_rule_map_report(records))
    render_html(md_path, html_path)
    return {
        "records": records,
        "findings": [],
        "rule_map": str(paths.rule_map_path),
        "report": str(md_path),
        "html": str(html_path),
        "prose_only_critical": [r for r in records if r.get("enforcement_status") == "prose-only" and r.get("criticality") == "critical"],
    }


def latest_artifacts(paths, limit=12):
    if not paths.operator_artifacts.exists():
        return []
    files = [p for p in paths.operator_artifacts.glob("*") if p.is_file() and p.suffix in {".md", ".html", ".json"}]
    files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return [{"path": str(p), "name": p.name, "mtime": mtime_iso(p)} for p in files[:limit]]


def build_cockpit(paths):
    dashboard = build_daily_dashboard(paths)
    trust = load_pathway_trust_summary(paths)
    portfolio_data = read_json_file(paths.portfolio_next_path, {"items": portfolio_next_items(paths)})
    metric = read_json_file(paths.operator_intel / "pathway-metric.json", {})
    proofs = read_ndjson(paths.proofs_path)
    rules = read_json_file(paths.rule_map_path, {"rules": rule_map_records(paths)}).get("rules", [])
    recs = sorted(read_ndjson(paths.recommendations_path), key=lambda r: r.get("timestamp", ""), reverse=True)
    stale_proofs = [p for p in proofs if proof_is_stale(p)]
    critical_rule_gaps = [
        r for r in rules
        if r.get("criticality") == "critical" and r.get("enforcement_status") == "prose-only"
    ]
    top_portfolio = (portfolio_data.get("items") or [None])[0]
    latest_rec = recs[0] if recs else None
    source_paths = {
        "daily_dashboard": str(paths.daily_dashboard_path),
        "portfolio_next": str(paths.portfolio_next_path),
        "pathway_metric": str(paths.operator_intel / "pathway-metric.json"),
        "proofs": str(paths.proofs_path),
        "rule_map": str(paths.rule_map_path),
    }
    return {
        "generated_at": iso_now(),
        "daily_dashboard": dashboard,
        "trust": trust,
        "portfolio_top": top_portfolio,
        "latest_recommendation": latest_rec,
        "active_work_count": dashboard.get("active_count", 0),
        "stuck_work_items": dashboard.get("stuck_work_items", []),
        "open_controls": dashboard.get("top_open_controls", []),
        "metric": metric,
        "proof_count": len(proofs),
        "stale_proofs": stale_proofs,
        "critical_rule_gaps": critical_rule_gaps,
        "latest_artifacts": latest_artifacts(paths),
        "source_paths": {k: v for k, v in source_paths.items() if Path(v).exists()},
    }


def safe_display_text(value, limit=180):
    text = redact(str(value or "")).replace("\n", " ").strip()
    text = re.sub(r"/Users/[^\s`|,;)]+", lambda m: Path(m.group(0)).name, text)
    text = re.sub(r"/private/tmp/[^\s`|,;)]+", lambda m: Path(m.group(0)).name, text)
    text = re.sub(r"\bpython3\s+[^\n;]+", "verification command recorded", text)
    text = re.sub(r"\bnpm\s+(?:run\s+)?[^\n;]+", "npm verification recorded", text)
    text = re.sub(r"\bnpx\s+[^\n;]+", "node verification recorded", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def safe_artifact_name(value):
    raw = str(value or "").strip()
    name = Path(raw).name if raw else ""
    return safe_display_text(name or "artifact", limit=80)


def latest_recommendation_proof_status(latest_rec, proofs):
    if not latest_rec:
        return "unknown"
    rec_id = latest_rec.get("recommendation_id")
    pathway = latest_rec.get("pathway")
    project = latest_rec.get("project")
    matches = []
    for proof in proofs:
        if rec_id and proof.get("recommendation_id") == rec_id:
            matches.append(proof)
            continue
        if proof.get("pathway") == pathway and proof.get("project") == project:
            matches.append(proof)
    if not matches:
        return "missing"
    verified = [p for p in matches if proof_is_verified(p)]
    if not verified:
        return "unverified"  # keystone: attested-only proofs don't read as proved in the cockpit
    return "stale" if all(proof_is_stale(p) for p in verified) else "proved"


def safe_latest_recommendation(latest_rec, proofs):
    if not latest_rec:
        return None
    return {
        "project": safe_display_text(latest_rec.get("project"), 80),
        "pathway": safe_display_text(latest_rec.get("pathway"), 40),
        "recommendation_id": safe_display_text(latest_rec.get("recommendation_id"), 80),
        "confidence": safe_display_text(latest_rec.get("confidence") or latest_rec.get("level") or "unknown", 40),
        "runner_up_pathway": safe_display_text(latest_rec.get("runner_up_pathway"), 40),
        "why_this": safe_display_text(latest_rec.get("why_this") or latest_rec.get("reason") or "Latest recorded recommendation.", 220),
        "why_not_runner_up": safe_display_text(latest_rec.get("why_not_runner_up") or "Runner-up detail unavailable in the current ledger.", 220),
        "proof_status": latest_recommendation_proof_status(latest_rec, proofs),
    }


def safe_proof_summary(proof):
    return {
        "proof_id": safe_display_text(proof.get("proof_id"), 80),
        "project": safe_display_text(proof.get("project"), 80),
        "pathway": safe_display_text(proof.get("pathway"), 40),
        "proof_type": safe_display_text(proof.get("proof_type"), 40),
        "result": safe_display_text(proof.get("result"), 40),
        "status": "stale" if proof_is_stale(proof) else "current",
        "artifact_name": safe_artifact_name(proof.get("evidence_path")),
        "timestamp": safe_display_text(proof.get("timestamp"), 40),
    }


def safe_portfolio_item(item):
    reasons = item.get("reasons") if isinstance(item.get("reasons"), list) else []
    return {
        "project": safe_display_text(item.get("project"), 80),
        "score": int(item.get("score") or 0),
        "reason": safe_display_text(reasons[0] if reasons else item.get("next_action"), 180),
        "active_work": int(item.get("active_work") or 0),
        "stale_proofs": int(item.get("stale_proofs") or 0),
    }


def safe_decision_summary(decision):
    return {
        "decision_id": safe_display_text(decision.get("decision_id"), 80),
        "action": safe_display_text(decision.get("action"), 30),
        "project": safe_display_text(decision.get("project"), 80),
        "pathway": safe_display_text(decision.get("pathway"), 40),
        "recommendation_id": safe_display_text(decision.get("recommendation_id"), 80),
        "work_id": safe_display_text(decision.get("work_id"), 80),
        "proof_id": safe_display_text(decision.get("proof_id"), 80),
        "agent": safe_display_text(decision.get("agent"), 80),
        "reason": safe_display_text(decision.get("reason"), 220),
        "timestamp": safe_display_text(decision.get("timestamp"), 40),
    }


def build_decision_memory(decisions):
    memory = []
    for decision in decisions[:8]:
        action = safe_display_text(decision.get("action"), 30) or "decision"
        pathway = safe_display_text(decision.get("pathway"), 40) or "pathway"
        project = safe_display_text(decision.get("project"), 80) or "project"
        reason = safe_display_text(decision.get("reason"), 220) or "No rationale recorded."
        memory.append({
            "decision_id": safe_display_text(decision.get("decision_id"), 80),
            "title": f"{action.title()} {pathway} for {project}",
            "summary": reason,
            "project": project,
            "pathway": pathway,
            "timestamp": safe_display_text(decision.get("timestamp"), 40),
        })
    return memory


def build_agent_assignments(decisions, autonomous_queue):
    assignments = []
    for decision in decisions:
        if decision.get("action") != "assign":
            continue
        agent = safe_display_text(decision.get("agent"), 80)
        if not agent:
            continue
        assignments.append({
            "assignment_id": safe_display_text(decision.get("decision_id"), 80),
            "project": safe_display_text(decision.get("project"), 80),
            "pathway": safe_display_text(decision.get("pathway"), 40),
            "agent": agent,
            "status": "assigned",
            "reason": safe_display_text(decision.get("reason") or "Operator assigned this pathway.", 180),
        })
    for item in autonomous_queue:
        if len(assignments) >= 8:
            break
        project = safe_display_text(item.get("project"), 80)
        pathway = safe_display_text(item.get("pathway"), 40)
        if not project and not pathway:
            continue
        assignments.append({
            "assignment_id": f"suggested-{safe_slug(project or pathway)}-{len(assignments) + 1}",
            "project": project,
            "pathway": pathway,
            "agent": "unassigned",
            "status": "suggested",
            "reason": safe_display_text(item.get("title") or item.get("reason"), 180),
        })
    return assignments[:8]


def build_closeout_queue(cockpit, proofs):
    proofs_by_id = {p.get("proof_id"): p for p in proofs if p.get("proof_id")}
    dashboard = cockpit.get("daily_dashboard") or {}
    queue = []
    for summary in dashboard.get("work_summaries", [])[:8]:
        item = summary.get("work_item") or {}
        proof_ids = [
            m.get("proof_id")
            for m in summary.get("measurements", [])
            if m.get("proof_id")
        ]
        proof_records = [proofs_by_id.get(pid) for pid in proof_ids if proofs_by_id.get(pid)]
        has_current_proof = any(p and not proof_is_stale(p) for p in proof_records)
        has_stale_proof = bool(proof_records) and not has_current_proof
        ready = summary.get("closeout_readiness") == "ready" and has_current_proof
        warnings = summary.get("warnings") if isinstance(summary.get("warnings"), list) else []
        queue.append({
            "work_id": safe_display_text(item.get("work_id"), 80),
            "project": safe_display_text(item.get("project_name") or item.get("project"), 80),
            "goal": safe_display_text(item.get("goal"), 180),
            "status": "ready" if ready else "blocked",
            "proof_status": "current" if has_current_proof else "stale" if has_stale_proof else "missing",
            "reason": "Current proof supports closeout." if ready else safe_display_text(warnings[0] if warnings else "Closeout needs a current proof.", 220),
        })
    return queue


def build_alex_queue(cockpit, latest_rec, metric):
    queue = []
    if latest_rec and latest_recommendation_proof_status(latest_rec, cockpit.get("proofs_for_status", [])) != "proved":
        queue.append({
            "kind": "proof-needed",
            "priority": "high",
            "title": f"Prove {safe_display_text(latest_rec.get('pathway'), 40)} recommendation",
            "reason": "Latest recommendation is not linked to a current proof.",
        })
    for gap in cockpit.get("critical_rule_gaps", [])[:3]:
        queue.append({
            "kind": "rule-gap",
            "priority": "high" if gap.get("criticality") == "critical" else "medium",
            "title": safe_display_text(gap.get("rule") or gap.get("title") or "Rule gap", 120),
            "reason": safe_display_text(gap.get("description") or "Critical rule is not enforced by code.", 220),
        })
    for item in cockpit.get("stuck_work_items", [])[:3]:
        warnings = item.get("warnings") if isinstance(item.get("warnings"), list) else []
        queue.append({
            "kind": "stuck-work",
            "priority": "medium",
            "title": safe_display_text(item.get("goal") or item.get("work_id") or "Stuck work", 120),
            "reason": safe_display_text(warnings[0] if warnings else "Work needs operator attention.", 220),
        })
    if metric and metric.get("proof_gate_pass") is False:
        queue.append({
            "kind": "metric-gap",
            "priority": "medium",
            "title": "Raise proved follow-through",
            "reason": f"Proved rate is {metric.get('proved_rate', 0)} against target {metric.get('gate_target', 0)}.",
        })
    return queue[:6]


def build_autonomous_queue(paths, portfolio_items):
    plans = sorted(read_ndjson(paths.pathway_run_plans_path), key=lambda p: p.get("timestamp", ""), reverse=True)
    queue = []
    for plan in plans[:4]:
        queue.append({
            "kind": "pathway-run",
            "priority": "normal",
            "title": safe_display_text(plan.get("one_percent_move") or f"Continue {plan.get('pathway', 'pathway')} run", 140),
            "reason": safe_display_text(plan.get("proof_requirement") or "Attach proof before closeout.", 220),
            "project": safe_display_text(plan.get("project"), 80),
            "pathway": safe_display_text(plan.get("pathway"), 40),
        })
    for item in portfolio_items[:3]:
        queue.append({
            "kind": "portfolio",
            "priority": "normal",
            "title": f"Inspect {safe_display_text(item.get('project'), 80)}",
            "reason": safe_display_text((item.get("reasons") or [item.get("next_action", "")])[0], 180),
            "project": safe_display_text(item.get("project"), 80),
            "pathway": "",
        })
    return queue[:6]


def build_tool_warnings(paths):
    warnings = []
    for finding_item in sorted(read_ndjson(paths.findings_path), key=lambda f: f.get("id", "")):
        fid = finding_item.get("id", "")
        if not (fid.startswith("opintel-provider-model-drift") or fid.startswith("tools-auth") or fid.startswith("tools-duplicate")):
            continue
        warnings.append({
            "id": safe_display_text(fid, 100),
            "severity": safe_display_text(finding_item.get("severity"), 30),
            "label": safe_display_text(finding_item.get("message") or fid, 180),
        })
    return warnings[:6]


def build_pfos_cockpit(paths):
    cockpit = build_cockpit(paths)
    if not paths.rule_map_path.exists():
        cockpit["critical_rule_gaps"] = []
    if not paths.portfolio_next_path.exists():
        cockpit["portfolio_top"] = {}
    if not paths.recommendations_path.exists():
        cockpit["latest_recommendation"] = None
    proofs = read_ndjson(paths.proofs_path)
    decisions = sorted(read_ndjson(paths.pathway_decisions_path), key=lambda d: d.get("timestamp", ""), reverse=True)
    cockpit["proofs_for_status"] = proofs
    metric = cockpit.get("metric") or {}
    latest_rec = cockpit.get("latest_recommendation") or {}
    portfolio_items = (read_json_file(paths.portfolio_next_path, {"items": []}).get("items") or [])
    safe_rec = safe_latest_recommendation(latest_rec, proofs)
    stale_proofs = [p for p in proofs if proof_is_stale(p)]
    evidence = [safe_proof_summary(p) for p in sorted(proofs, key=lambda p: p.get("timestamp", ""), reverse=True)[:8]]
    portfolio_queue = [safe_portfolio_item(item) for item in portfolio_items[:8]]
    rule_gap_labels = [
        safe_display_text(gap.get("rule") or gap.get("title") or gap.get("description"), 120)
        for gap in cockpit.get("critical_rule_gaps", [])
    ]
    artifacts = [
        {
            "name": safe_artifact_name(a.get("name") or a.get("path")),
            "kind": safe_display_text(Path(str(a.get("name") or a.get("path") or "artifact")).suffix.lstrip(".") or "artifact", 40),
            "generated_at": safe_display_text(a.get("mtime") or a.get("generated_at"), 40),
        }
        for a in cockpit.get("latest_artifacts", [])[:8]
    ]
    autonomous_queue = build_autonomous_queue(paths, portfolio_items)
    snapshot = {
        "schema_version": 3,
        "generated_at": cockpit.get("generated_at"),
        "trust": {
            "status": safe_display_text(cockpit.get("trust", {}).get("status") or "unknown", 20),
            "summary": safe_display_text(cockpit.get("trust", {}).get("summary") or "", 220),
        },
        "portfolio_top": safe_portfolio_item(cockpit.get("portfolio_top") or {}),
        "latest_recommendation": safe_rec,
        "recommendation": safe_rec,
        "metric": {
            "acted_on_rate": metric.get("acted_on_rate", metric.get("rate")),
            "proved_rate": metric.get("proved_rate"),
            "gate_target": metric.get("gate_target"),
            "gate_pass": metric.get("gate_pass"),
            "proof_gate_pass": metric.get("proof_gate_pass"),
        },
        "proof": {
            "proof_count": len(proofs),
            "stale_count": len(stale_proofs),
            "acted_on_rate": metric.get("acted_on_rate", metric.get("rate")),
            "proved_rate": metric.get("proved_rate"),
        },
        "proof_count": len(proofs),
        "stale_proofs": [safe_proof_summary(p) for p in stale_proofs[:8]],
        "active_work_count": int(cockpit.get("active_work_count") or 0),
        "work": {
            "active_count": int(cockpit.get("active_work_count") or 0),
            "stuck_count": len(cockpit.get("stuck_work_items", [])),
        },
        "stuck_work_items": [
            {
                "work_id": safe_display_text(item.get("work_id"), 80),
                "goal": safe_display_text(item.get("goal"), 180),
            }
            for item in cockpit.get("stuck_work_items", [])[:8]
        ],
        "critical_rule_gaps": [
            {"rule": label}
            for label in rule_gap_labels
        ],
        "latest_artifacts": artifacts,
        "alex_queue": build_alex_queue(cockpit, latest_rec, metric),
        "autonomous_queue": autonomous_queue,
        "evidence_ledger": evidence,
        "portfolio_queue": portfolio_queue,
        "approval_history": [safe_decision_summary(d) for d in decisions[:8]],
        "decision_memory": build_decision_memory(decisions),
        "agent_assignments": build_agent_assignments(decisions, autonomous_queue),
        "closeout_queue": build_closeout_queue(cockpit, proofs),
        "health": {
            "rule_gaps": rule_gap_labels,
            "tool_warnings": build_tool_warnings(paths),
        },
    }
    snapshot.pop("source_paths", None)
    return snapshot


def render_pfos_cockpit_report(snapshot):
    rec = snapshot.get("recommendation") or {}
    proof = snapshot.get("proof") or {}
    lines = [
        "# PFOS Pathway Cockpit Snapshot",
        "",
        f"Generated: {snapshot.get('generated_at')}",
        "",
        "## Recommendation",
        "",
        f"- Project: `{rec.get('project') or 'none'}`",
        f"- Pathway: `{rec.get('pathway') or 'none'}`",
        f"- Confidence: `{rec.get('confidence') or 'unknown'}`",
        f"- Proof status: `{rec.get('proof_status') or 'unknown'}`",
        f"- Why this: {rec.get('why_this') or 'n/a'}",
        f"- Why not runner-up: {rec.get('why_not_runner_up') or 'n/a'}",
        "",
        "## Proof Health",
        "",
        f"- Proofs: {proof.get('proof_count', 0)}",
        f"- Stale: {proof.get('stale_count', 0)}",
        f"- Acted-on rate: {proof.get('acted_on_rate', 'n/a')}",
        f"- Proved rate: {proof.get('proved_rate', 'n/a')}",
        "",
        "## Alex Queue",
        "",
    ]
    lines.extend(f"- **{item.get('title')}** — {item.get('reason')}" for item in snapshot.get("alex_queue", []))
    if not snapshot.get("alex_queue"):
        lines.append("- No Alex-only queue items.")
    lines += ["", "## Autonomous Queue", ""]
    lines.extend(f"- **{item.get('title')}** — {item.get('reason')}" for item in snapshot.get("autonomous_queue", []))
    if not snapshot.get("autonomous_queue"):
        lines.append("- No safe autonomous queue items.")
    lines += ["", "## Evidence Ledger", ""]
    lines.extend(
        f"- `{item.get('proof_id')}` {item.get('project')} / {item.get('pathway')} — {item.get('status')} ({item.get('artifact_name')})"
        for item in snapshot.get("evidence_ledger", [])
    )
    if not snapshot.get("evidence_ledger"):
        lines.append("- No proof summaries recorded.")
    lines += ["", "## Steering", ""]
    for item in snapshot.get("approval_history", [])[:6]:
        lines.append(f"- `{item.get('action')}` {item.get('project')} / {item.get('pathway')} — {item.get('reason')}")
    if not snapshot.get("approval_history"):
        lines.append("- No pathway decisions recorded.")
    lines += ["", "## Proof-Backed Closeout", ""]
    for item in snapshot.get("closeout_queue", [])[:6]:
        lines.append(f"- `{item.get('work_id')}` {item.get('status')} / proof `{item.get('proof_status')}` — {item.get('reason')}")
    if not snapshot.get("closeout_queue"):
        lines.append("- No active work closeout candidates.")
    return "\n".join(lines) + "\n"


def pathway_decision_id(record):
    return "PD-" + short_hash(
        record.get("timestamp", ""),
        record.get("action", ""),
        record.get("project", ""),
        record.get("pathway", ""),
        record.get("recommendation_id", ""),
        record.get("work_id", ""),
        record.get("proof_id", ""),
        record.get("agent", ""),
        record.get("reason", ""),
        length=12,
    )


def render_pathway_decision_report(record):
    lines = [
        "# Pathway Decision",
        "",
        f"Generated: {record.get('timestamp')}",
        "",
        f"- Decision: `{record.get('decision_id')}`",
        f"- Action: `{record.get('action')}`",
        f"- Project: `{record.get('project') or 'none'}`",
        f"- Pathway: `{record.get('pathway') or 'none'}`",
        f"- Recommendation: `{record.get('recommendation_id') or 'none'}`",
        f"- Work: `{record.get('work_id') or 'none'}`",
        f"- Proof: `{record.get('proof_id') or 'none'}`",
        f"- Agent: `{record.get('agent') or 'none'}`",
        f"- Reason: {record.get('reason') or 'No reason recorded.'}",
        "",
        "This record is a steering-memory entry only. It does not execute external actions, shell commands, or production mutations.",
    ]
    return "\n".join(lines) + "\n"


def run_pathway_decision(args, paths):
    allowed = {"approve", "reject", "assign", "closeout"}
    action = safe_display_text(getattr(args, "action", ""), 30)
    if action not in allowed:
        return {
            "findings": [finding(
                "pathway-decision-missing-action",
                "pathway-decision",
                "warn",
                "pathway-decision requires --action approve|reject|assign|closeout.",
                [line_evidence(paths.pathway_decisions_path)],
                "Pass a valid --action.",
                "static",
                "high",
            )],
            "records": [],
        }
    if action == "assign" and not safe_display_text(getattr(args, "agent", ""), 80):
        return {
            "findings": [finding(
                "pathway-decision-missing-agent",
                "pathway-decision",
                "warn",
                "Assignment decisions require --agent.",
                [line_evidence(paths.pathway_decisions_path)],
                "Pass --agent with the assignee label.",
                "static",
                "high",
            )],
            "records": [],
        }

    project_raw = getattr(args, "project", "") or ""
    project = safe_display_text(Path(project_raw).name if "/" in str(project_raw) else project_raw, 80)
    record = {
        "timestamp": iso_now(),
        "action": action,
        "project": project,
        "pathway": safe_display_text(getattr(args, "pathway", ""), 40),
        "recommendation_id": safe_display_text(getattr(args, "recommendation_id", ""), 80),
        "work_id": safe_display_text(getattr(args, "work_id", ""), 80),
        "proof_id": safe_display_text(getattr(args, "proof_id", ""), 80),
        "agent": safe_display_text(getattr(args, "agent", ""), 80),
        "reason": safe_display_text(getattr(args, "reason", ""), 240),
        "source": "operating-layer pathway-decision",
    }
    record["decision_id"] = pathway_decision_id(record)
    decisions = read_ndjson(paths.pathway_decisions_path)
    decisions.append(record)
    write_ndjson(paths.pathway_decisions_path, decisions)
    md_path = dated_artifact_path(paths, "pathway-decision")
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_pathway_decision_report(record))
    render_html(md_path, html_path)
    return {
        "records": [record],
        "findings": [],
        "decision": record,
        "decision_ledger": str(paths.pathway_decisions_path),
        "report": str(md_path),
        "html": str(html_path),
    }


def run_pfos_cockpit(args, paths):
    snapshot = build_pfos_cockpit(paths)
    write_json(paths.pfos_cockpit_path, snapshot)
    md_path = dated_artifact_path(paths, "pfos-cockpit")
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_pfos_cockpit_report(snapshot))
    render_html(md_path, html_path)
    return {
        "records": [snapshot],
        "findings": [],
        "pfos_cockpit": str(paths.pfos_cockpit_path),
        "report": str(md_path),
        "html": str(html_path),
        "summary": {
            "trust": snapshot.get("trust", {}).get("status"),
            "recommendation": (snapshot.get("recommendation") or {}).get("pathway"),
            "proof_status": (snapshot.get("recommendation") or {}).get("proof_status"),
            "alex_queue_count": len(snapshot.get("alex_queue", [])),
            "autonomous_queue_count": len(snapshot.get("autonomous_queue", [])),
        },
    }


def render_cockpit_report(cockpit):
    top = cockpit.get("portfolio_top") or {}
    rec = cockpit.get("latest_recommendation") or {}
    metric = cockpit.get("metric") or {}
    lines = [
        "# Operating Layer Cockpit",
        "",
        f"Generated: {cockpit.get('generated_at')}",
        "",
        "## What Is Happening",
        "",
        f"- Trust: `{cockpit.get('trust', {}).get('status', 'unknown')}` ({cockpit.get('trust', {}).get('summary', '')})",
        f"- Active work items: {cockpit.get('active_work_count', 0)}",
        f"- Proofs recorded: {cockpit.get('proof_count', 0)}",
        f"- Stale proofs: {len(cockpit.get('stale_proofs', []))}",
        f"- Critical prose-only rule gaps: {len(cockpit.get('critical_rule_gaps', []))}",
        "",
        "## What Matters",
        "",
        f"- Portfolio top project: `{top.get('project', 'none')}` score={top.get('score', 0)} reason={'; '.join(top.get('reasons', [])[:2])}",
        f"- Latest recommendation: `{rec.get('project', 'none')}` -> `{rec.get('pathway', 'none')}` ({rec.get('recommendation_id', '')})",
        f"- Recommendation acted-on rate: {metric.get('acted_on_rate', metric.get('rate', 'n/a'))}",
        f"- Recommendation proved rate: {metric.get('proved_rate', 'n/a')}",
        "",
        "## What To Do Next",
        "",
    ]
    if top:
        lines.append(f"- Run `pathway-run --project {top.get('project')}` or open the portfolio report for `{top.get('project')}`.")
    elif rec:
        lines.append(f"- Continue latest recommendation `{rec.get('recommendation_id')}`.")
    else:
        lines.append("- Run `portfolio-next` and `pathway-next --project <project>` to seed the cockpit.")
    lines += ["", "## Source Links", ""]
    for label, path in cockpit.get("source_paths", {}).items():
        lines.append(f"- {label}: `{path}`")
    lines += ["", "## Latest Artifacts", ""]
    for artifact in cockpit.get("latest_artifacts", []):
        lines.append(f"- `{artifact.get('name')}`: `{artifact.get('path')}`")
    if not cockpit.get("latest_artifacts"):
        lines.append("- No artifacts found.")
    return "\n".join(lines) + "\n"


def run_cockpit(args, paths):
    cockpit = build_cockpit(paths)
    write_json(paths.cockpit_path, cockpit)
    md_path = dated_artifact_path(paths, "cockpit")
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_cockpit_report(cockpit))
    render_html(md_path, html_path)
    return {
        "records": [cockpit],
        "findings": [],
        "cockpit": str(paths.cockpit_path),
        "report": str(md_path),
        "html": str(html_path),
        "summary": {
            "trust": cockpit.get("trust", {}).get("status"),
            "top_project": (cockpit.get("portfolio_top") or {}).get("project"),
            "active_work_count": cockpit.get("active_work_count"),
            "critical_rule_gaps": len(cockpit.get("critical_rule_gaps", [])),
        },
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


# Gap E (tier calibration) thresholds. A tier needs at least MIN_TIER_CALIBRATION_OUTCOMES closed
# outcomes before its history is trusted to calibrate anything (one close is noise, not a signal).
MIN_TIER_CALIBRATION_OUTCOMES = 2
TIER_NEED_THRESHOLD = 0.5   # proved in >= this fraction of a tier's closes -> empirically needed
TIER_DROP_THRESHOLD = 0.5   # a DEFAULT pathway marked N/A this often -> over-included (drop candidate)
TIER_ADD_THRESHOLD = 0.5    # a NON-default pathway proved this often -> under-included (add candidate)


def compute_tier_calibration(paths, min_outcomes=MIN_TIER_CALIBRATION_OUTCOMES,
                             need=TIER_NEED_THRESHOLD, drop=TIER_DROP_THRESHOLD, add=TIER_ADD_THRESHOLD):
    """Gap E: measure each tier's REAL pathway needs from closed-outcome history and surface where
    the measured signal diverges from the hardcoded PATHWAY_TIERS default. Advisory only — it never
    mutates the map (the coverage guarantee forbids silently dropping a pathway); a human adopts
    confirmed changes by ADR. Tier definitions are global, so it aggregates closed outcomes across
    ALL projects. A tier with fewer than `min_outcomes` closes makes no calibration claim."""
    items = read_ndjson(paths.work_items_path)
    closed = [w for w in items if w.get("status") in ("closed", "done") and w.get("tier") in PATHWAY_TIERS]

    def canon_key(pathway):
        idx = PATHWAY_CANON_ORDER.index(pathway) if pathway in PATHWAY_CANON_ORDER else len(PATHWAY_CANON_ORDER)
        return (idx, pathway)  # name tiebreak keeps off-canon pathways deterministically ordered

    tiers = []
    for tier, default in PATHWAY_TIERS.items():
        outcomes = [w for w in closed if w.get("tier") == tier]
        m = len(outcomes)
        proved, na = {}, {}
        for w in outcomes:
            # One status per pathway per outcome (last entry wins) so a duplicated/corrupted
            # itinerary can never count a pathway twice and push a rate above 1.0.
            status_by_pathway = {}
            for entry in w.get("itinerary", []) or []:
                pathway = entry.get("pathway")
                if pathway:
                    status_by_pathway[pathway] = entry.get("status")
            for pathway, status in status_by_pathway.items():
                if status == "proved":
                    proved[pathway] = proved.get(pathway, 0) + 1
                elif status == "na":
                    na[pathway] = na.get(pathway, 0) + 1
        seen = set(proved) | set(na) | set(default)
        # Raw rates drive the threshold comparisons; rounding is display-only, so a value just under
        # a threshold can never round up into a claim.
        raw_proved = {p: (proved.get(p, 0) / m if m else 0.0) for p in seen}
        raw_na = {p: (na.get(p, 0) / m if m else 0.0) for p in seen}
        proved_rate = {p: round(raw_proved[p], 3) for p in seen}
        na_rate = {p: round(raw_na[p], 3) for p in seen}
        sufficient = m >= min_outcomes
        default_set = set(default)
        if sufficient:
            measured_required = sorted((p for p in seen if raw_proved[p] >= need), key=canon_key)
            drop_candidates = [{"pathway": p, "na_rate": na_rate[p]}
                               for p in default if raw_na.get(p, 0.0) >= drop]
            add_candidates = [{"pathway": p, "proved_rate": proved_rate[p]}
                              for p in sorted(seen - default_set, key=canon_key)
                              if raw_proved.get(p, 0.0) >= add]
        else:
            measured_required, drop_candidates, add_candidates = [], [], []
        tiers.append({
            "tier": tier,
            "heuristic_default": list(default),
            "closed_outcomes": m,
            "sufficient": sufficient,
            "min_outcomes": min_outcomes,
            "proved_rate": proved_rate,
            "na_rate": na_rate,
            "measured_required": measured_required,
            "drop_candidates": drop_candidates,
            "add_candidates": add_candidates,
            "diverges_from_default": bool(drop_candidates or add_candidates),
        })
    return {
        "metric": "tier calibration (measured tier->pathway defaults)",
        "generated_at": iso_now(),
        "thresholds": {"min_outcomes": min_outcomes, "need": need, "drop": drop, "add": add},
        "tiers": tiers,
    }


def render_tier_calibration_report(cal):
    th = cal.get("thresholds", {})
    lines = [
        "# Tier Calibration — measured tier->pathway defaults",
        "",
        f"Generated: {cal.get('generated_at', '')}",
        "",
        "The tier->pathway map is a heuristic. This compares it against what closed outcomes actually "
        "needed (proved) versus did not (marked N/A). **Advisory only** — adopt changes by ADR; the "
        "engine never auto-edits the map, because silently dropping a pathway would break the coverage guarantee.",
        "",
        f"Thresholds: >={int(th.get('need', 0.5) * 100)}% proved = needed · "
        f">={int(th.get('drop', 0.5) * 100)}% N/A = drop-candidate · "
        f">={int(th.get('add', 0.5) * 100)}% proved (non-default) = add-candidate · "
        f"min {th.get('min_outcomes', 2)} closes to calibrate.",
        "",
    ]
    for t in cal.get("tiers", []):
        lines += [f"## `{t['tier']}` — {t['closed_outcomes']} closed outcome(s)", ""]
        if not t["sufficient"]:
            lines += [f"_Insufficient history ({t['closed_outcomes']} < {t['min_outcomes']}) — default unchanged._", ""]
            continue
        lines += [
            f"- **Heuristic default:** {', '.join(t['heuristic_default'])}",
            f"- **Measured-required:** {', '.join(t['measured_required']) or '—'}",
        ]
        if t["drop_candidates"]:
            lines.append("- **Drop candidates (over-included):** " + ", ".join(
                f"`{d['pathway']}` (N/A {int(d['na_rate'] * 100)}%)" for d in t["drop_candidates"]))
        if t["add_candidates"]:
            lines.append("- **Add candidates (under-included):** " + ", ".join(
                f"`{a['pathway']}` (proved {int(a['proved_rate'] * 100)}%)" for a in t["add_candidates"]))
        if not t["diverges_from_default"]:
            lines.append("- Measured need matches the heuristic default — no change suggested.")
        lines += [""]
    lines += [
        "## Plain-English Summary",
        "",
        "**What we're building** — A way to check whether our preset checklists for \"how done is done\" "
        "match what finished work actually needed.",
        "",
        "**Why this piece** — The presets were an educated guess. Now that real projects have finished, we "
        "can see which steps they always needed and which they always skipped.",
        "",
        "**The surprise** — Sometimes a step we assumed was required gets skipped every time, and a step we "
        "left off the list gets done every time.",
        "",
        "**The real problem I caught** — Editing the checklist automatically could let the system quietly drop "
        "a step that mattered, so this only advises — a person makes the call.",
        "",
        "**Where we are right now** — Read-only. It reports the gap between the preset and the evidence and "
        "changes nothing on its own.",
        "",
        "**The one thing left** — A human decides whether to adopt a suggested change. Fully reversible; nothing ships.",
    ]
    return "\n".join(lines)


def run_tier_calibrate(args, paths):
    cal = compute_tier_calibration(paths)
    write_json(paths.operator_intel / "tier-calibration.json", cal)
    md_path = dated_artifact_path(paths, "tier-calibration")
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_tier_calibration_report(cal))
    render_html(md_path, html_path)
    return {
        "records": cal["tiers"],
        "findings": [],
        "tiers": cal["tiers"],
        "thresholds": cal["thresholds"],
        "written": str(paths.operator_intel / "tier-calibration.json"),
        "report": str(md_path),
        "html": str(html_path),
    }


# Circular-validation fix: an INDEPENDENT judge records whether a recommendation was the right
# next move. This is the only non-self signal that the picks are good — distinct from proved_rate
# (which only measures self-follow-through). Verdict vocabulary kept small and checkable.
SELF_PROJECT = "pathway-operating-layer"
VALID_VERDICTS = ("correct", "wrong", "late", "missed_blocker", "unnecessary")


def render_evaluations_report(summary, evals):
    by_verdict = summary.get("by_verdict", {})
    lines = [
        "# Pathway Recommendation Evaluation — independent verdicts",
        "",
        f"Generated: {summary.get('generated_at', '')}",
        "",
        "Independent judges scoring whether `pathway-next` picked the RIGHT next move — the first",
        "non-self signal that the recommendations are good, not merely that the tool tracked its own work.",
        "",
        f"- **Precision (correct / judged):** {summary.get('precision', 0)} "
        f"({summary.get('correct', 0)}/{summary.get('total', 0)})",
        f"- **External projects judged (not the tool itself):** {summary.get('external_projects_judged', 0)}",
        f"- **Verdict mix:** " + (", ".join(f"{k}={v}" for k, v in by_verdict.items()) or "—"),
        "",
        "| Project | Recommended | Verdict | Counterfactual | Judge | Note |",
        "|---|---|---|---|---|---|",
    ]
    for e in evals[-50:]:
        lines.append("| {p} | `{rp}` | {v} | {cf} | {j} | {n} |".format(
            p=e.get("project", ""), rp=e.get("pathway", ""), v=e.get("verdict", ""),
            cf=e.get("counterfactual", "") or "—", j=e.get("judge", ""),
            n=safe_display_text(e.get("note", ""), 60)))
    if summary.get("external_projects_judged", 0) == 0:
        lines += ["", "> No EXTERNAL project judged yet — every verdict so far is on the tool itself, which is "
                  "still circular. Judge `pathway-next` on real outside projects to earn a non-self signal."]
    return "\n".join(lines)


def run_pathway_evaluate(args, paths):
    evals = read_ndjson(paths.evaluations_path)
    if getattr(args, "summary", False):
        total = len(evals)
        correct = sum(1 for e in evals if e.get("verdict") == "correct")
        by_verdict = {}
        for e in evals:
            by_verdict[e.get("verdict", "?")] = by_verdict.get(e.get("verdict", "?"), 0) + 1
        external = {e.get("project") for e in evals if e.get("project") and e.get("project") != SELF_PROJECT}
        summary = {
            "metric": "recommendation precision (independent judgments)",
            "generated_at": iso_now(),
            "total": total,
            "correct": correct,
            "precision": round(correct / total, 3) if total else 0.0,
            "by_verdict": by_verdict,
            "external_projects_judged": len(external),
        }
        write_json(paths.operator_intel / "pathway-evaluations-summary.json", summary)
        md_path = dated_artifact_path(paths, "pathway-evaluations")
        html_path = md_path.with_suffix(".html")
        write_text(md_path, render_evaluations_report(summary, evals))
        render_html(md_path, html_path)
        return {"records": evals, "findings": [], "summary": summary, "report": str(md_path), "html": str(html_path)}

    verdict = (args.verdict or "").strip().lower()
    if verdict not in VALID_VERDICTS:
        return {"findings": [finding(
            "pathway-evaluate-bad-verdict", "pathway-evaluate", "warn",
            f"Verdict must be one of {', '.join(VALID_VERDICTS)} (got {args.verdict!r}).",
            [line_evidence(paths.evaluations_path)],
            "Record a verdict: --verdict correct|wrong|late|missed_blocker|unnecessary --judge <who>.",
            "static", "high")], "records": []}
    if not (args.judge or "").strip():
        return {"findings": [finding(
            "pathway-evaluate-missing-judge", "pathway-evaluate", "warn",
            "An evaluation needs an independent --judge (who judged the recommendation).",
            [line_evidence(paths.evaluations_path)],
            "Pass --judge <identity> — ideally NOT the agent that produced the recommendation.",
            "static", "high")], "records": []}
    project = Path(args.project).name if args.project else ""
    record = {
        "evaluation_id": f"EVAL-{safe_slug(project)}-{safe_slug(args.pathway or '')}-{len(evals) + 1:04d}",
        "timestamp": iso_now(),
        "recommendation_id": args.recommendation_id or "",
        "project": project,
        "pathway": args.pathway or "",
        "verdict": verdict,
        "counterfactual": getattr(args, "counterfactual", None) or "",
        "judge": args.judge.strip(),
        "note": getattr(args, "note", None) or "",
        "is_self": project == SELF_PROJECT,
        "source": "operating-layer pathway-evaluate",
    }
    evals.append(record)
    write_ndjson(paths.evaluations_path, evals)
    return {"records": [record], "findings": [], "evaluation_id": record["evaluation_id"]}


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
        "improve", "compare", "portfolio-next", "rule-map", "cockpit", "pfos-cockpit", "work-start", "work-status", "work-log", "work-close", "work-cover", "work-daily",
        "proof-add", "proof-report", "pathway-trust", "pathway-next", "pathway-run",
        "pathway-decision", "ingest-review", "pathway-metric", "tier-calibrate", "pathway-evaluate", "all"
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
    parser.add_argument("--action", choices=["approve", "reject", "assign", "closeout"], help="pathway-decision action.")
    parser.add_argument("--agent", help="pathway-decision assignee label.")
    parser.add_argument("--reason", help="pathway-decision rationale.")
    parser.add_argument("--proof-id", help="pathway-decision proof id for proof-backed closeout.")
    parser.add_argument("--proof-type", help="Proof type to record with proof-add or work-log.")
    parser.add_argument("--verified-by", help="Free-text label for the verification (attestation only — does NOT prove on its own).")
    parser.add_argument("--verify-cmd", help="Verifier command the engine RE-EXECUTES; the pathway proves only if it exits 0 (executed proof).")
    parser.add_argument("--reviewer", help="Named human reviewer signing off over the hashed artifact (signed proof).")
    parser.add_argument("--verdict", help="pathway-evaluate verdict: correct|wrong|late|missed_blocker|unnecessary.")
    parser.add_argument("--judge", help="pathway-evaluate: who independently judged the recommendation.")
    parser.add_argument("--counterfactual", help="pathway-evaluate: the pathway the judge would have picked instead.")
    parser.add_argument("--note", help="pathway-evaluate: short free-text rationale for the verdict.")
    parser.add_argument("--summary", action="store_true", help="pathway-evaluate: report precision across recorded verdicts.")
    parser.add_argument("--recommendation-id", help="pathway-next recommendation_id this proof satisfies.")
    parser.add_argument("--control-risk", help="Create a control from this pathway risk.")
    parser.add_argument("--control-id", help="Existing control id to update.")
    parser.add_argument("--control-status", choices=["open", "resolved"], help="Control status for creation or update.")
    parser.add_argument("--target-pathways", help="Comma-separated pathways affected by a control.")
    parser.add_argument("--stale-after-days", type=int, default=WORK_STALE_DAYS)
    parser.add_argument("--input", help="review-stack --json input file for ingest-review (or '-' / omit for stdin).")
    parser.add_argument("--window-days", type=int, help="pathway-metric: days after a recommendation to count a matching work-log as acted-on (default 1).")
    parser.add_argument("--gate-target", type=float, help="pathway-metric: minimum acted-on rate to pass the gate (default 0.5).")
    parser.add_argument("--tier", choices=list(PATHWAY_TIERS.keys()), help="work-start: target 'done' tier sizing the required-pathway itinerary (default live).")
    parser.add_argument("--na", action="store_true", help="work-cover: mark the pathway not-applicable (requires --reason).")
    parser.add_argument("--add", action="store_true", help="work-cover: append the pathway to the itinerary as newly required.")
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
    elif args.subcommand == "portfolio-next":
        result = run_portfolio_next(args, paths)
    elif args.subcommand == "rule-map":
        result = run_rule_map(args, paths)
    elif args.subcommand == "cockpit":
        result = run_cockpit(args, paths)
    elif args.subcommand == "pfos-cockpit":
        result = run_pfos_cockpit(args, paths)
    elif args.subcommand == "work-start":
        result = run_work_start(args, paths)
    elif args.subcommand == "work-status":
        result = run_work_status(args, paths)
    elif args.subcommand == "work-log":
        result = run_work_log(args, paths)
    elif args.subcommand == "work-close":
        result = run_work_close(args, paths)
    elif args.subcommand == "work-cover":
        result = run_work_cover(args, paths)
    elif args.subcommand == "work-daily":
        result = run_work_daily(args, paths)
    elif args.subcommand == "proof-add":
        result = run_proof_add(args, paths)
    elif args.subcommand == "proof-report":
        result = run_proof_report(args, paths)
    elif args.subcommand == "pathway-trust":
        result = run_pathway_trust(args, paths)
    elif args.subcommand == "pathway-next":
        result = run_pathway_next(args, paths)
    elif args.subcommand == "pathway-run":
        result = run_pathway_run(args, paths)
    elif args.subcommand == "pathway-decision":
        result = run_pathway_decision(args, paths)
    elif args.subcommand == "ingest-review":
        result = run_ingest_review(args, paths)
    elif args.subcommand == "pathway-metric":
        result = run_pathway_metric(args, paths)
    elif args.subcommand == "tier-calibrate":
        result = run_tier_calibrate(args, paths)
    elif args.subcommand == "pathway-evaluate":
        result = run_pathway_evaluate(args, paths)
    else:
        result = run_all(args, paths)
    print_result(result, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
