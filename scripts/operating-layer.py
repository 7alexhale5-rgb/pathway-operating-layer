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
import contextlib
import fcntl
import hashlib
import html
import json
import math
import os
import re
import secrets
import shutil
import shlex
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType


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
APPROVAL_AUTHORITY_PATH = Path(
    "/Library/Application Support/Pathway/approval-authority.ndjson"
    if sys.platform == "darwin"
    else "/var/lib/pathway/approval-authority.ndjson"
)
APPROVAL_HELPER_PATH = Path("/usr/local/libexec/pathway-approval")

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
# Append-only ledgers (proofs, runs, measurements) are read WHOLE. safe_read_text truncates from
# the FRONT, so a cap smaller than the file silently drops the NEWEST records. On 2026-08-13
# proofs.ndjson crossed the previous 5MB cap by ~1.2KB and a freshly verified proof became
# invisible to the coverage join while work-log, the proof receipt, and proof_is_verified() all
# still reported success. Raise this before a ledger reaches it, and never let truncation be silent.
NDJSON_READ_MAX_BYTES = 64_000_000
MAX_SCAN_FILES = 20_000
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(?:xai-|xai_api_|gsk_|ghp_|github_pat_|sk-ant-|sk-or-v1-)[A-Za-z0-9_\-]{16,}"),
    # Cloud-provider credential shapes shorter than the 64-char entropy floor.
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                              # AWS access key ID
    re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*[A-Za-z0-9/+=]{40}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),                        # Google API key
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),                 # Slack token
    re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),   # Stripe key
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b"),                     # GitLab PAT
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|pwd)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)authorization\s*:\s*bearer\s+[^\s,;]+"),
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

# Canonical execution order is the single source of truth for recommendation tie-breaks
# and itinerary walking. `field` is an extension pathway: first-class when triggered, but
# not part of the 11 core pathways or base tier defaults.
CORE_PATHWAYS = [
    "govern",
    "research",
    "data",
    "security",
    "design",
    "implementation",
    "quality",
    "observability",
    "techdebt",
    "release",
    "docs",
]
EXTENSION_PATHWAYS = ["field"]
PATHWAY_CANON_ORDER = [
    "govern",
    "research",
    "data",
    "security",
    "design",
    "implementation",
    "quality",
    "field",
    "observability",
    "techdebt",
    "release",
    "docs",
]
PATHWAY_ORDER = list(PATHWAY_CANON_ORDER)
CANONICAL_PATHWAY_CATALOG = "govern, research, data, security, design, implementation, quality, field, observability, techdebt, release, docs"

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
    "field": r"\b(client|customer|stakeholder|feedback|approval|review packet|operator validation|field|send-ready|sent)\b",
}

DEFAULT_ITINERARY_TIER = "live"

OUTCOME_PROFILES = [
    {
        "id": "customer-field-review",
        "label": "Customer field review",
        "pattern": r"\b(client|customer|stakeholder|feedback|approval|review packet|send-ready|sent|outreach|field)\b",
        "default_tier": "live",
        "required_pathways": ["govern", "field"],
        "overlays": ["human-gate"],
    },
    {
        "id": "production-secure-launch",
        "label": "Production-secure launch",
        "pattern": r"\b(production|prod|public|launch|deploy|external|compliance|tenant|auth|rls|pii|secret)\b",
        "default_tier": "production-secure",
        "required_pathways": ["security", "observability", "release"],
        "overlays": ["production-mutation", "rollback"],
    },
    {
        "id": "data-integration",
        "label": "Data integration",
        "pattern": r"\b(schema|migration|migrate|database|db|supabase|postgres|sql|sftp|api|webhook|integration|import|export)\b",
        "default_tier": "live",
        "required_pathways": ["data", "security", "quality"],
        "overlays": ["tenant-authz"],
    },
    {
        "id": "agent-automation",
        "label": "Agent automation",
        "pattern": r"\b(agent|llm|prompt|tool call|automation|autonomy|rag|memory|a2a|mcp|eval)\b",
        "default_tier": "live",
        "required_pathways": ["security", "quality", "observability"],
        "overlays": ["llm-agent-eval"],
    },
    {
        "id": "ui-slice",
        "label": "UI slice",
        "pattern": r"\b(ui|ux|screen|component|page|frontend|front-end|layout|form|dashboard|a11y|accessibility|responsive|visual)\b",
        "default_tier": "live",
        "required_pathways": ["design", "implementation", "quality"],
        "overlays": ["ui-proof"],
    },
    {
        "id": "tiny-fix",
        "label": "Tiny fix",
        "pattern": r"\b(typo|copy edit|tiny fix|small fix|one-line|one line|trivial)\b",
        "default_tier": "demoable",
        "required_pathways": ["govern", "quality"],
        "overlays": [],
    },
    {
        "id": "standard-bugfix",
        "label": "Standard bugfix",
        "pattern": r"\b(bug|fix|regression|broken|failure|failing|crash|error)\b",
        "default_tier": "live",
        "required_pathways": ["govern", "implementation", "quality"],
        "overlays": [],
    },
]

DEFAULT_OUTCOME_PROFILE = {
    "id": "internal-live-feature",
    "label": "Internal live feature",
    "default_tier": DEFAULT_ITINERARY_TIER,
    "required_pathways": [],
    "overlays": [],
}

RISK_OVERLAYS = {
    "tenant-authz": {
        "title": "Tenant authorization",
        "pattern": r"\b(rls|tenant|multi-tenant|authz|authorization|role|membership|client portal|anon|policy|row level)\b",
        "required_pathways": ["data", "security"],
    },
    "privacy-evidence": {
        "title": "Privacy and evidence hygiene",
        "pattern": r"\b(pii|phi|hipaa|customer data|client data|screenshot|log|redact|secret|credential|password)\b",
        "required_pathways": ["security", "docs"],
    },
    "production-mutation": {
        "title": "Production mutation",
        "pattern": r"\b(production|prod|migration|migrate|deploy|database write|destructive|drop table|delete data|feature flag|flag)\b",
        "required_pathways": ["data", "security", "release"],
    },
    "rollback": {
        "title": "Rollback",
        "pattern": r"\b(rollback|release|deploy|canary|rollout|feature flag|flag)\b",
        "required_pathways": ["release", "observability"],
    },
    "supply-chain": {
        "title": "Supply chain",
        "pattern": r"\b(dependency|dependencies|lockfile|package|npm audit|cve|sbom|osv|license)\b",
        "required_pathways": ["security", "techdebt"],
    },
    "incident-response": {
        "title": "Incident response",
        "pattern": r"\b(incident|sev|alert|runbook|outage|paging|pager|postmortem)\b",
        "required_pathways": ["observability", "docs", "release"],
    },
    "ui-proof": {
        "title": "Rendered UI proof",
        "pattern": r"\b(ui|ux|screen|component|page|frontend|front-end|layout|form|dashboard|a11y|accessibility|responsive|visual)\b",
        "required_pathways": ["design", "quality"],
    },
    "llm-agent-eval": {
        "title": "LLM/agent evaluation",
        "pattern": r"\b(llm|agent|prompt|tool call|automation|autonomy|hallucination|eval|rag|memory|mcp|a2a)\b",
        "required_pathways": ["quality", "security", "observability"],
    },
    "human-gate": {
        "title": "Human/customer gate",
        "pattern": r"\b(client|customer|stakeholder|feedback|approval|review packet|send-ready|sent|outreach|field)\b",
        "required_pathways": ["field", "govern"],
    },
}


def pathway_sort_key(pathway):
    return PATHWAY_CANON_ORDER.index(pathway) if pathway in PATHWAY_CANON_ORDER else 99


def _signal_text(*parts):
    chunks = []
    for part in parts:
        if isinstance(part, dict):
            chunks.extend(str(v) for v in part.values())
        elif isinstance(part, list):
            chunks.extend(_signal_text(p) for p in part)
        elif part:
            chunks.append(str(part))
    return " ".join(chunks).lower()


def finding_signal_text(scoped_findings):
    bits = []
    for item in scoped_findings or []:
        bits.extend([
            item.get("id", ""),
            item.get("message", ""),
            item.get("workflow", ""),
            item.get("pathway", ""),
            item.get("severity", ""),
        ])
    return _signal_text(bits)


def carry_forward_signal_text(carry_forward):
    if not carry_forward:
        return ""
    bits = [
        carry_forward.get("summary", ""),
        carry_forward.get("pathway", ""),
        carry_forward.get("what_changed", []),
        carry_forward.get("more_relevant", []),
        carry_forward.get("less_relevant", []),
        carry_forward.get("next_pathway_must_use", []),
        carry_forward.get("do_not_do_yet", []),
        carry_forward.get("open_decisions", []),
        carry_forward.get("active_risk_overlays", []),
    ]
    return _signal_text(bits)


def carry_forward_positive_signal_text(carry_forward):
    """Signals that can safely classify current work.

    Deferrals (`less_relevant`, `do_not_do_yet`, conditional `next_pathway_must_use`,
    and open decisions) are constraints, not evidence that a risk is active now. Scanning
    them as normal text turns "do not add A2A yet" into an active A2A/agent overlay.
    """
    if not carry_forward:
        return ""
    bits = [
        carry_forward.get("summary", ""),
        carry_forward.get("pathway", ""),
        carry_forward.get("what_changed", []),
        carry_forward.get("more_relevant", []),
        carry_forward.get("active_risk_overlays", []),
    ]
    return _signal_text(bits)


def carry_forward_active_overlay_ids(carry_forward):
    if not carry_forward:
        return []
    return [
        str(overlay_id).strip()
        for overlay_id in carry_forward.get("active_risk_overlays", []) or []
        if str(overlay_id).strip()
    ]


def carry_forward_next_pathways(carry_forward):
    """Return pathways the baton explicitly says to run/use next.

    This intentionally does not treat every pathway name in the baton as a directive:
    lines like "if the next recommendation is design" or "future A2A work must re-open
    security" are guardrails, not current next-pathway orders.
    """
    refs = set()
    for item in carry_forward.get("next_pathway_must_use", []) if carry_forward else []:
        text = str(item).strip().lower()
        if not text:
            continue
        if re.match(r"^(if|when|any future|future|do not|don't|decide later)\b", text):
            continue
        if ("when deciding whether" in text or "if the next" in text
                or "before any stage" in text or "before any promotion" in text):
            continue
        for pathway in PATHWAY_ORDER:
            escaped = re.escape(pathway)
            if re.search(rf"\b(?:non[- ]|not\s+|avoid\s+){escaped}\b", text):
                continue
            if re.search(rf"\b{escaped}\b\s+must\s+use\b", text):
                refs.add(pathway)
            elif re.search(
                rf"\b{escaped}\b\s+must\s+"
                r"(?:close|complete|deliver|implement|produce|prove|resolve|run|verify)\b",
                text,
            ):
                refs.add(pathway)
            elif re.search(rf"\b(next|run|recommend|route|handoff|proceed|start|feed)\b[^.:\n]{{0,100}}\b{escaped}\b", text):
                refs.add(pathway)
    return sorted(refs, key=pathway_sort_key)


def carry_forward_deferred_pathways(carry_forward):
    """Return pathways explicitly prohibited by the latest carry-forward.

    Deferrals do not erase itinerary obligations. They only stop the router from selecting a
    prohibited move while another required prerequisite remains open. Release and observability
    holds are structured outcomes; their narrow prose fallbacks preserve older carry-forwards.
    """
    deferred = set()
    if (carry_forward and carry_forward.get("pathway") == "release"
            and carry_forward.get("credits_pathway") is False
            and carry_forward.get("pathway_outcome") == "blocked_no_deploy"):
        deferred.add("release")
    if (carry_forward and carry_forward.get("pathway") == "observability"
            and carry_forward.get("credits_pathway") is False
            and carry_forward.get("pathway_outcome") == "blocked_no_runtime"):
        deferred.add("observability")
    for item in carry_forward.get("do_not_do_yet", []) if carry_forward else []:
        text = str(item).strip().lower()
        if not re.match(r"^(do not|don't|never)\b", text):
            continue
        if re.search(r"\b(deploy|deployment|release|rollout|production mutation)\b|feature[- ]?flag", text):
            deferred.add("release")
        # Prose fallbacks only defer when observability itself is the direct prohibited object.
        # Nested negatives and prerequisite clauses are requirements, not deferrals.
        direct_observability_prohibition = re.match(
            r"^(?:do not|don't|never)\s+(?:claim|credit|mark|prove|close|wire|enable|implement|run|start|perform)\s+observability\b",
            text,
        )
        direct_telemetry_prohibition = re.match(
            r"^(?:do not|don't|never)\s+(?:wire|enable|claim|add|configure)\s+(?:telemetry|alerts?)\b",
            text,
        )
        observability_prerequisite = re.search(
            r"\b(?:until|unless)\b[^.\n]{0,80}\b(?:observability|telemetry|alerts?)\b"
            r"|\bbefore\s+(?:observability|telemetry|alerts?)\b",
            text,
        )
        if (not observability_prerequisite
                and (direct_observability_prohibition or direct_telemetry_prohibition)):
            deferred.add("observability")
    return sorted(deferred, key=pathway_sort_key)


def classify_outcome_profile(goal="", project_name="", scoped_findings=None, carry_forward=None):
    """Choose the outcome shape before scoring pathways.

    Profiles are intentionally coarse. They do not replace proof state; they only seed a
    better itinerary and make the recommendation explain which kind of development cycle
    this work appears to be.
    """
    text = _signal_text(goal, project_name, carry_forward_positive_signal_text(carry_forward))
    for profile in OUTCOME_PROFILES:
        if re.search(profile["pattern"], text):
            return {k: v for k, v in profile.items() if k != "pattern"}
    return dict(DEFAULT_OUTCOME_PROFILE)


def detect_risk_overlays(goal="", project_name="", scoped_findings=None, carry_forward=None, profile=None):
    """Detect advisory-but-binding risk overlays.

    Overlays are not new pathway categories; they are reasons to pull existing pathways
    into the itinerary. The ledger/proof layer remains authoritative for status.
    """
    text = _signal_text(goal, project_name, finding_signal_text(scoped_findings),
                        carry_forward_positive_signal_text(carry_forward))
    wanted = set((profile or {}).get("overlays", []) or [])
    wanted.update(carry_forward_active_overlay_ids(carry_forward))
    for overlay_id, overlay in RISK_OVERLAYS.items():
        if re.search(overlay["pattern"], text):
            wanted.add(overlay_id)
    overlays = []
    for overlay_id in sorted(wanted, key=lambda oid: list(RISK_OVERLAYS).index(oid) if oid in RISK_OVERLAYS else 99):
        overlay = RISK_OVERLAYS.get(overlay_id)
        if not overlay:
            continue
        overlays.append({
            "id": overlay_id,
            "title": overlay["title"],
            "required_pathways": list(overlay.get("required_pathways", [])),
            "reason": "matched profile or risk signal",
        })
    return overlays



# Design used to enter an itinerary only when the GOAL SENTENCE happened to say
# "ui"/"screen"/"page" (PATHWAY_KEYWORD_GATES). Measured 2026-08-28: 58 of 321 work
# items (18%) ever carried design, and affiliate-desk -- a live Next.js app -- was
# closure-eligible having never passed a design gate. evansville-tonight got one only
# because a human added it by hand mid-run, reason "revealed during execution".
#
# A repo either renders an interface or it does not. That is a property of the code,
# not of how the goal was phrased, so it is read from the code.
UI_FILE_GLOBS = ("*.tsx", "*.jsx", "*.vue", "*.svelte")
UI_CONFIG_NAMES = (
    "tailwind.config.js", "tailwind.config.ts", "tailwind.config.mjs",
    "tailwind.config.cjs", "postcss.config.js", "postcss.config.mjs",
)
_UI_REPO_CACHE = {}


def repo_has_ui(project_path):
    """True when the repo renders an interface.

    Deliberately cheap and bounded: a depth-limited scan for component files or a
    CSS-framework config. A false positive costs one `work-cover ... na`; a false
    negative is how a client site ships ungated, so this leans towards detecting.
    """
    if not project_path:
        return False
    root = Path(project_path)
    if not root.is_dir():
        return False
    key = str(root.resolve())
    if key in _UI_REPO_CACHE:
        return _UI_REPO_CACHE[key]

    found = False
    for name in UI_CONFIG_NAMES:
        if (root / name).exists() or (root / "web" / name).exists():
            found = True
            break
    if not found:
        # `templates` and `_vendored` hold harvested third-party code. Somebody
        # else's React app in our warehouse is not our interface to gate.
        skip = {
            "node_modules", ".git", ".next", "dist", "build", ".venv", "__pycache__",
            "templates", "_vendored", "vendor", "third_party", ".worktrees",
        }
        for depth_root, dirnames, filenames in os.walk(root):
            rel = Path(depth_root).relative_to(root)
            if len(rel.parts) > 3:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in skip and not d.endswith("-wt")]
            if any(fn.endswith((".tsx", ".jsx", ".vue", ".svelte")) for fn in filenames):
                found = True
                break
    _UI_REPO_CACHE[key] = found
    return found


def outcome_contract(goal="", project_path="", project_name="", scoped_findings=None, carry_forward=None, explicit_tier=None):
    project_label = project_name or (Path(project_path).name if project_path else "")
    profile = classify_outcome_profile(goal, project_label, scoped_findings, carry_forward)
    # Copy before touching: profiles come from the module-level OUTCOME_PROFILES list
    # and mutating one would leak into every later call in the process.
    if repo_has_ui(project_path):
        profile = dict(profile)
        required = list(profile.get("required_pathways", []) or [])
        if "design" not in required:
            required.append("design")
            profile["required_pathways"] = required
    overlays = detect_risk_overlays(goal, project_label, scoped_findings, carry_forward, profile)
    tier = (explicit_tier or profile.get("default_tier") or DEFAULT_ITINERARY_TIER).lower()
    if tier not in PATHWAY_TIERS:
        tier = DEFAULT_ITINERARY_TIER
    return {"outcome_profile": profile, "risk_overlays": overlays, "tier": tier}


def compute_itinerary(tier, goal, outcome_profile=None, risk_overlays=None):
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
    for pathway in (outcome_profile or {}).get("required_pathways", []) or []:
        if pathway in PATHWAY_CANON_ORDER:
            base.add(pathway)
    for overlay in risk_overlays or []:
        for pathway in overlay.get("required_pathways", []) or []:
            if pathway in PATHWAY_CANON_ORDER:
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
        retained_manual_requirement = (
            prev.get("status", "required") == "required"
            and prev.get("coverage_source") == "work-cover"
        )
        if pathway not in new_pathways and (
            prev.get("status") in ("proved", "na") or retained_manual_requirement
        ):
            merged.append(prev)
    merged.sort(key=lambda e: pathway_sort_key(e.get("pathway")))
    return merged


def itinerary_coverage(item):
    """Return (covered_count, total, [open_required_pathways]) for a work item.

    Covered = proved or na. Open required = still owed proof. The list is foundation-
    first so the router's next pick walks dependencies in order.
    """
    itin = (item or {}).get("itinerary") or []
    covered = [e for e in itin if e.get("status") in ("proved", "na")]
    open_required = [e.get("pathway") for e in itin if e.get("status", "required") == "required"]
    open_required.sort(key=pathway_sort_key)
    return len(covered), len(itin), open_required


WORK_STALE_DAYS = 14
REVIEW_STALE_DAYS = 14  # a .planning/review/latest-findings.json older than this is not trusted as current
# Flipped from VERIFIABLE_WAIVER_NOT_CONFIGURED on 2026-08-16 when the single-use waiver
# authority shipped (approval-issue + approvals.ndjson). The constant stays load-bearing as a
# kill switch: work-cover consults it before any ticket lookup, so setting it back to a
# non-configured value disables waivers again without touching the ticket machinery.
PRODUCTION_SECURE_WAIVER_STATE = "CONFIGURED_AND_VERIFIED"


def production_secure_waiver_locked(item):
    """Return True when tier or live risk classification makes proof non-waivable."""
    item = item if isinstance(item, dict) else {}
    profile = item.get("outcome_profile") if isinstance(item.get("outcome_profile"), dict) else {}
    overlays = item.get("risk_overlays") if isinstance(item.get("risk_overlays"), list) else []
    return (
        item.get("tier") == "production-secure"
        or profile.get("id") == "production-secure-launch"
        or any(overlay.get("id") == "production-mutation" for overlay in overlays
               if isinstance(overlay, dict))
    )

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
    "field": {
        "title": "Field — operator/customer validation",
        "foundation": False,
        "decision": "Did a real operator or customer review the right artifact, and what changed because of it?",
        "good": "Reviewer, artifact shown, feedback, blockers, send state, and next-pathway impact are recorded.",
        "artifact": "field packet or feedback note with reviewed artifact hash and unresolved blockers",
        "move": "Show the proof packet to the real reviewer, record what changed, and keep send-ready separate from sent.",
        "skill": "/review-gap-ideation",
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
        "stack": ["/review-stack --audit (primary, read-only)", "/build-stack to fix the top confirmed finding", "/review-stack --quick to prove the remediation", "/codex:adversarial-review (second model)"],
        "tools": ["reviewer agent", "local sec-guard scripts (no app-backed scan unless requested)", "koho-guardrail + secret guards", "project runtime evidence"],
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
    "field": {
        "stack": ["operator/customer review packet", "/review-gap-ideation", "feedback-to-carry-forward", "send-ready versus sent audit"],
        "tools": ["memory-vault decisions/", "client feedback artifact", "stakeholder-reviewer agent"],
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

TEAM_ROLE_BY_PATHWAY = {
    "govern": {
        "lead": "Product governor",
        "critic": "Premortem / stakeholder reviewer",
        "proof_gate": "Decision, target metric, tier, and stop condition are recorded.",
        "human_gate": "Alex approves the metric, tier, and business tradeoff before broad execution.",
    },
    "research": {
        "lead": "Research lead",
        "critic": "Devil's advocate",
        "proof_gate": "Cited dossier classifies unknowns as blocker, warn, or info.",
        "human_gate": "Alex reviews unresolved blocker assumptions before build decisions depend on them.",
    },
    "data": {
        "lead": "Data architect",
        "critic": "Database reviewer",
        "proof_gate": "Schema, migration, lineage, and real-row boundary proof exist.",
        "human_gate": "Alex approves production data mutations and tenant-boundary risk.",
    },
    "security": {
        "lead": "Security reviewer",
        "critic": "Adversarial reviewer",
        "proof_gate": "Trust boundaries, secrets, authz, and highest-risk exposure are verified closed.",
        "human_gate": "Alex approves any residual security risk or N/A security claim.",
    },
    "design": {
        "lead": "Product designer",
        "critic": "UX/a11y critic",
        "proof_gate": "Rendered UI proof covers workflow, responsive states, keyboard path, and a11y.",
        "human_gate": "Alex reviews visible UX changes before customer-facing release.",
    },
    "implementation": {
        "lead": "Implementer",
        "critic": "Code reviewer",
        "proof_gate": "Smallest end-to-end slice works on the user-visible artifact.",
        "human_gate": "Alex approves scope expansion beyond the governed slice.",
    },
    "quality": {
        "lead": "QA / eval engineer",
        "critic": "Second-model reviewer",
        "proof_gate": "Golden path, regression, or eval gate catches the relevant failure mode.",
        "human_gate": "Alex reviews failed gates, accepted risk, or test scope reductions.",
    },
    "field": {
        "lead": "Field reviewer",
        "critic": "Stakeholder reviewer",
        "proof_gate": "Reviewer, artifact shown, feedback, blockers, and send state are recorded.",
        "human_gate": "Alex controls external sends, customer commitments, and feedback disposition.",
    },
    "observability": {
        "lead": "SRE / observability engineer",
        "critic": "Incident reviewer",
        "proof_gate": "Critical journey signal, alert, and runbook delta exist.",
        "human_gate": "Alex approves alert noise, SLO tradeoffs, and incident-response ownership.",
    },
    "techdebt": {
        "lead": "Simplifier",
        "critic": "Refactor reviewer",
        "proof_gate": "Highest-cost duplication/dependency/dead path is removed or bounded.",
        "human_gate": "Alex approves risky refactors and abstraction expansion.",
    },
    "release": {
        "lead": "Release captain",
        "critic": "Rollback reviewer",
        "proof_gate": "Rollout, canary/flag, production proof, and rollback evidence exist.",
        "human_gate": "Alex controls deploys, prod flags, rollbacks, and external sends.",
    },
    "docs": {
        "lead": "Docs steward",
        "critic": "Operator reviewer",
        "proof_gate": "ADR, runbook, or handoff matches the current code/artifact state.",
        "human_gate": "Alex reviews strategic claims and customer-facing documentation.",
    },
}

HUMAN_GATE_OVERLAYS = {
    "human-gate",
    "production-mutation",
    "rollback",
    "privacy-evidence",
    "tenant-authz",
}

# Keyword -> pathway routing for findings. First match wins, scanned in order.
FINDING_PATHWAY_KEYWORDS = [
    ("security", ["secret", "rls", "anon-read", "anon_read", "auth", "ssrf", "leak", "credential", "exposure", "vuln", "service_role", "service-role"]),
    ("field", ["field", "customer", "client", "stakeholder", "feedback", "review packet", "send-ready", "sent", "approval", "operator validation"]),
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
    "ds-": "design",
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
    "field-": "field",
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


def local_day():
    """The calendar day a human would call today, in the machine's own timezone.

    Timestamps INSIDE an artifact stay UTC (see iso_now) because those are instants.
    A filename date is not an instant. It is the day the operator did the work, and
    it is what doc_freshness.py and operator-artifacts-supersede.py read to decide
    whether a document is stale. Stamping it from utc_now() dated every artifact
    written after 7pm CDT to tomorrow, and a document dated tomorrow can never read
    as stale. 175 artifacts were misdated this way between 2026-05-22 and 2026-08-11.
    """
    return datetime.now().strftime("%Y-%m-%d")


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


def _strict_verifier_markers(stdout, allowed_markers):
    """Parse a closed marker set and reject duplicate trusted keys."""
    markers, duplicate_keys = {}, set()
    for line in (stdout or "").splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=([^\r\n]+)$", line.strip())
        if not match or match.group(1) not in allowed_markers:
            continue
        key = match.group(1)
        if key in markers:
            duplicate_keys.add(key)
        else:
            markers[key] = match.group(2).strip()
    return markers, duplicate_keys


RELEASE_RECEIPT_STATES = {
    "preview_status": {"not-run", "ready", "failed"},
    "canary_status": {"not-run", "ready", "active", "passed", "failed"},
    "production_status": {"not-deployed", "deployed", "failed"},
    "rollback_status": {"not-needed", "ready", "rehearsed", "executed", "failed"},
    "external_send_state": {
        "not-sent", "send-ready", "sent", "blocked", "user-triggered-auth-only",
    },
    "feature_flag_state": {"not-used", "disabled", "enabled"},
}
RELEASE_RECEIPT_ARTIFACT_FIELDS = (
    "deploy_artifact", "verification_artifact", "canary_artifact", "rollback_artifact",
)
RELEASE_AUTH_SEND_ARTIFACT_FIELD = "external_send_artifact"
RELEASE_CONTEXT_FIELDS = ("work_id", "recommendation_id", "target_project")
RELEASE_MAX_EVIDENCE_AGE_SECONDS = 86_400
RELEASE_MAX_FUTURE_SKEW_SECONDS = 300
RELEASE_PROVIDER_ACTION_KIND = "release-provider-action"
RELEASE_PROVIDER_ACTIONS = {
    "apply-product-migration",
    "deploy-canary",
    "promote-public-stage",
}
# Flipped from VERIFIABLE_APPROVAL_NOT_CONFIGURED on 2026-08-16 when the single-use approval
# authority shipped. proof_is_verified still consults it, so it remains the release-credit kill
# switch; per-proof crediting additionally requires a consumed, ledger-corroborated ticket.
RELEASE_PRODUCTION_APPROVAL_STATE = "CONFIGURED_AND_VERIFIED"


def release_receipt_artifact_fields(receipt):
    """Return the closed artifact set required by one typed release receipt."""
    fields = list(RELEASE_RECEIPT_ARTIFACT_FIELDS)
    if (
        isinstance(receipt, dict)
        and receipt.get("external_send_state") == "user-triggered-auth-only"
    ):
        fields.append(RELEASE_AUTH_SEND_ARTIFACT_FIELD)
    return tuple(fields)


def validate_release_receipt(receipt, artifact_base=None, production_approval=False):
    """Validate a local release receipt without performing a release.

    A receipt can prove preview readiness while production stays `not-deployed`.
    Production and external-send claims have stronger, explicit evidence requirements.
    `production_approval` is True only when the caller has already located a live (or
    proof-bound consumed) single-use approval ticket for this exact receipt digest; the
    default keeps every approval-blind caller fail-closed.
    """
    errors = []
    if not isinstance(receipt, dict):
        return ["receipt must be an object"]
    for field, allowed in RELEASE_RECEIPT_STATES.items():
        value = receipt.get(field)
        if value not in allowed:
            errors.append(f"{field} must be one of: {', '.join(sorted(allowed))}")
    production = receipt.get("production_status")
    rollback = receipt.get("rollback_status")
    external = receipt.get("external_send_state")
    approval = str(receipt.get("human_approval") or "").strip()
    if receipt.get("preview_status") == "ready" and not str(receipt.get("verification_artifact") or "").strip():
        errors.append("preview-ready requires verification_artifact")
    if production == "deployed":
        # Free text is an attestation, not an approval receipt. Production credit requires a
        # single-use ticket bound to this receipt's exact digest, consumed through the approval
        # authority (approval-issue). Approval-blind callers stay fail-closed.
        if production_approval is not True:
            errors.append(
                "production deployment requires a verifiable single-use external approval "
                "receipt; have Alex issue one with `approval-issue --kind "
                "release-production-approval` bound to this exact receipt"
            )
        if rollback not in {"ready", "rehearsed", "executed"}:
            errors.append(
                "production deployment requires ready, rehearsed, or executed rollback_status"
            )
        if receipt.get("canary_status") not in {"active", "passed"}:
            errors.append("production deployment requires an active or passed canary_status")
        for field in release_receipt_artifact_fields(receipt):
            if not str(receipt.get(field) or "").strip():
                errors.append(f"production deployment requires {field}")
    if artifact_base:
        base = Path(artifact_base).resolve()
        for field in release_receipt_artifact_fields(receipt):
            raw = str(receipt.get(field) or "").strip()
            if not raw:
                continue
            raw_path = Path(raw)
            if (raw_path.is_absolute() or len(raw_path.parts) != 1
                    or raw_path.name in {"", ".", ".."}):
                errors.append(f"{field} must be a companion-directory filename without traversal")
                continue
            artifact = base / raw_path.name
            if artifact.is_symlink():
                errors.append(f"{field} must not be a symlink")
                continue
            try:
                if not artifact.is_file() or artifact.resolve().parent != base:
                    errors.append(f"{field} must point to an existing companion-directory file")
            except OSError:
                errors.append(f"{field} must point to an existing companion-directory file")
    if external == "sent":
        # The same approval boundary applies even when no deployment occurred. Free text cannot
        # prove an external send was authorized or performed, and release receipts cannot
        # authorize sends at all — sends have their own approval channel (approve-send.py).
        errors.append(
            "external send requires a verifiable single-use external approval receipt; "
            "release receipts cannot authorize sends"
        )
        if not approval:
            errors.append("external send requires human_approval attestation")
    if external == "user-triggered-auth-only":
        # This state records a completed user-triggered transactional auth message. It grants
        # no send authority. The release verifier must bind its separate approval/evidence file.
        if receipt.get("external_send_count") != 1:
            errors.append("user-triggered auth state requires exactly one external send")
        if receipt.get("external_send_action") != "request-one-supabase-magic-link":
            errors.append("user-triggered auth state requires the exact auth action")
        if not str(receipt.get(RELEASE_AUTH_SEND_ARTIFACT_FIELD) or "").strip():
            errors.append("user-triggered auth state requires external_send_artifact")
        if not approval:
            errors.append("user-triggered auth state requires human_approval attestation")
    if external == "send-ready" and receipt.get("claimed_external_send") is True:
        errors.append("send-ready cannot be claimed as sent")
    return errors


def release_receipt_supports_send(receipt):
    """A narrow predicate for callers that need proof of an actual external send."""
    return not validate_release_receipt(receipt) and receipt.get("external_send_state") == "sent"


def release_receipt_credit_scope(receipt, envelope=None, production_approval=False):
    """Return the release scope a structured receipt can honestly prove.

    Only `production` credits the release pathway. Preview readiness is useful planning evidence,
    but it cannot close a production release obligation. A syntactically valid all-not-run receipt
    is still a hold, not release proof. Explicit BLOCKED / NO_RELEASE envelope claims always win
    over caller-supplied `--result pass`.
    """
    if validate_release_receipt(receipt, production_approval=production_approval):
        return ""
    envelope = envelope if isinstance(envelope, dict) else {}
    decision = envelope.get("release_decision")
    decision = decision if isinstance(decision, dict) else {}
    blockers = {
        str(envelope.get("status") or "").strip().upper(),
        str(envelope.get("claim_scope") or "").strip().upper(),
        str(decision.get("decision") or "").strip().upper(),
        str(decision.get("release_gate") or "").strip().upper(),
        str(decision.get("pathway_result") or "").strip().upper(),
    }
    if any("BLOCKED" in value or "NO_RELEASE" in value for value in blockers if value):
        return ""
    if receipt.get("production_status") == "deployed":
        if decision and (
            decision.get("deployed") is not True
            or decision.get("production_mutation_performed") is not True
            or str(decision.get("current_authorized_stage") or "").upper() in {"", "NONE", "BLOCKED"}
        ):
            return ""
        return "production"
    return ""


def _release_envelope_errors(envelope, expected=None, now=None):
    """Bind a production release claim to one fresh work and project context."""
    now = now or utc_now()
    errors = []
    for field in RELEASE_CONTEXT_FIELDS:
        value = envelope.get(field)
        wanted = str((expected or {}).get(field) or "").strip() if expected is not None else ""
        if not isinstance(value, str) or not value.strip():
            errors.append(f"production release requires non-empty string {field}")
        if expected is None or not wanted or value != wanted:
            errors.append(f"production release {field} does not match the current proof context")
    issued_value = envelope.get("issued_at")
    issued_at = parse_ts(issued_value) if (
        isinstance(issued_value, str)
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", issued_value)
    ) else None
    expires_value = envelope.get("expires_at")
    expires_at = parse_ts(expires_value) if (
        isinstance(expires_value, str)
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", expires_value)
    ) else None
    if issued_at is None:
        errors.append("production release issued_at must be an ISO-8601 timestamp")
    else:
        age = (now - issued_at).total_seconds()
        if age > RELEASE_MAX_EVIDENCE_AGE_SECONDS:
            errors.append("production release evidence is stale")
        if age < -RELEASE_MAX_FUTURE_SKEW_SECONDS:
            errors.append("production release issued_at is in the future")
    if expires_at is None:
        errors.append("production release expires_at must be an ISO-8601 timestamp")
    elif expires_at < now:
        errors.append("production release evidence is stale")
    if issued_at and expires_at:
        lifetime = (expires_at - issued_at).total_seconds()
        if lifetime <= 0:
            errors.append("production release expires_at must be after issued_at")
        elif lifetime > RELEASE_MAX_EVIDENCE_AGE_SECONDS:
            errors.append("production release validity window is overlong")
    return errors


def release_companion_candidate(evidence_path):
    """The one rule for resolving a release receipt's JSON companion. Shared by the evidence
    loader and the approval peek so the subject can never bind a different file than the
    validator reads."""
    primary = Path(evidence_path).expanduser() if evidence_path else Path()
    return primary if primary.suffix.lower() == ".json" else primary.with_suffix(".json")


def release_receipt_from_evidence(evidence_path, expected=None, now=None, production_approval=False):
    """Load a release receipt from JSON evidence or a same-stem JSON companion.

    Markdown remains the operator/carry-forward artifact. The JSON companion is the typed state
    boundary. Its receipt and digest are copied into the proof record so later credit does not
    depend on reparsing mutable prose. `production_approval` reflects whether the caller located
    a live single-use approval ticket for this exact companion digest (default fail-closed).
    """
    for candidate in [release_companion_candidate(evidence_path)]:
        if candidate.is_symlink():
            return {
                "receipt": {}, "receipt_path": str(candidate), "receipt_sha256": "",
                "credit_scope": "", "errors": ["release companion must not be a symlink"],
                "artifact_sha256": {},
            }
        if not candidate.is_file():
            continue
        envelope, parse_errors = _read_strict_json_object(candidate, "release companion")
        receipt = envelope.get("release_receipt", envelope)
        if not isinstance(receipt, dict):
            continue
        errors = list(parse_errors) + validate_release_receipt(
            receipt, candidate.parent, production_approval=production_approval)
        scope = release_receipt_credit_scope(receipt, envelope, production_approval=production_approval)
        if scope == "production":
            errors.extend(_release_envelope_errors(envelope, expected, now))
        if not scope and not errors:
            errors = ["release receipt records a hold, not preview or production readiness"]
        artifact_sha256 = {}
        if not errors and scope == "production":
            for field in release_receipt_artifact_fields(receipt):
                artifact = candidate.parent / str(receipt[field])
                artifact_sha256[field] = sha256_file(artifact)
        return {
            "receipt": receipt,
            "receipt_path": str(candidate.resolve()),
            "receipt_sha256": sha256_file(candidate),
            "credit_scope": scope,
            "errors": errors,
            "artifact_sha256": artifact_sha256,
        }
    return {
        "receipt": {},
        "receipt_path": "",
        "receipt_sha256": "",
        "credit_scope": "",
        "errors": ["release proof requires JSON evidence or a same-stem JSON release receipt"],
        "artifact_sha256": {},
    }


def release_verifier_binding(stdout, receipt_sha256, typed_receipt):
    """Bind a production release verifier's explicit outcome to the typed receipt digest."""
    allowed_markers = {
        "RELEASE_DECISION", "RELEASE_GATE", "PATHWAY_RESULT", "PRODUCTION_STATUS",
        "CANARY_STATUS", "ROLLBACK_STATUS", "EXTERNAL_SEND_STATUS",
        "EXTERNAL_SEND_COUNT", "RELEASE_RECEIPT_SHA256",
    }
    markers, duplicate_keys = _strict_verifier_markers(stdout, allowed_markers)
    required = {
        "RELEASE_DECISION": {"RELEASE", "APPROVED"},
        "RELEASE_GATE": {"PASS"},
        "PATHWAY_RESULT": {"PASS", "PASSED"},
        "PRODUCTION_STATUS": {"DEPLOYED"},
        "CANARY_STATUS": {"ACTIVE", "PASSED"},
    }
    errors = [
        f"release verifier must emit {key}={('|'.join(sorted(values)))}"
        for key, values in required.items()
        if markers.get(key, "").upper() not in values
    ]
    errors.extend(f"release verifier emitted duplicate marker {key}" for key in sorted(duplicate_keys))
    rollback_status = (
        str(typed_receipt.get("rollback_status") or "").strip().lower()
        if isinstance(typed_receipt, dict)
        else ""
    )
    expected_rollback_marker = {
        "ready": "TARGET_READY",
        "rehearsed": "REHEARSED",
        "executed": "EXECUTED",
    }.get(rollback_status)
    if not expected_rollback_marker:
        errors.append(
            "release verifier requires a typed ready, rehearsed, or executed rollback receipt"
        )
    elif markers.get("ROLLBACK_STATUS", "").upper() != expected_rollback_marker:
        errors.append(
            "release verifier ROLLBACK_STATUS must match the typed rollback receipt"
        )
    external_send_state = (
        str(typed_receipt.get("external_send_state") or "").strip().lower()
        if isinstance(typed_receipt, dict)
        else ""
    )
    expected_external_marker = {
        "not-sent": ("NOT_SENT", "0"),
        "user-triggered-auth-only": ("USER_TRIGGERED_AUTH_ONLY", "1"),
    }.get(external_send_state)
    if not expected_external_marker:
        errors.append(
            "release verifier requires a typed no-send or user-triggered auth-only receipt"
        )
    else:
        expected_status, expected_count = expected_external_marker
        if markers.get("EXTERNAL_SEND_STATUS", "").upper() != expected_status:
            errors.append(
                "release verifier EXTERNAL_SEND_STATUS must match the typed receipt"
            )
        if markers.get("EXTERNAL_SEND_COUNT", "") != expected_count:
            errors.append(
                "release verifier EXTERNAL_SEND_COUNT must match the typed receipt"
            )
        if (
            external_send_state == "user-triggered-auth-only"
            and typed_receipt.get("external_send_count") != 1
        ):
            errors.append(
                "release verifier auth-only receipt must record exactly one external send"
            )
    if not receipt_sha256 or markers.get("RELEASE_RECEIPT_SHA256", "").lower() != receipt_sha256.lower():
        errors.append("release verifier must emit the exact RELEASE_RECEIPT_SHA256")
    return {"markers": markers, "errors": errors, "bound": not errors}


def release_provider_action_from_evidence(evidence_path):
    """Load one frozen provider-action authorization without treating it as final release state."""
    candidate = Path(evidence_path).expanduser() if evidence_path else Path()
    errors = []
    if candidate.suffix.lower() != ".json":
        errors.append("release provider action requires a JSON authorization artifact")
    if candidate.is_symlink():
        errors.append("release provider action authorization must not be a symlink")
    if not candidate.is_file():
        errors.append("release provider action authorization must be an existing file")
    authorization = {}
    if not errors:
        authorization, parse_errors = _read_strict_json_object(
            candidate, "release provider action authorization")
        errors.extend(parse_errors)
    action = authorization.get("action") if isinstance(authorization, dict) else None
    if action not in RELEASE_PROVIDER_ACTIONS:
        errors.append("release provider action authorization has an unknown action")
    authorized_verifier_sha256 = (
        authorization.get("verifier_source_sha256")
        if isinstance(authorization, dict) else None
    )
    if (not isinstance(authorized_verifier_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", authorized_verifier_sha256)):
        errors.append(
            "release provider action authorization requires one lowercase SHA-256 "
            "verifier_source_sha256"
        )
    receipt_path = ""
    receipt_sha256 = ""
    if candidate.is_file() and not candidate.is_symlink():
        try:
            receipt_path = str(candidate.resolve())
            receipt_sha256 = sha256_file(candidate)
        except OSError:
            errors.append("release provider action authorization could not be resolved")
    return {
        "receipt": authorization,
        "receipt_path": receipt_path,
        "receipt_sha256": receipt_sha256,
        "credit_scope": "",
        "errors": errors,
        "artifact_sha256": {},
        "action": action if isinstance(action, str) else "",
    }


def release_provider_action_verifier_binding(stdout, expected_action, receipt_sha256):
    """Bind one intermediate provider action to exact output, action, and authorization bytes.

    This contract deliberately has no final-release markers. A successful provider action may
    consume its ticket, but it cannot claim deployment, canary, rollback, or release credit.
    """
    allowed = {
        "PROVIDER_ACTION", "PROVIDER_ACTION_PROOF", "PATHWAY_RESULT",
        "RELEASE_RECEIPT_SHA256",
    }
    markers = {}
    duplicates = set()
    extra_markers = set()
    unexpected_output = False
    for line in (stdout or "").splitlines():
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=([^\r\n]+)", line)
        if not match:
            unexpected_output = True
            continue
        key, value = match.group(1), match.group(2)
        if key not in allowed:
            extra_markers.add(key)
            continue
        if key in markers:
            duplicates.add(key)
            continue
        markers[key] = value
    errors = []
    if unexpected_output:
        errors.append("provider-action verifier emitted unexpected output")
    errors.extend(
        f"provider-action verifier emitted extra marker {key}"
        for key in sorted(extra_markers)
    )
    errors.extend(
        f"provider-action verifier emitted duplicate marker {key}"
        for key in sorted(duplicates)
    )
    if expected_action not in RELEASE_PROVIDER_ACTIONS:
        errors.append("provider-action evidence names an unknown action")
    emitted_action = markers.get("PROVIDER_ACTION", "")
    if emitted_action not in RELEASE_PROVIDER_ACTIONS:
        errors.append("provider-action verifier emitted an unknown action")
    elif emitted_action != expected_action:
        errors.append("provider-action verifier action does not match the authorization")
    if markers.get("PROVIDER_ACTION_PROOF") != "PASS":
        errors.append("provider-action verifier must emit PROVIDER_ACTION_PROOF=PASS")
    if markers.get("PATHWAY_RESULT") != "PASS":
        errors.append("provider-action verifier must emit PATHWAY_RESULT=PASS")
    if not receipt_sha256 or markers.get("RELEASE_RECEIPT_SHA256") != receipt_sha256:
        errors.append("provider-action verifier must emit the exact RELEASE_RECEIPT_SHA256")
    if set(markers) != allowed:
        errors.append("provider-action verifier must emit exactly the four required markers")
    return {"markers": markers, "errors": errors, "bound": not errors}


OBSERVABILITY_ALLOWED_STAGES = {"NONE"}
OBSERVABILITY_ALLOWED_VERDICTS = {"NO_PROMOTE"}
OBSERVABILITY_RECEIPT_ARTIFACT_FIELDS = (
    "metric_artifact", "log_artifact", "trace_artifact", "alert_artifact",
    "runbook_drill_artifact", "canary_artifact", "verifier_artifact",
)
OBSERVABILITY_JSON_ARTIFACT_TYPES = {
    "metric_artifact": "metric_evidence",
    "log_artifact": "structured_log_evidence",
    "trace_artifact": "trace_evidence",
    "alert_artifact": "alert_execution_evidence",
    "runbook_drill_artifact": "runbook_drill_evidence",
    "canary_artifact": "anti_gaming_canary_evidence",
}
OBSERVABILITY_RUNTIME_TRUE_FIELDS = (
    "runtime_present", "telemetry_present", "alerts_wired", "alert_executed",
    "incident_drills_run", "trace_context_validated", "operator_disposition_recorded",
    "recovery_evidence_recorded", "anti_gaming_canary_failed", "credits_pathway",
)
OBSERVABILITY_PRE_RUNTIME_STATE = {
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
}
OBSERVABILITY_CONTEXT_FIELDS = ("work_id", "recommendation_id", "target_project")
OBSERVABILITY_MAX_EVIDENCE_AGE_SECONDS = 86_400
OBSERVABILITY_MAX_FUTURE_SKEW_SECONDS = 300
OBSERVABILITY_MAX_OBSERVATION_WINDOW_SECONDS = 300
OBSERVABILITY_MAX_JSON_BYTES = 5_000_000
OBSERVABILITY_MAX_ABS_METRIC_VALUE = 10 ** 100
def _parse_strict_json_object_bytes(raw, label="observability companion", max_bytes=None):
    """Parse one captured byte snapshot, rejecting duplicates and non-finite numbers."""
    duplicates = []

    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                duplicates.append(str(key))
            else:
                obj[key] = value
        return obj

    def reject_constant(value):
        raise ValueError(f"non-finite number {value}")

    def finite_number(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"non-finite number {value}")
        return number

    limit = OBSERVABILITY_MAX_JSON_BYTES if max_bytes is None else max_bytes
    if len(raw) > limit:
        return {}, [f"{label} exceeds the {limit}-byte limit"]
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return {}, [f"{label} must be valid UTF-8"]
    try:
        data = json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
            parse_float=finite_number,
        )
    except (TypeError, ValueError) as exc:
        return {}, [f"{label} is not strict JSON: {exc}"]
    errors = [f"{label} contains duplicate key {key}" for key in sorted(set(duplicates))]
    if not isinstance(data, dict):
        errors.append(f"{label} must be a JSON object")
        data = {}
    return data, errors


def _read_strict_json_object(path, label="observability companion"):
    """Read a JSON object while rejecting duplicate keys and non-finite numbers."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(OBSERVABILITY_MAX_JSON_BYTES + 1)
    except OSError as exc:
        return {}, [f"{label} could not be read: {exc}"]
    return _parse_strict_json_object_bytes(raw, label)


# ---------------------------------------------------------------------------
# Per-project observability evidence contracts.
#
# The tradebot evidence schema that used to live here as module constants is
# now versioned DATA: contracts/observability/rainman-thorp.json (extracted
# verbatim 2026-08-30). A contract defines WHAT the evidence describes; it can
# never lower HOW MUCH proof is required -- the receipt shape, sha256/canary/
# restoration binding, and snapshot checks stay engine-side above and in
# proof_is_verified. The loader below fails closed: no readable, schema-valid
# contract means every observability receipt is refused outright.

OBSERVABILITY_CONTRACT_MAX_BYTES = 65_536
OBSERVABILITY_CONTRACT_MEMBER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{3,127}\Z")
OBSERVABILITY_RUNBOOK_FACT_KINDS = frozenset({
    "enum", "evidence_list", "identifier", "mode", "sha256", "stage", "timestamp", "true",
})
OBSERVABILITY_RUNBOOK_EVIDENCE_INVENTORY = frozenset(OBSERVABILITY_RECEIPT_ARTIFACT_FIELDS) - {
    "runbook_drill_artifact", "verifier_artifact",
}
OBSERVABILITY_CONTRACT_ENUM_FLOORS = {
    "metric_names": 3,
    "event_names": 3,
    "correlation_fields": 8,
    "correlation_hash_fields": 1,
    "correlation_timestamp_fields": 1,
    "correlation_sequence_fields": 1,
    "runbook_question_ids": 3,
    "runbook_evidence_fields": 3,
    "runbook_dispositions": 1,
    "runbook_missing_evidence": 1,
}
OBSERVABILITY_LEGACY_CORRELATION_ENUM_KEYS = {
    "allowed_assets": "asset",
    "allowed_modes": "mode",
    "allowed_risk_decisions": "risk_decision",
    "allowed_reason_codes": "reason_code",
}


def observability_contracts_dir(contract_root=None):
    """Engine-owned contracts root, realpath-contained inside this repo.

    Resolves through symlinks (including a symlinked contracts/ directory)
    and refuses any resolution that escapes the repo root, per threat T4.
    """
    repo_root = Path(__file__).resolve().parent.parent
    configured = (
        Path(contract_root).expanduser().absolute()
        if contract_root is not None
        else repo_root / "contracts" / "observability"
    )
    contracts_dir = configured.resolve()
    if contracts_dir != configured:
        return None
    return contracts_dir


def _observability_contract_enum_errors(contract, key, floor):
    if key not in contract:
        return [f"observability contract is missing required key {key}"]
    value = contract.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return [f"observability contract {key} must be a list of strings"]
    errors = []
    if len(value) != len(set(value)):
        errors.append(f"observability contract {key} must not contain duplicates")
    if len(value) < floor:
        errors.append(
            f"observability contract {key} needs at least {floor} member(s)"
        )
    for member in value:
        if not OBSERVABILITY_CONTRACT_MEMBER_RE.fullmatch(member):
            errors.append(
                f"observability contract {key} member {member!r} fails the quality gate"
            )
            break
    return errors


def _observability_string_list(value):
    """Return a validated string list or an inert empty list, never a crashable scalar."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return value


def _observability_finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def validate_observability_contract(contract):
    """Schema gate for one contract object. Returns a list of errors."""
    if not isinstance(contract, dict):
        return ["observability contract must be an object"]
    errors = []
    if type(contract.get("schema_version")) is not int or contract.get("schema_version") != 1:
        errors.append("observability contract schema_version must be integer 1")
    if contract.get("contract_type") != "observability_evidence_contract":
        errors.append("observability contract_type must be observability_evidence_contract")
    if not isinstance(contract.get("project_key"), str) or not contract.get("project_key").strip():
        errors.append("observability contract requires a non-empty project_key")
    for key, floor in OBSERVABILITY_CONTRACT_ENUM_FLOORS.items():
        errors.extend(_observability_contract_enum_errors(contract, key, floor))

    metric_names = set(_observability_string_list(contract.get("metric_names")))
    labels = contract.get("metric_label_values")
    if not isinstance(labels, dict) or set(labels) != metric_names or not all(
        isinstance(entry, dict)
        and all(
            isinstance(values, list) and values
            and all(isinstance(v, str) and v.strip() for v in values)
            and len(values) == len(set(values))
            for values in entry.values()
        )
        for entry in labels.values()
    ):
        errors.append("observability contract metric_label_values must cover exactly metric_names")
    domains = contract.get("metric_domains")
    domains_valid = isinstance(domains, dict) and set(domains) == metric_names
    if domains_valid:
        for bounds in domains.values():
            if not isinstance(bounds, list) or len(bounds) != 2:
                domains_valid = False
                break
            minimum, maximum = bounds
            if (not _observability_finite_number(minimum)
                    or (maximum is not None and not _observability_finite_number(maximum))
                    or (maximum is not None and maximum < minimum)):
                domains_valid = False
                break
    if not domains_valid:
        errors.append("observability contract metric_domains must cover exactly metric_names")

    correlation = set(_observability_string_list(contract.get("correlation_fields")))
    for subset_key in (
        "correlation_hash_fields", "correlation_timestamp_fields",
        "correlation_sequence_fields",
    ):
        if not set(_observability_string_list(contract.get(subset_key))).issubset(correlation):
            errors.append(
                f"observability contract {subset_key} must be a subset of correlation_fields"
            )
    correlation_timestamps = set(
        _observability_string_list(contract.get("correlation_timestamp_fields")))
    timestamp_order = contract.get("correlation_timestamp_order")
    if (timestamp_order is not None
            and (not isinstance(timestamp_order, list)
                 or not all(isinstance(field, str) for field in timestamp_order)
                 or len(timestamp_order) != len(set(timestamp_order))
                 or set(timestamp_order) != correlation_timestamps)):
        errors.append(
            "observability contract correlation_timestamp_order must order every timestamp field"
        )
    for legacy_key in OBSERVABILITY_LEGACY_CORRELATION_ENUM_KEYS:
        if legacy_key in contract:
            errors.extend(_observability_contract_enum_errors(contract, legacy_key, 1))
    correlation_enum_values = contract.get("correlation_enum_values", {})
    if (not isinstance(correlation_enum_values, dict)
            or not all(
                isinstance(field, str) and field in correlation
                and isinstance(values, list) and values
                and all(isinstance(value, str) and value.strip() for value in values)
                and len(values) == len(set(values))
                for field, values in correlation_enum_values.items()
            )):
        errors.append(
            "observability contract correlation_enum_values must map correlation fields to value lists"
        )
        correlation_enum_values = {}
    else:
        correlation_enum_values = dict(correlation_enum_values)
    for legacy_key, field in OBSERVABILITY_LEGACY_CORRELATION_ENUM_KEYS.items():
        legacy_values = contract.get(legacy_key)
        if legacy_key not in contract or not isinstance(legacy_values, list):
            continue
        if (field in correlation_enum_values
                and set(correlation_enum_values[field]) != set(legacy_values)):
            errors.append(
                f"observability contract {legacy_key} conflicts with correlation_enum_values[{field}]"
            )
        correlation_enum_values.setdefault(field, legacy_values)

    question_ids = set(_observability_string_list(contract.get("runbook_question_ids")))
    answer_codes = contract.get("runbook_answer_codes")
    if not isinstance(answer_codes, dict) or set(answer_codes) != question_ids or not all(
        isinstance(code, str) and code.strip() for code in answer_codes.values()
    ):
        errors.append("observability contract runbook_answer_codes must cover exactly runbook_question_ids")
    enum_values = contract.get("runbook_enum_values")
    enum_values_valid = isinstance(enum_values, dict) and all(
        isinstance(field, str) and isinstance(values, list) and values
        and all(isinstance(v, str) and v.strip() for v in values)
        and len(values) == len(set(values))
        for field, values in enum_values.items()
    )
    if not enum_values_valid:
        errors.append("observability contract runbook_enum_values must map fields to value lists")
    evidence_fields = set(_observability_string_list(contract.get("runbook_evidence_fields")))
    if not evidence_fields.issubset(OBSERVABILITY_RUNBOOK_EVIDENCE_INVENTORY):
        errors.append(
            "observability contract runbook_evidence_fields must come from the receipt artifact inventory"
        )
    answer_contract = contract.get("runbook_answer_contract")
    answer_contract_valid = isinstance(answer_contract, dict) and set(answer_contract) == question_ids
    enum_fact_fields = set()
    if answer_contract_valid:
        for entry in answer_contract.values():
            if not isinstance(entry, dict):
                answer_contract_valid = False
                break
            fields = entry.get("fields")
            evidence = entry.get("evidence")
            if (not isinstance(fields, dict) or not fields
                    or not all(
                        isinstance(field, str) and isinstance(kind, str)
                        and kind in OBSERVABILITY_RUNBOOK_FACT_KINDS
                        for field, kind in fields.items()
                    )
                    or not isinstance(evidence, list) or not evidence
                    or not all(isinstance(ref, str) for ref in evidence)
                    or len(evidence) != len(set(evidence))
                    or not set(evidence).issubset(evidence_fields)
                    or not set(evidence).issubset(OBSERVABILITY_RUNBOOK_EVIDENCE_INVENTORY)):
                answer_contract_valid = False
                break
            enum_fact_fields.update(field for field, kind in fields.items() if kind == "enum")
    if not answer_contract_valid:
        errors.append(
            "observability contract runbook_answer_contract must cover exactly runbook_question_ids"
        )
    if enum_values_valid and enum_fact_fields != set(enum_values):
        errors.append(
            "observability contract enum facts must map exactly to runbook_enum_values"
        )

    drill_incident = contract.get("drill_incident")
    if (not isinstance(drill_incident, dict)
            or len(set(drill_incident) - {"event_name"}) < 3
            or "event_name" not in drill_incident
            or not set(drill_incident).issubset(correlation | {"event_name"})
            or not all(isinstance(value, str) and value.strip()
                       for value in drill_incident.values())
            or drill_incident.get("event_name") not in set(
                _observability_string_list(contract.get("event_names")))
            or any(
                field in correlation_enum_values
                and value not in correlation_enum_values[field]
                for field, value in drill_incident.items()
            )):
        errors.append(
            "observability contract drill_incident must bind at least three contract correlation fields"
        )
    if not isinstance(contract.get("drill_trace_name"), str) or not contract.get("drill_trace_name").strip():
        errors.append("observability contract requires a drill_trace_name")
    drill_alert = contract.get("drill_alert")
    if (not isinstance(drill_alert, dict)
            or set(drill_alert) != {"alert_id", "condition", "status", "safe_action"}
            or drill_alert.get("status") != "FIRED" or not all(
        isinstance(drill_alert.get(field), str) and drill_alert.get(field).strip()
        for field in ("alert_id", "condition", "status", "safe_action")
    )):
        errors.append("observability contract drill_alert must carry alert_id/condition/status/safe_action")

    trusted = contract.get("trusted_verifier_sha256")
    trusted_valid = isinstance(trusted, list) and all(
        isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) for digest in trusted
    )
    if not trusted_valid or len(trusted) != len(set(trusted)):
        errors.append(
            "observability contract trusted_verifier_sha256 must be a unique list of lowercase sha256 digests"
        )
    return errors


def load_observability_contract_snapshot(contract_path):
    """Load, parse, and hash one exact contract byte snapshot, fail closed."""
    contract_path = Path(contract_path)
    if contract_path.is_symlink():
        return {}, ["observability contract must not be a symlink"], ""
    if not contract_path.is_file():
        return {}, ["observability_contract_not_registered"], ""
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(contract_path, flags)
        with os.fdopen(fd, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                return {}, ["observability contract must be a regular file"], ""
            raw = fh.read(OBSERVABILITY_CONTRACT_MAX_BYTES + 1)
    except OSError:
        return {}, ["observability contract is unreadable"], ""
    contract, errors = _parse_strict_json_object_bytes(
        raw, "observability contract", OBSERVABILITY_CONTRACT_MAX_BYTES)
    if errors:
        return {}, errors, ""
    errors = validate_observability_contract(contract)
    if errors:
        return {}, errors, ""
    return contract, [], hashlib.sha256(raw).hexdigest()


def load_observability_contract_file(contract_path):
    """Compatibility wrapper returning the schema-gated contract and errors."""
    contract, errors, _digest = load_observability_contract_snapshot(contract_path)
    return contract, errors


def observability_project_key(project_path, projects_root=None):
    """Return the canonical projects-root-relative identity, including owner family."""
    root = Path(projects_root or DEFAULT_PROJECTS_ROOT).expanduser().resolve()
    resolved = Path(resolve_project_dir(project_path, root)).expanduser()
    try:
        resolved = resolved.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, ValueError):
        return "", ["observability project must resolve inside the canonical projects root"]
    if (not relative.parts or any(
            part in {"", ".", ".."} or part.startswith(("_", "."))
            for part in relative.parts)):
        return "", ["observability project key is not a canonical project path"]
    return relative.as_posix(), []


OBSERVABILITY_PROJECT_CONTRACT_ALIASES = MappingProxyType({
    # The live work item and checkout are /Projects/tradebot; Phase 1 preserved
    # the pre-existing Rainman/Thorp contract filename and project_key verbatim.
    "tradebot": "rainman-thorp",
})


def _observability_contract_state(
        contract, errors=(), path="", key="", digest="", project_key=""):
    """Compile validated contract data into one read-only state passed through validation."""
    contract = contract if isinstance(contract, dict) else {}
    answer_contract = {
        question_id: MappingProxyType({
            "fields": MappingProxyType(dict(entry["fields"])),
            "evidence": tuple(entry["evidence"]),
        })
        for question_id, entry in (contract.get("runbook_answer_contract") or {}).items()
    }
    correlation_enum_values = {
        field: frozenset(members)
        for field, members in (contract.get("correlation_enum_values") or {}).items()
    }
    for legacy_key, field in OBSERVABILITY_LEGACY_CORRELATION_ENUM_KEYS.items():
        if legacy_key in contract:
            correlation_enum_values[field] = frozenset(contract.get(legacy_key) or [])
    timestamp_order = tuple(contract.get("correlation_timestamp_order") or [])
    if not timestamp_order:
        # Compatibility for schema-v1 contracts extracted before the optional
        # order existed. Derive a chain only when every contract-declared field
        # has one unambiguous temporal role; otherwise retain no implicit order.
        role_tokens = {
            "event": 0,
            "occur": 1,
            "occurred": 1,
            "observe": 2,
            "observed": 2,
        }
        ranked = []
        for field in contract.get("correlation_timestamp_fields") or []:
            roles = {
                role_tokens[token]
                for token in re.split(r"[^a-z0-9]+", field.lower())
                if token in role_tokens
            }
            if len(roles) != 1:
                ranked = []
                break
            ranked.append((roles.pop(), field))
        if ranked and len({rank for rank, _field in ranked}) == len(ranked):
            timestamp_order = tuple(field for _rank, field in sorted(ranked))
    values = {
        "errors": tuple(errors),
        "path": str(path or ""),
        "key": str(key or contract.get("project_key") or ""),
        "project_key": str(project_key or key or contract.get("project_key") or ""),
        "sha256": str(digest or ""),
        "schema_version": contract.get("schema_version"),
        "metric_names": frozenset(contract.get("metric_names") or []),
        "metric_label_values": MappingProxyType({
            name: MappingProxyType({label: frozenset(members) for label, members in entry.items()})
            for name, entry in (contract.get("metric_label_values") or {}).items()
        }),
        "metric_domains": MappingProxyType({
            name: tuple(bounds) for name, bounds in (contract.get("metric_domains") or {}).items()
        }),
        "event_names": frozenset(contract.get("event_names") or []),
        "correlation_fields": frozenset(contract.get("correlation_fields") or []),
        "correlation_hash_fields": frozenset(contract.get("correlation_hash_fields") or []),
        "correlation_timestamp_fields": frozenset(
            contract.get("correlation_timestamp_fields") or []),
        "correlation_timestamp_order": timestamp_order,
        "correlation_sequence_fields": frozenset(
            contract.get("correlation_sequence_fields") or []),
        "correlation_enum_values": MappingProxyType(correlation_enum_values),
        "allowed_assets": frozenset(contract.get("allowed_assets") or []),
        "allowed_modes": frozenset(contract.get("allowed_modes") or []),
        "allowed_risk_decisions": frozenset(contract.get("allowed_risk_decisions") or []),
        "allowed_reason_codes": frozenset(contract.get("allowed_reason_codes") or []),
        "drill_incident": MappingProxyType(dict(contract.get("drill_incident") or {})),
        "drill_trace_name": str(contract.get("drill_trace_name") or ""),
        "drill_alert": MappingProxyType(dict(contract.get("drill_alert") or {})),
        "runbook_question_ids": frozenset(contract.get("runbook_question_ids") or []),
        "runbook_evidence_fields": frozenset(contract.get("runbook_evidence_fields") or []),
        "runbook_dispositions": frozenset(contract.get("runbook_dispositions") or []),
        "runbook_answer_codes": MappingProxyType(dict(contract.get("runbook_answer_codes") or {})),
        "runbook_enum_values": MappingProxyType({
            field: frozenset(members)
            for field, members in (contract.get("runbook_enum_values") or {}).items()
        }),
        "runbook_missing_evidence": frozenset(contract.get("runbook_missing_evidence") or []),
        "runbook_answer_contract": MappingProxyType(answer_contract),
        "trusted_verifier_sha256": frozenset(contract.get("trusted_verifier_sha256") or []),
    }
    return MappingProxyType(values)


def resolve_observability_contract(project_path, projects_root=None, contract_root=None):
    """Resolve exactly one project-owned contract without consulting receipt-controlled data."""
    project_key, key_errors = observability_project_key(project_path, projects_root)
    reserved_alias_targets = set(OBSERVABILITY_PROJECT_CONTRACT_ALIASES.values())
    if (not key_errors and project_key in reserved_alias_targets
            and project_key not in OBSERVABILITY_PROJECT_CONTRACT_ALIASES):
        key_errors = [
            "observability contract key is reserved for an explicit compatibility alias"
        ]
    key = OBSERVABILITY_PROJECT_CONTRACT_ALIASES.get(project_key, project_key)
    root = observability_contracts_dir(contract_root)
    if key_errors or root is None:
        errors = key_errors or ["observability contracts directory escapes the repo root"]
        return _observability_contract_state(
            {}, errors=errors, key=key, project_key=project_key)
    parts = key.split("/")
    candidate = root.joinpath(*parts[:-1], f"{parts[-1]}.json")
    try:
        resolved_parent = candidate.parent.resolve()
        resolved_parent.relative_to(root)
    except (OSError, ValueError):
        return _observability_contract_state(
            {}, errors=["observability contract path escapes the contracts root"],
            key=key, project_key=project_key)
    if resolved_parent != candidate.parent:
        return _observability_contract_state(
            {}, errors=["observability contract path must not contain symlink directories"],
            key=key, project_key=project_key)
    contract, errors, digest = load_observability_contract_snapshot(candidate)
    if not errors and contract.get("project_key") != key:
        errors = ["observability contract project_key does not match the canonical project path"]
        contract = {}
    return _observability_contract_state(
        contract, errors=errors, path=str(candidate), key=key, digest=digest,
        project_key=project_key)


_OBSERVABILITY_DEFAULT_CONTRACT, OBSERVABILITY_DEFAULT_CONTRACT_ERRORS, _OBSERVABILITY_DEFAULT_SHA256 = (
    load_observability_contract_snapshot(observability_contracts_dir() / "rainman-thorp.json")
    if observability_contracts_dir() is not None
    else ({}, ["observability contracts directory escapes the repo root"], "")
)

if OBSERVABILITY_DEFAULT_CONTRACT_ERRORS:
    OBSERVABILITY_METRIC_NAMES = frozenset()
    OBSERVABILITY_METRIC_LABEL_VALUES = {}
    OBSERVABILITY_METRIC_DOMAINS = {}
    OBSERVABILITY_EVENT_NAMES = frozenset()
    OBSERVABILITY_CORRELATION_FIELDS = frozenset()
    OBSERVABILITY_CORRELATION_HASH_FIELDS = frozenset()
    OBSERVABILITY_CORRELATION_TIMESTAMP_FIELDS = frozenset()
    OBSERVABILITY_CORRELATION_SEQUENCE_FIELDS = frozenset()
    OBSERVABILITY_ALLOWED_ASSETS = frozenset()
    OBSERVABILITY_ALLOWED_MODES = frozenset()
    OBSERVABILITY_ALLOWED_RISK_DECISIONS = frozenset()
    OBSERVABILITY_ALLOWED_REASON_CODES = frozenset()
    OBSERVABILITY_DRILL_INCIDENT = {}
    OBSERVABILITY_DRILL_TRACE_NAME = ""
    OBSERVABILITY_DRILL_ALERT = {}
    OBSERVABILITY_RUNBOOK_QUESTION_IDS = frozenset()
    OBSERVABILITY_RUNBOOK_EVIDENCE_FIELDS = frozenset()
    OBSERVABILITY_RUNBOOK_DISPOSITIONS = frozenset()
    OBSERVABILITY_RUNBOOK_ANSWER_CODES = {}
    OBSERVABILITY_RUNBOOK_ENUM_VALUES = {}
    OBSERVABILITY_RUNBOOK_MISSING_EVIDENCE = frozenset()
    OBSERVABILITY_RUNBOOK_ANSWER_CONTRACT = {}
    OBSERVABILITY_TRUSTED_VERIFIER_SHA256 = frozenset()
else:
    OBSERVABILITY_METRIC_NAMES = frozenset(_OBSERVABILITY_DEFAULT_CONTRACT["metric_names"])
    OBSERVABILITY_METRIC_LABEL_VALUES = {
        name: {label: frozenset(values) for label, values in entry.items()}
        for name, entry in _OBSERVABILITY_DEFAULT_CONTRACT["metric_label_values"].items()
    }
    OBSERVABILITY_METRIC_DOMAINS = {
        name: (bounds[0], bounds[1])
        for name, bounds in _OBSERVABILITY_DEFAULT_CONTRACT["metric_domains"].items()
    }
    OBSERVABILITY_EVENT_NAMES = frozenset(_OBSERVABILITY_DEFAULT_CONTRACT["event_names"])
    OBSERVABILITY_CORRELATION_FIELDS = frozenset(
        _OBSERVABILITY_DEFAULT_CONTRACT["correlation_fields"]
    )
    OBSERVABILITY_CORRELATION_HASH_FIELDS = frozenset(
        _OBSERVABILITY_DEFAULT_CONTRACT["correlation_hash_fields"]
    )
    OBSERVABILITY_CORRELATION_TIMESTAMP_FIELDS = frozenset(
        _OBSERVABILITY_DEFAULT_CONTRACT["correlation_timestamp_fields"]
    )
    OBSERVABILITY_CORRELATION_SEQUENCE_FIELDS = frozenset(
        _OBSERVABILITY_DEFAULT_CONTRACT["correlation_sequence_fields"]
    )
    OBSERVABILITY_ALLOWED_ASSETS = frozenset(_OBSERVABILITY_DEFAULT_CONTRACT["allowed_assets"])
    OBSERVABILITY_ALLOWED_MODES = frozenset(_OBSERVABILITY_DEFAULT_CONTRACT["allowed_modes"])
    OBSERVABILITY_ALLOWED_RISK_DECISIONS = frozenset(
        _OBSERVABILITY_DEFAULT_CONTRACT["allowed_risk_decisions"]
    )
    OBSERVABILITY_ALLOWED_REASON_CODES = frozenset(
        _OBSERVABILITY_DEFAULT_CONTRACT["allowed_reason_codes"]
    )
    OBSERVABILITY_DRILL_INCIDENT = dict(_OBSERVABILITY_DEFAULT_CONTRACT["drill_incident"])
    OBSERVABILITY_DRILL_TRACE_NAME = _OBSERVABILITY_DEFAULT_CONTRACT["drill_trace_name"]
    OBSERVABILITY_DRILL_ALERT = dict(_OBSERVABILITY_DEFAULT_CONTRACT["drill_alert"])
    OBSERVABILITY_RUNBOOK_QUESTION_IDS = frozenset(
        _OBSERVABILITY_DEFAULT_CONTRACT["runbook_question_ids"]
    )
    OBSERVABILITY_RUNBOOK_EVIDENCE_FIELDS = frozenset(
        _OBSERVABILITY_DEFAULT_CONTRACT["runbook_evidence_fields"]
    )
    OBSERVABILITY_RUNBOOK_DISPOSITIONS = frozenset(
        _OBSERVABILITY_DEFAULT_CONTRACT["runbook_dispositions"]
    )
    OBSERVABILITY_RUNBOOK_ANSWER_CODES = dict(
        _OBSERVABILITY_DEFAULT_CONTRACT["runbook_answer_codes"]
    )
    OBSERVABILITY_RUNBOOK_ENUM_VALUES = {
        field: frozenset(values)
        for field, values in _OBSERVABILITY_DEFAULT_CONTRACT["runbook_enum_values"].items()
    }
    OBSERVABILITY_RUNBOOK_MISSING_EVIDENCE = frozenset(
        _OBSERVABILITY_DEFAULT_CONTRACT["runbook_missing_evidence"]
    )
    OBSERVABILITY_RUNBOOK_ANSWER_CONTRACT = {
        question_id: {
            "fields": dict(entry["fields"]),
            "evidence": tuple(entry["evidence"]),
        }
        for question_id, entry in _OBSERVABILITY_DEFAULT_CONTRACT["runbook_answer_contract"].items()
    }
    OBSERVABILITY_TRUSTED_VERIFIER_SHA256 = frozenset(
        _OBSERVABILITY_DEFAULT_CONTRACT["trusted_verifier_sha256"]
    )
OBSERVABILITY_RUNTIME_VERIFIER_TRUST_STATE = (
    "CONFIGURED_AND_VERIFIED"
    if OBSERVABILITY_TRUSTED_VERIFIER_SHA256 and not OBSERVABILITY_DEFAULT_CONTRACT_ERRORS
    else "TRUSTED_VERIFIER_NOT_CONFIGURED"
)
_OBSERVABILITY_DEFAULT_STATE = _observability_contract_state(
    _OBSERVABILITY_DEFAULT_CONTRACT,
    errors=OBSERVABILITY_DEFAULT_CONTRACT_ERRORS,
    path=str((observability_contracts_dir() or Path()) / "rainman-thorp.json"),
    key="rainman-thorp",
    digest=_OBSERVABILITY_DEFAULT_SHA256,
)


def validate_pre_runtime_observability(envelope, expected=None):
    """Validate the exact Tier-A no-runtime state; verifier success still earns no credit."""
    if not isinstance(envelope, dict):
        return ["pre-runtime observability companion must be an object"]
    errors = []
    for field, expected_value in OBSERVABILITY_PRE_RUNTIME_STATE.items():
        actual = envelope.get(field)
        if isinstance(expected_value, bool):
            valid = actual is expected_value
        else:
            valid = actual == expected_value
        if not valid:
            errors.append(f"pre-runtime observability requires {field}={expected_value}")
    if "observability_receipt" in envelope:
        errors.append("pre-runtime observability cannot contain a runtime observability_receipt")
    for field in OBSERVABILITY_CONTEXT_FIELDS:
        value = envelope.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"pre-runtime observability requires non-empty string {field}")
        wanted = str((expected or {}).get(field) or "").strip() if expected is not None else ""
        if expected is not None and (not wanted or value != wanted):
            errors.append(f"pre-runtime observability {field} does not match the current proof context")
    return errors


def _observability_timestamp(value, field, now=None):
    now = now or utc_now()
    canonical = isinstance(value, str) and bool(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value)
    )
    parsed = parse_ts(value) if canonical else None
    errors = []
    if parsed is None:
        return None, [f"observability {field} must be an ISO-8601 timestamp"]
    age = (now - parsed).total_seconds()
    if age > OBSERVABILITY_MAX_EVIDENCE_AGE_SECONDS:
        errors.append(f"observability {field} is stale")
    if age < -OBSERVABILITY_MAX_FUTURE_SKEW_SECONDS:
        errors.append(f"observability {field} is in the future")
    return parsed, errors


def _resolve_observability_artifacts(receipt, artifact_base):
    """Resolve only distinct regular files located directly beside the companion."""
    paths, digests, errors = {}, {}, []
    if not artifact_base:
        return paths, digests, errors
    base = Path(artifact_base).resolve()
    for field in OBSERVABILITY_RECEIPT_ARTIFACT_FIELDS:
        raw = receipt.get(field)
        if not isinstance(raw, str) or not raw.strip():
            continue
        raw_path = Path(raw)
        if raw_path.is_absolute() or len(raw_path.parts) != 1 or raw_path.name in {"", ".", ".."}:
            errors.append(f"{field} must be a companion-directory filename without traversal")
            continue
        artifact = base / raw_path.name
        if artifact.is_symlink():
            errors.append(f"{field} must not be a symlink")
            continue
        try:
            if not artifact.is_file() or artifact.resolve().parent != base:
                errors.append(f"{field} must be an existing file in the companion directory")
                continue
        except OSError:
            errors.append(f"{field} must be an existing file in the companion directory")
            continue
        paths[field] = str(artifact.resolve())
        digests[field] = sha256_file(artifact)
    if len(set(paths.values())) != len(paths):
        errors.append("observability artifacts must be distinct files")
    return paths, digests, errors


def _nonempty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _finite_observability_metric_value(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return abs(value) <= OBSERVABILITY_MAX_ABS_METRIC_VALUE


def _valid_observability_metric_sample(item, contract_state=None):
    state = contract_state or _OBSERVABILITY_DEFAULT_STATE
    if not isinstance(item, dict) or item.get("name") not in state["metric_names"]:
        return False
    value = item.get("value")
    labels = item.get("labels")
    allowed_labels = state["metric_label_values"][item["name"]]
    if (not _finite_observability_metric_value(value) or not isinstance(labels, dict)
            or set(labels) != set(allowed_labels)
            or any(not isinstance(labels[key], str) or labels[key] not in allowed_labels[key]
                   for key in allowed_labels)):
        return False
    minimum, maximum = state["metric_domains"][item["name"]]
    return value >= minimum and (maximum is None or value <= maximum)


def _valid_observability_correlation_record(record, contract_state=None):
    """Require typed, usable correlation values instead of merely present JSON keys."""
    state = contract_state or _OBSERVABILITY_DEFAULT_STATE
    if (not isinstance(record, dict)
            or record.get("event_name") not in state["event_names"]):
        return False
    for key in state["correlation_fields"]:
        value = record.get(key)
        if key in state["correlation_sequence_fields"]:
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return False
        elif key in state["correlation_hash_fields"]:
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                return False
        elif key in state["correlation_timestamp_fields"]:
            if (not isinstance(value, str)
                    or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value)
                    or parse_ts(value) is None):
                return False
        elif key == "trace_id":
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
                return False
        elif (key in state["correlation_enum_values"]
              and value not in state["correlation_enum_values"][key]):
            return False
        elif not _nonempty_string(value):
            return False
    return True


def _valid_observability_drill_answer(answer, contract_state=None):
    state = contract_state or _OBSERVABILITY_DEFAULT_STATE
    if not isinstance(answer, dict):
        return False
    question_id = answer.get("question_id")
    evidence_refs = answer.get("evidence_refs")
    contract = state["runbook_answer_contract"].get(question_id)
    facts = answer.get("facts")
    if (not contract or answer.get("answer") != state["runbook_answer_codes"].get(question_id)
            or not isinstance(facts, dict) or set(facts) != set(contract["fields"])):
        return False
    for field, kind in contract["fields"].items():
        value = facts.get(field)
        if kind == "stage" and value not in OBSERVABILITY_ALLOWED_STAGES:
            return False
        if kind == "mode" and value not in state["allowed_modes"]:
            return False
        if (kind == "identifier"
                and (not isinstance(value, str)
                     or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,127}", value))):
            return False
        if kind == "enum" and value not in state["runbook_enum_values"][field]:
            return False
        if kind == "sha256" and not _is_sha256_digest(value):
            return False
        if (kind == "timestamp"
                and (not isinstance(value, str)
                     or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value)
                     or parse_ts(value) is None)):
            return False
        if kind == "true" and value is not True:
            return False
        if (kind == "evidence_list"
                and (not isinstance(value, list) or len(value) != len(set(value))
                     or not value or not set(value).issubset(state["runbook_missing_evidence"]))):
            return False
    return (
        isinstance(evidence_refs, list)
        and len(evidence_refs) == len(set(evidence_refs))
        and set(evidence_refs) == set(contract["evidence"])
        and all(ref in state["runbook_evidence_fields"] for ref in evidence_refs)
    )


def _validate_observability_drill_correlations(
        runbook, log_artifact, trace_artifact, alert_artifact, receipt, contract_state=None):
    """Bind contract-declared drill facts to one correlated incident record."""
    state = contract_state or _OBSERVABILITY_DEFAULT_STATE
    answers = {
        item.get("question_id"): item
        for item in (runbook.get("answered_questions") or [])
        if isinstance(item, dict)
    } if isinstance(runbook, dict) else {}
    records = log_artifact.get("records") if isinstance(log_artifact, dict) else None
    if (set(answers) != state["runbook_question_ids"]
            or not all(_valid_observability_drill_answer(answer, state) for answer in answers.values())
            or not isinstance(records, list)):
        return ["runbook drill cannot be correlated to the structured incident record"]

    facts, fact_kinds = {}, {}
    conflicting_facts = False
    for question_id, answer in answers.items():
        field_kinds = state["runbook_answer_contract"][question_id]["fields"]
        for field, value in answer["facts"].items():
            if field in facts and facts[field] != value:
                conflicting_facts = True
            facts[field] = value
            fact_kinds[field] = field_kinds[field]
    match_fields = {
        field: value for field, value in facts.items()
        if field in state["correlation_fields"]
    }
    # Schema-v1 contracts may use semantically equivalent runbook and log clock
    # names. Preserve the join without pinning project vocabulary: an alias is
    # accepted only when removing generic clock words leaves one identical,
    # unique semantic stem on each side. Ambiguous or similar names fail closed.
    timestamp_aliases = {}
    timestamp_alias_ambiguous = False
    generic_clock_tokens = {"at", "event", "time", "timestamp", "ts"}

    def timestamp_stem(field):
        return tuple(
            token for token in re.split(r"[^a-z0-9]+", field.lower())
            if token and token not in generic_clock_tokens
        )

    correlation_timestamps_by_stem = {}
    for field in state["correlation_timestamp_fields"]:
        stem = timestamp_stem(field)
        if stem:
            correlation_timestamps_by_stem.setdefault(stem, []).append(field)
    for field, value in facts.items():
        if fact_kinds.get(field) != "timestamp" or field in match_fields:
            continue
        candidates = correlation_timestamps_by_stem.get(timestamp_stem(field), [])
        if len(candidates) == 1:
            target = candidates[0]
            if target in timestamp_aliases and timestamp_aliases[target] != value:
                timestamp_alias_ambiguous = True
            timestamp_aliases[target] = value
        elif len(candidates) > 1:
            timestamp_alias_ambiguous = True
    match_fields.update(timestamp_aliases)
    correlated_records = [
        record
        for record in records
        if (
        isinstance(record, dict)
        and all(record.get(field) == value for field, value in match_fields.items())
        and all(record.get(field) == value for field, value in state["drill_incident"].items())
        )
    ]
    observed_at = parse_ts(runbook.get("observed_at"))
    errors = []
    if (conflicting_facts or timestamp_alias_ambiguous or not match_fields
            or not correlated_records
            or ("authorized_stage" in facts
                and facts["authorized_stage"] != receipt.get("authorized_stage"))):
        errors.append("runbook drill facts must match one correlated structured incident record")
    incident_trace_ids = {record.get("trace_id") for record in correlated_records}
    spans = trace_artifact.get("spans") if isinstance(trace_artifact, dict) else None
    if (not isinstance(spans, list)
            or not any(
                isinstance(span, dict)
                and span.get("name") == state["drill_trace_name"]
                and span.get("trace_id") in incident_trace_ids
                for span in spans
            )):
        errors.append("runbook drill requires the contract trace correlated to the incident record")
    executions = alert_artifact.get("executions") if isinstance(alert_artifact, dict) else None
    if (not isinstance(executions, list)
            or not any(
                isinstance(execution, dict)
                and all(execution.get(field) == value
                        for field, value in state["drill_alert"].items())
                for execution in executions
            )):
        errors.append("runbook drill requires the contract-declared fired alert")
    fact_timestamps = [
        parse_ts(value) for field, value in facts.items()
        if fact_kinds.get(field) == "timestamp"
    ]
    if (not observed_at or not fact_timestamps
            or any(value is None or value > observed_at for value in fact_timestamps)):
        errors.append("runbook drill timestamps must precede its observation")
    enum_facts = {
        value for field, value in facts.items()
        if fact_kinds.get(field) == "enum"
    }
    if runbook.get("operator_disposition") not in enum_facts:
        errors.append("runbook drill human disposition must match the operator disposition")
    return errors


def _validate_observability_json_artifact(
        field, artifact, receipt, now=None, contract_state=None):
    """Validate one typed, nontrivial runtime evidence artifact."""
    state = contract_state or _OBSERVABILITY_DEFAULT_STATE
    if contract_state is None and OBSERVABILITY_DEFAULT_CONTRACT_ERRORS:
        return [
            "observability_contract_not_registered: "
            + "; ".join(OBSERVABILITY_DEFAULT_CONTRACT_ERRORS[:3])
        ]
    if state["errors"]:
        return [
            "observability_contract_not_registered: "
            + "; ".join(state["errors"][:3])
        ]
    errors = []
    data, parse_errors = _read_strict_json_object(artifact, field)
    errors.extend(parse_errors)
    if parse_errors:
        return errors
    if data.get("schema_version") != 1 or isinstance(data.get("schema_version"), bool):
        errors.append(f"{field} schema_version must be integer 1")
    if data.get("artifact_type") != OBSERVABILITY_JSON_ARTIFACT_TYPES[field]:
        errors.append(f"{field} has the wrong artifact_type")
    if data.get("environment_id") != receipt.get("environment_id"):
        errors.append(f"{field} environment_id does not match the receipt")
    if data.get("runtime_digest") != receipt.get("runtime_digest"):
        errors.append(f"{field} runtime_digest does not match the receipt")
    observed_at, timestamp_errors = _observability_timestamp(data.get("observed_at"), f"{field}.observed_at", now)
    errors.extend(timestamp_errors)
    expires_at = parse_ts(receipt.get("expires_at"))
    if observed_at and expires_at and observed_at > expires_at:
        errors.append(f"{field} observed_at falls after receipt expiry")
    issued_at = parse_ts(receipt.get("issued_at"))
    if observed_at and issued_at:
        observation_lag = (issued_at - observed_at).total_seconds()
        if observation_lag < 0 or observation_lag > OBSERVABILITY_MAX_OBSERVATION_WINDOW_SECONDS:
            errors.append(f"{field} observed_at falls outside the receipt observation window")

    if field == "metric_artifact":
        names = data.get("metric_names")
        name_set = set(names) if isinstance(names, list) and all(isinstance(x, str) for x in names) else set()
        samples = data.get("samples")
        sample_names = {
            item.get("name") for item in samples or []
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        } if isinstance(samples, list) else set()
        valid_samples = (
            isinstance(samples, list) and bool(samples)
            and all(_valid_observability_metric_sample(item, state) for item in samples)
        )
        if (not isinstance(names, list) or len(names) != len(name_set)
                or name_set != state["metric_names"] or sample_names != state["metric_names"]
                or not valid_samples):
            errors.append("metric_artifact must contain one typed sample for every canonical metric")
    elif field == "log_artifact":
        fields = data.get("correlation_fields")
        field_set = set(fields) if isinstance(fields, list) and all(isinstance(x, str) for x in fields) else set()
        records = data.get("records")
        valid_records = (
            isinstance(records, list) and bool(records)
            and all(_valid_observability_correlation_record(item, state) for item in records)
        )
        receipt_observed_at = parse_ts(data.get("observed_at"))
        if valid_records and receipt_observed_at:
            for item in records:
                timestamps = {
                    name: parse_ts(item.get(name))
                    for name in state["correlation_timestamp_fields"]
                }
                order = state["correlation_timestamp_order"]
                if (any(value is None or value > receipt_observed_at
                        for value in timestamps.values())
                        or (order and timestamps[order[-1]] != receipt_observed_at)
                        or any(timestamps[earlier] > timestamps[later]
                               for earlier, later in zip(order, order[1:]))):
                    valid_records = False
                    break
        if (not isinstance(fields, list) or len(fields) != len(field_set)
                or field_set != state["correlation_fields"] or not valid_records):
            errors.append("log_artifact must contain correlated structured log records")
    elif field == "trace_artifact":
        spans = data.get("spans")
        valid_spans = isinstance(spans, list) and bool(spans) and all(
            isinstance(item, dict)
            and bool(re.fullmatch(r"[0-9a-f]{32}", str(item.get("trace_id") or "")))
            and bool(re.fullmatch(r"[0-9a-f]{16}", str(item.get("span_id") or "")))
            and _nonempty_string(item.get("name"))
            for item in spans
        )
        if data.get("context_validated") is not True or not valid_spans:
            errors.append("trace_artifact must contain validated trace context and typed spans")
    elif field == "alert_artifact":
        executions = data.get("executions")
        valid_executions = isinstance(executions, list) and bool(executions) and all(
            isinstance(item, dict)
            and _nonempty_string(item.get("alert_id"))
            and _nonempty_string(item.get("condition"))
            and item.get("status") == "FIRED"
            and item.get("safe_action") == state["drill_alert"]["safe_action"]
            for item in executions
        )
        if data.get("alerts_wired") is not True or not valid_executions:
            errors.append("alert_artifact must bind wired and executed fail-closed alerts")
    elif field == "runbook_drill_artifact":
        answers = data.get("answered_questions")
        recovery = data.get("recovery_evidence")
        answer_ids = {
            item.get("question_id") for item in answers or [] if isinstance(item, dict)
        } if isinstance(answers, list) else set()
        valid_answers = (
            isinstance(answers, list)
            and len(answers) == len(state["runbook_question_ids"])
            and answer_ids == state["runbook_question_ids"]
            and all(_valid_observability_drill_answer(item, state) for item in answers)
        )
        valid_recovery = isinstance(recovery, list) and len(recovery) >= 3 and all(
            isinstance(item, dict)
            and item.get("artifact_field") in state["runbook_evidence_fields"]
            and re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256") or ""))
            and item.get("sha256") == (receipt.get("artifact_sha256") or {}).get(
                item.get("artifact_field")
            )
            for item in recovery
        ) and len({item.get("artifact_field") for item in recovery}) >= 3
        if (data.get("runbook_version") != receipt.get("runbook_version")
                or data.get("drill_executed") is not True
                or not valid_answers
                or data.get("prohibited_actions_taken") != []
                or data.get("operator_disposition") not in state["runbook_dispositions"]
                or not valid_recovery):
            errors.append("runbook_drill_artifact must contain the complete safe 3am drill receipt")
    elif field == "canary_artifact":
        if (data.get("canary_failed") is not True
                or data.get("results") != {
                    "disabled_alert": "FAILED_AS_EXPECTED",
                    "missing_signal": "FAILED_AS_EXPECTED",
                }):
            errors.append("canary_artifact must prove missing-signal and disabled-alert failures")
    return errors


def _validate_observability_verifier_source(path):
    errors = []
    verifier = Path(path)
    if verifier.suffix != ".py":
        return ["verifier_artifact must be a Python source file"]
    text = safe_read_text(verifier, max_bytes=1_000_000)
    if len(text.encode("utf-8", "replace")) < 128:
        errors.append("verifier_artifact is too small to be a nontrivial verifier")
        return errors
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return errors + ["verifier_artifact must contain valid Python"]
    nodes = list(ast.walk(tree))
    if not any(isinstance(node, (ast.If, ast.Assert, ast.Raise)) for node in nodes):
        errors.append("verifier_artifact must contain a load-bearing check")
    if not any(isinstance(node, ast.Call) for node in nodes):
        errors.append("verifier_artifact must execute verification logic")
    return errors


def validate_observability_runtime_receipt(
        receipt, artifact_base=None, expected=None, now=None, contract_state=None):
    """Validate the typed Tier-B receipt without trusting caller-supplied pass semantics."""
    if not isinstance(receipt, dict):
        return ["observability_receipt must be an object"]
    state = contract_state or _OBSERVABILITY_DEFAULT_STATE
    if contract_state is None and OBSERVABILITY_DEFAULT_CONTRACT_ERRORS:
        return [
            "observability_contract_not_registered: "
            + "; ".join(OBSERVABILITY_DEFAULT_CONTRACT_ERRORS[:3])
        ]
    if state["errors"]:
        return [
            "observability_contract_not_registered: "
            + "; ".join(state["errors"][:3])
        ]
    now = now or utc_now()
    errors = []
    if receipt.get("schema_version") != 1 or isinstance(receipt.get("schema_version"), bool):
        errors.append("observability receipt schema_version must be integer 1")
    if receipt.get("receipt_type") != "runtime_observability":
        errors.append("observability receipt_type must be runtime_observability")
    if receipt.get("pathway_result") != "PASS":
        errors.append("runtime observability pathway_result must be PASS")
    claim_scope = receipt.get("claim_scope")
    if claim_scope not in {"runtime", "production"}:
        errors.append("observability claim_scope must be runtime or production")
    environment_class = receipt.get("environment_class")
    if environment_class not in {"local", "test", "staging", "production"}:
        errors.append("observability environment_class must be local, test, staging, or production")
    if claim_scope == "production" and environment_class != "production":
        errors.append("production observability claims require a production environment_class")
    if receipt.get("authorized_stage") not in OBSERVABILITY_ALLOWED_STAGES:
        errors.append("runtime observability authorized_stage must remain NONE without a stage grant")
    if receipt.get("current_verdict") not in OBSERVABILITY_ALLOWED_VERDICTS:
        errors.append("runtime observability current_verdict must be NO_PROMOTE")
    for field in (
        "work_id", "recommendation_id", "project", "target_project", "environment_id", "authorized_stage",
        "current_verdict", "runbook_version",
    ):
        if not _nonempty_string(receipt.get(field)):
            errors.append(f"observability receipt requires non-empty string {field}")
    for field in ("runtime_digest", "verifier_source_sha256"):
        if not _is_sha256_digest(receipt.get(field)):
            errors.append(f"observability receipt requires a SHA-256 {field}")
    for field in OBSERVABILITY_RUNTIME_TRUE_FIELDS:
        if receipt.get(field) is not True:
            errors.append(f"runtime observability requires {field}=true")
    metric_names = receipt.get("metric_names")
    metric_name_set = set(metric_names) if (
        isinstance(metric_names, list) and all(isinstance(item, str) for item in metric_names)
    ) else set()
    if (not isinstance(metric_names, list) or len(metric_names) != len(metric_name_set)
            or metric_name_set != state["metric_names"]):
        errors.append("runtime observability requires the exact canonical metric_names")
    correlations = receipt.get("log_correlation_fields")
    correlation_set = set(correlations) if (
        isinstance(correlations, list) and all(isinstance(item, str) for item in correlations)
    ) else set()
    if (not isinstance(correlations, list) or len(correlations) != len(correlation_set)
            or correlation_set != state["correlation_fields"]):
        errors.append("runtime observability requires every canonical log_correlation_field")
    issued_at, issued_errors = _observability_timestamp(receipt.get("issued_at"), "issued_at", now)
    expires_value = receipt.get("expires_at")
    expires_at = parse_ts(expires_value) if (
        isinstance(expires_value, str)
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", expires_value)
    ) else None
    errors.extend(issued_errors)
    if expires_at is None:
        errors.append("observability expires_at must be an ISO-8601 timestamp")
    elif expires_at < now:
        errors.append("observability receipt is stale")
    if issued_at and expires_at:
        lifetime = (expires_at - issued_at).total_seconds()
        if lifetime <= 0:
            errors.append("observability expires_at must be after issued_at")
        elif lifetime > OBSERVABILITY_MAX_EVIDENCE_AGE_SECONDS:
            errors.append("observability receipt validity window is overlong")
    for field in OBSERVABILITY_RECEIPT_ARTIFACT_FIELDS:
        if not _nonempty_string(receipt.get(field)):
            errors.append(f"runtime observability requires {field}")
    declared_hashes = receipt.get("artifact_sha256")
    if (not isinstance(declared_hashes, dict)
            or set(declared_hashes) != set(OBSERVABILITY_RECEIPT_ARTIFACT_FIELDS)
            or not all(
                isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))
                for value in (declared_hashes or {}).values()
            )):
        errors.append("observability receipt requires an exact lowercase artifact_sha256 map")
    if expected is not None:
        for field in ("work_id", "recommendation_id", "project", "target_project"):
            wanted = str((expected or {}).get(field) or "").strip()
            if not wanted:
                errors.append(f"runtime observability proof requires caller binding for {field}")
            elif receipt.get(field) != wanted:
                errors.append(f"observability receipt {field} does not match the current proof context")
    paths, digests, path_errors = _resolve_observability_artifacts(receipt, artifact_base)
    errors.extend(path_errors)
    if artifact_base:
        if isinstance(declared_hashes, dict) and declared_hashes != digests:
            errors.append("observability artifact_sha256 map does not match current artifact bytes")
        for field in OBSERVABILITY_JSON_ARTIFACT_TYPES:
            if field in paths:
                errors.extend(_validate_observability_json_artifact(
                    field, paths[field], receipt, now, state))
        drill_fields = (
            "runbook_drill_artifact", "log_artifact", "trace_artifact", "alert_artifact",
        )
        if all(field in paths for field in drill_fields):
            drill_artifacts, drill_errors = {}, []
            for field in drill_fields:
                drill_artifacts[field], field_errors = _read_strict_json_object(paths[field], field)
                drill_errors.extend(field_errors)
            if not drill_errors:
                errors.extend(_validate_observability_drill_correlations(
                    drill_artifacts["runbook_drill_artifact"],
                    drill_artifacts["log_artifact"],
                    drill_artifacts["trace_artifact"],
                    drill_artifacts["alert_artifact"],
                    receipt,
                    state,
                ))
        verifier_path = paths.get("verifier_artifact")
        if verifier_path:
            errors.extend(_validate_observability_verifier_source(verifier_path))
            if sha256_file(verifier_path) != str(receipt.get("verifier_source_sha256") or ""):
                errors.append("verifier_source_sha256 must match verifier_artifact")
    return errors


def observability_receipt_credit_scope(receipt, envelope=None, validation_errors=()):
    """Classify already-validated state; this pure helper never reloads or revalidates."""
    if validation_errors:
        return ""
    envelope = envelope if isinstance(envelope, dict) else {}
    decision = envelope.get("observability_decision")
    decision = decision if isinstance(decision, dict) else {}
    values = {
        str(envelope.get("status") or "").strip().upper(),
        str(envelope.get("claim_scope") or "").strip().upper(),
        str(envelope.get("pathway_result") or "").strip().upper(),
        str(decision.get("decision") or "").strip().upper(),
        str(decision.get("observability_gate") or "").strip().upper(),
        str(decision.get("pathway_result") or "").strip().upper(),
    }
    negative_terms = ("BLOCKED", "NO_CREDIT", "NO_RUNTIME", "SPEC_ONLY", "NO_TELEMETRY")
    if any(any(term in value for term in negative_terms) for value in values if value):
        return ""
    for field in ("credits_pathway", "runtime_present", "telemetry_present", "alerts_wired",
                  "incident_drills_run"):
        if envelope.get(field) is False or decision.get(field) is False:
            return ""
    return receipt.get("claim_scope", "")


def observability_receipt_from_evidence(
        evidence_path, expected=None, now=None, contract_state=None):
    """Load either the exact Tier-A companion or a typed Tier-B same-stem receipt."""
    now = now or utc_now()
    primary = Path(evidence_path).expanduser() if evidence_path else Path()
    candidates = [primary] if primary.suffix.lower() == ".json" else [primary.with_suffix(".json")]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        if candidate.is_symlink():
            return {
                "receipt": {}, "receipt_path": str(candidate), "receipt_sha256": "",
                "credit_scope": "", "outcome": "",
                "errors": ["observability companion must not be a symlink"],
                "artifact_sha256": {}, "artifact_paths": {}, "receipt_kind": "",
            }
        envelope, parse_errors = _read_strict_json_object(candidate)
        receipt = envelope.get("observability_receipt") if isinstance(envelope, dict) else None
        artifact_sha256, artifact_paths = {}, {}
        if isinstance(receipt, dict):
            errors = list(parse_errors) + validate_observability_runtime_receipt(
                receipt, candidate.parent, expected, now, contract_state
            )
            scope = observability_receipt_credit_scope(receipt, envelope, errors)
            if not scope and not errors:
                errors.append("observability envelope records a hold, not runtime credit")
            artifact_paths, artifact_sha256, _ = _resolve_observability_artifacts(
                receipt, candidate.parent
            )
            outcome = "runtime" if scope and not errors else ""
            receipt_kind = "runtime"
        else:
            receipt = envelope
            errors = list(parse_errors) + validate_pre_runtime_observability(envelope, expected)
            scope = ""
            outcome = "blocked_no_runtime" if not errors else ""
            receipt_kind = "pre_runtime"
        return {
            "receipt": receipt,
            "receipt_path": str(candidate.resolve()),
            "receipt_sha256": sha256_file(candidate),
            "credit_scope": scope if not errors else "",
            "outcome": outcome,
            "errors": errors,
            "artifact_sha256": artifact_sha256,
            "artifact_paths": artifact_paths,
            "receipt_kind": receipt_kind,
        }
    return {
        "receipt": {}, "receipt_path": "", "receipt_sha256": "", "credit_scope": "",
        "outcome": "", "errors": [
            "observability proof requires JSON evidence or a same-stem JSON observability companion"
        ], "artifact_sha256": {}, "artifact_paths": {}, "receipt_kind": "",
    }


def observability_verifier_binding(stdout, receipt_sha256, receipt, outcome):
    """Bind exact negative or positive verifier markers to the typed companion state."""
    allowed = {
        "OBSERVABILITY_DECISION", "OBSERVABILITY_GATE", "PATHWAY_RESULT", "RUNTIME_STATUS",
        "TELEMETRY_STATUS", "ALERT_STATUS", "RUNBOOK_STATUS", "CANARY_STATUS",
        "AUTHORIZED_STAGE", "CURRENT_VERDICT", "PROJECT_TREE_MUTATION",
        "EXTERNAL_SIDE_EFFECTS", "WORK_ID", "RECOMMENDATION_ID", "ENVIRONMENT_ID",
        "TARGET_PROJECT", "OBSERVABILITY_RECEIPT_SHA256",
    }
    markers, duplicates = _strict_verifier_markers(stdout, allowed)
    errors = [
        f"observability verifier emitted duplicate marker {key}" for key in sorted(duplicates)
    ]
    if outcome == "blocked_no_runtime":
        required = {
            "OBSERVABILITY_DECISION": "NO_CREDIT",
            "OBSERVABILITY_GATE": "BLOCKED_NO_RUNTIME",
            "TELEMETRY_STATUS": "ABSENT",
            "ALERT_STATUS": "NOT_WIRED",
            "RUNBOOK_STATUS": "SPECIFIED_NOT_DRILLED",
            "AUTHORIZED_STAGE": "NONE",
            "CURRENT_VERDICT": "NO_PROMOTE",
            "PROJECT_TREE_MUTATION": "NONE",
            "EXTERNAL_SIDE_EFFECTS": "0",
            "WORK_ID": str(receipt.get("work_id") or ""),
            "RECOMMENDATION_ID": str(receipt.get("recommendation_id") or ""),
            "TARGET_PROJECT": str(receipt.get("target_project") or ""),
        }
        for key, value in required.items():
            if markers.get(key) != value:
                errors.append(f"pre-runtime observability verifier must emit {key}={value}")
        if markers.get("PATHWAY_RESULT") not in {None, "BLOCKED"}:
            errors.append("pre-runtime observability PATHWAY_RESULT must be BLOCKED when emitted")
        if markers.get("RUNTIME_STATUS") not in {None, "NO_RUNTIME", "ABSENT"}:
            errors.append("pre-runtime observability RUNTIME_STATUS must be NO_RUNTIME or ABSENT")
        for key in ("CANARY_STATUS", "ENVIRONMENT_ID"):
            if key in markers:
                errors.append(f"pre-runtime observability verifier emitted contradictory runtime marker {key}")
        marker_digest = markers.get("OBSERVABILITY_RECEIPT_SHA256")
        if not receipt_sha256 or str(marker_digest or "").lower() != receipt_sha256.lower():
            errors.append("pre-runtime verifier must emit the exact OBSERVABILITY_RECEIPT_SHA256")
    elif outcome == "runtime":
        required = {
            "OBSERVABILITY_DECISION": "CREDIT",
            "OBSERVABILITY_GATE": "PASS",
            "PATHWAY_RESULT": "PASS",
            "RUNTIME_STATUS": "PRESENT",
            "TELEMETRY_STATUS": "PRESENT",
            "ALERT_STATUS": "WIRED",
            "RUNBOOK_STATUS": "DRILLED",
            "CANARY_STATUS": "FAILED_AS_EXPECTED",
            "AUTHORIZED_STAGE": str(receipt.get("authorized_stage") or ""),
            "CURRENT_VERDICT": str(receipt.get("current_verdict") or ""),
            "WORK_ID": str(receipt.get("work_id") or ""),
            "RECOMMENDATION_ID": str(receipt.get("recommendation_id") or ""),
            "ENVIRONMENT_ID": str(receipt.get("environment_id") or ""),
        }
        for key, value in required.items():
            if markers.get(key) != value:
                errors.append(f"runtime observability verifier must emit exact {key}={value}")
        if (not receipt_sha256 or markers.get("OBSERVABILITY_RECEIPT_SHA256", "").lower()
                != receipt_sha256.lower()):
            errors.append("runtime observability verifier must emit the exact OBSERVABILITY_RECEIPT_SHA256")
    else:
        errors.append("observability verifier cannot bind an invalid companion")
    return {"markers": markers, "errors": errors, "bound": not errors, "mode": outcome}


def parse_observability_verifier_command(command, cwd, verifier_path):
    """Accept only this process's trusted Python followed immediately by the bound verifier."""
    if not command or not verifier_path:
        return {"argv": [], "errors": ["runtime observability requires a verifier command"]}
    if re.search(r"[;&|<>`$()\r\n]", command):
        return {"argv": [], "errors": ["observability verifier command must not use shell composition"]}
    try:
        argv = shlex.split(command)
    except ValueError:
        return {"argv": [], "errors": ["observability verifier command is not valid shell quoting"]}
    if not argv:
        return {"argv": [], "errors": ["runtime observability requires a verifier command"]}
    wanted = os.path.realpath(verifier_path)

    def resolved_file(token):
        candidate = Path(token).expanduser()
        candidate = candidate if candidate.is_absolute() else Path(cwd) / candidate
        return os.path.realpath(candidate) if candidate.is_file() else ""

    interpreter = shutil.which(argv[0]) if not Path(argv[0]).is_absolute() else argv[0]
    try:
        trusted_interpreter = (
            len(argv) >= 2
            and Path(interpreter or "").is_file()
            and os.path.samefile(interpreter, sys.executable)
        )
    except OSError:
        trusted_interpreter = False
    if not trusted_interpreter or resolved_file(argv[1]) != wanted:
        return {
            "argv": [],
            "errors": [
                "receipt-bound verifier_artifact must immediately follow the trusted sys.executable"
            ],
        }
    return {"argv": [sys.executable, wanted, *argv[2:]], "errors": []}


def run_observability_verifier_argv(
        argv, cwd, timeout=120, expected_verifier_sha256="", trusted_sha256=()):
    """Execute only when the verifier bytes still match receipt and contract trust."""
    try:
        if expected_verifier_sha256:
            current_sha256 = sha256_file(argv[1]) if len(argv) >= 2 else ""
            if (current_sha256 != expected_verifier_sha256
                    or current_sha256 not in set(trusted_sha256 or ())):
                return 126, "", 0, ""
        proc = subprocess.run(
            argv, cwd=cwd or None, capture_output=True, text=True, timeout=timeout, shell=False
        )
        stdout_bytes = (proc.stdout or "").encode("utf-8", "replace")
        return proc.returncode, hashlib.sha256(stdout_bytes).hexdigest(), len(stdout_bytes), proc.stdout or ""
    except Exception:
        return 1, "", 0, ""


def _observability_mutant_bytes(original):
    try:
        lines = original.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return b""
    for index, line in enumerate(lines):
        mutated, changed = _flip_one_byte(line)
        if changed:
            lines[index] = mutated
            result = "".join(lines).encode("utf-8")
            return result if result != original else b""
    return b""


def run_observability_artifact_canaries(
        argv, cwd, artifact_paths, before_hashes, timeout=120,
        expected_verifier_sha256="", trusted_sha256=()):
    """Mutate, verify, and restore each bound artifact independently."""
    results, restoration_sha256, errors = {}, {}, []
    fields = list(OBSERVABILITY_RECEIPT_ARTIFACT_FIELDS)
    noise_rounds = secrets.randbelow(len(fields) + 1)
    for _ in range(noise_rounds):
        control_exit, _, _, _ = run_observability_verifier_argv(
            argv, cwd, timeout, expected_verifier_sha256, trusted_sha256)
        if control_exit != 0:
            errors.append("verifier failed during randomized control prelude")
            return {"results": results, "restoration_sha256": restoration_sha256, "errors": errors}
    # The per-proof order is unpredictable to a stateful verifier. A verifier that fails by
    # invocation count rather than artifact content cannot align its failures to mutant runs.
    secrets.SystemRandom().shuffle(fields)
    for field in fields:
        path = Path((artifact_paths or {}).get(field, ""))
        result = None
        original = b""
        try:
            if path.is_symlink() or not path.is_file():
                raise OSError("artifact is unavailable or symlinked")
            control_exit, _, _, _ = run_observability_verifier_argv(
                argv, cwd, timeout, expected_verifier_sha256, trusted_sha256)
            if control_exit != 0:
                raise ValueError("verifier failed on restored control before mutation")
            original = path.read_bytes()
            mutated = _observability_mutant_bytes(original)
            if not mutated:
                raise ValueError("artifact has no safe text mutation")
            _atomic_replace_bytes(path, mutated)
            exit_code, _, _, _ = run_observability_verifier_argv(
                argv, cwd, timeout, expected_verifier_sha256, trusted_sha256)
            result = exit_code != 0
        except (OSError, ValueError) as exc:
            errors.append(f"{field} mutation canary unavailable: {exc}")
        finally:
            if original:
                try:
                    _atomic_replace_bytes(path, original)
                except OSError as exc:
                    errors.append(f"{field} restoration failed: {exc}")
            restoration_sha256[field] = sha256_file(path)
            if restoration_sha256[field] != (before_hashes or {}).get(field):
                errors.append(f"{field} restoration hash mismatch")
                result = None
            elif original:
                control_exit, _, _, _ = run_observability_verifier_argv(
                    argv, cwd, timeout, expected_verifier_sha256, trusted_sha256)
                if control_exit != 0:
                    errors.append(f"{field} verifier failed after restoration")
                    result = None
        results[field] = result
    # A second randomized pass must reproduce every first-pass result. This rejects stateful or
    # invocation-count-driven verifiers that merely happen to fail during a mutant invocation.
    replay_fields = list(fields)
    secrets.SystemRandom().shuffle(replay_fields)
    for field in replay_fields:
        path = Path((artifact_paths or {}).get(field, ""))
        replay_result = None
        original = b""
        try:
            if path.is_symlink() or not path.is_file():
                raise OSError("artifact is unavailable or symlinked")
            for _ in range(secrets.randbelow(3)):
                control_exit, _, _, _ = run_observability_verifier_argv(
                    argv, cwd, timeout, expected_verifier_sha256, trusted_sha256)
                if control_exit != 0:
                    raise ValueError("verifier failed during randomized replay control")
            original = path.read_bytes()
            mutated = _observability_mutant_bytes(original)
            if not mutated:
                raise ValueError("artifact has no safe text mutation")
            _atomic_replace_bytes(path, mutated)
            exit_code, _, _, _ = run_observability_verifier_argv(
                argv, cwd, timeout, expected_verifier_sha256, trusted_sha256)
            replay_result = exit_code != 0
        except (OSError, ValueError) as exc:
            errors.append(f"{field} replay mutation canary unavailable: {exc}")
        finally:
            if original:
                try:
                    _atomic_replace_bytes(path, original)
                except OSError as exc:
                    errors.append(f"{field} replay restoration failed: {exc}")
            replay_hash = sha256_file(path)
            if replay_hash != (before_hashes or {}).get(field):
                errors.append(f"{field} replay restoration hash mismatch")
                replay_result = None
        if replay_result is not results.get(field):
            errors.append(f"{field} mutation canary was not reproducible")
            results[field] = False
    return {
        "results": results,
        "restoration_sha256": restoration_sha256,
        "errors": errors,
    }


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


def _is_sha256_digest(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


DIGEST_KEY_SUFFIXES = ("_sha256", "_digest", "_hash", "_fingerprint")


def _is_digest_field(key, value):
    return (
        isinstance(key, str)
        and key.lower().endswith(DIGEST_KEY_SUFFIXES)
        and _is_sha256_digest(value)
    )


def _is_receipt_artifact_digest_map(key, value):
    """Recognize the closed maps whose values are receipt-bound artifact digests.

    The parent key supplies digest context while child keys come from a fixed receipt schema.
    Keeping each shape closed avoids a general nested-map exemption that could smuggle an
    entropy-shaped secret past redaction.
    """
    allowed_fields = {
        "release_artifact_sha256": (
            *RELEASE_RECEIPT_ARTIFACT_FIELDS,
            RELEASE_AUTH_SEND_ARTIFACT_FIELD,
        ),
        "release_post_release_artifact_sha256": (
            *RELEASE_RECEIPT_ARTIFACT_FIELDS,
            RELEASE_AUTH_SEND_ARTIFACT_FIELD,
        ),
        "artifact_sha256": OBSERVABILITY_RECEIPT_ARTIFACT_FIELDS,
        "observability_artifact_sha256": OBSERVABILITY_RECEIPT_ARTIFACT_FIELDS,
        "observability_post_observability_artifact_sha256": OBSERVABILITY_RECEIPT_ARTIFACT_FIELDS,
        "observability_artifact_restoration_sha256": OBSERVABILITY_RECEIPT_ARTIFACT_FIELDS,
    }.get(key)
    return bool(
        allowed_fields
        and isinstance(value, dict)
        and set(value).issubset(allowed_fields)
        and all(_is_sha256_digest(item) for item in value.values())
    )


def _authority_text_safe(value):
    if not isinstance(value, str):
        return False
    unsafe_bidi = {"LRE", "RLE", "LRO", "RLO", "PDF", "LRI", "RLI", "FSI", "PDI"}
    return not any(
        unicodedata.category(character).startswith("C")
        or unicodedata.category(character) in {"Zl", "Zp"}
        or unicodedata.bidirectional(character) in unsafe_bidi
        for character in value
    )


def _authority_json_strings_safe(value):
    if isinstance(value, dict):
        return all(
            _authority_text_safe(key) and _authority_json_strings_safe(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return all(_authority_json_strings_safe(item) for item in value)
    return not isinstance(value, str) or _authority_text_safe(value)


def _is_safe_authority_command(value):
    """Recognize only the two exact helper commands emitted after approval validation.

    The generic string redactor correctly treats an embedded 64-hex receipt digest as secret-like.
    Redacting that digest makes the reviewed root command unusable, so this narrow parser repeats
    the closed subject/consumer checks before allowing the generated command through unchanged.
    """
    prefix = (
        "/usr/bin/sudo -k; /usr/bin/sudo -- "
        "/usr/local/libexec/pathway-approval "
    )
    if not isinstance(value, str) or len(value.encode("utf-8")) > 16_384:
        return False
    if not value.startswith(prefix) or not _authority_text_safe(value):
        return False
    try:
        argv = shlex.split(value[len(prefix):])
    except ValueError:
        return False
    if not argv:
        return False
    action = argv[0]
    if action == "invalidate":
        if len(argv) != 5 or argv[1] != "--ticket-id" or argv[3] != "--reason":
            return False
        return bool(
            APPROVAL_TICKET_ID_RE.fullmatch(argv[2])
            and argv[4]
            and redact(argv[4]) == argv[4]
        )
    if action != "issue" or len(argv) != 7:
        return False
    if argv[1] != "--subject-json" or argv[3] != "--reason" or argv[5] != "--consumer":
        return False
    duplicate_keys = []

    def unique_subject_object(pairs):
        parsed = {}
        for key, item in pairs:
            if key in parsed:
                duplicate_keys.append(key)
            else:
                parsed[key] = item
        return parsed

    def reject_subject_constant(value):
        raise ValueError(f"non-finite JSON constant {value}")

    try:
        subject = json.loads(
            argv[2],
            object_pairs_hook=unique_subject_object,
            parse_constant=reject_subject_constant,
        )
    except (TypeError, ValueError):
        return False
    if duplicate_keys:
        return False
    canonical_subject = json.dumps(subject, sort_keys=True, separators=(",", ":"))
    if argv[2] != canonical_subject:
        return False
    reason, consumer = argv[4], argv[6]
    if (not isinstance(subject, dict) or not reason or redact(reason) != reason
            or not _authority_text_safe(reason) or not _authority_text_safe(consumer)
            or not _authority_json_strings_safe(subject)):
        return False
    if subject.get("kind") == APPROVAL_KIND_WAIVER:
        return bool(
            set(subject) == {
                "kind", "schema_version", "work_id", "project", "pathway", "reason",
                "work_context_sha256",
            }
            and type(subject.get("schema_version")) is int
            and subject.get("schema_version") == WAIVER_SUBJECT_SCHEMA_VERSION
            and subject.get("work_id")
            and subject.get("project")
            and subject.get("pathway") in PATHWAY_CANON_ORDER
            and subject.get("reason") == reason
            and _is_sha256_digest(subject.get("work_context_sha256"))
            and consumer
            == f"work-cover:{subject.get('work_id')}:{subject.get('pathway')}"
            and redact(subject.get("work_id")) == subject.get("work_id")
            and redact(subject.get("project")) == subject.get("project")
        )
    if subject.get("kind") == APPROVAL_KIND_RELEASE:
        return bool(
            set(subject)
            == {"kind", "work_id", "project", "stage", "release_receipt_sha256"}
            and subject.get("work_id")
            and subject.get("project")
            and subject.get("stage") == "production"
            and _is_sha256_digest(subject.get("release_receipt_sha256"))
            and re.fullmatch(r"P-[0-9a-f]{12}", consumer or "")
            and redact(subject.get("work_id")) == subject.get("work_id")
            and redact(subject.get("project")) == subject.get("project")
        )
    return False


def redact_obj(value):
    if isinstance(value, dict):
        generated_id_keys = {
            "work_id", "run_id", "measurement_id", "control_id", "evidence_id",
            "created_by_run_id", "resolved_by_run_id", "resolution_evidence_id",
            "proved_by_run",
            # Approval-ledger join keys. consumed_by embeds a work_id
            # ("work-cover:<work_id>:<pathway>"), and a project slug of ~21+ chars pushes the
            # composite over the 64-char entropy pattern — the stored consumption became
            # "work-cover:[REDACTED]:..." and the ledger join silently failed (adversarial
            # review finding, 2026-08-16). All three are engine-generated, never operator text.
            "consumed_by", "consumption_id", "ticket_id",
        }
        # Exempt a value only when it BOTH sits under a digest-named key AND is a 64-hex string —
        # that is a content hash (artifact/verifier-stdout/verifier-source binding) the entropy
        # redactor would otherwise scrub to "[REDACTED]", silently breaking the binding. The
        # conjunction closes both leak shapes: a non-digest secret in a *_sha256 key fails the
        # value check, and a hex-encoded 256-bit secret (openssl rand -hex 32) under any other
        # key fails the key check and gets scrubbed by the 64-char entropy pattern.
        return {
            k: (v if (k in generated_id_keys or _is_digest_field(k, v)
                      or (k == "authority_command" and _is_safe_authority_command(v))
                      or _is_receipt_artifact_digest_map(k, v))
                else redact_obj(v))
            for k, v in value.items()
        }
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
        self.output_root_input = self.output_root.absolute()
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
        self.approvals_path = self.operator_intel / "approvals.ndjson"
        # Fixed OS-owned trust root. It is deliberately not configurable through args or env;
        # a user-writable alternate would restore the same-agent authority bypass.
        self.approval_authority_path = APPROVAL_AUTHORITY_PATH
        self.carry_forward_path = self.operator_intel / "pathway-carry-forward.ndjson"
        self.pathway_run_plans_path = self.operator_intel / "pathway-run-plans.ndjson"
        self.pathway_decisions_path = self.operator_intel / "pathway-decisions.ndjson"
        self.pathway_pilots_path = self.operator_intel / "pathway-pilots.ndjson"
        self.pathway_pilot_latest_path = self.operator_intel / "pathway-pilot-latest.json"
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
    # Truncation here drops the newest records, which is the silent-undercount failure described
    # at NDJSON_READ_MAX_BYTES. Say so on stderr rather than returning a short list quietly.
    try:
        size = p.stat().st_size
    except OSError:
        size = 0
    if size > NDJSON_READ_MAX_BYTES:
        sys.stderr.write(
            f"WARNING: {p} is {size:,} bytes, over the {NDJSON_READ_MAX_BYTES:,}-byte read cap. "
            "The NEWEST records are being dropped and coverage will undercount. Rotate the ledger.\n"
        )
    for line in safe_read_text(p, max_bytes=NDJSON_READ_MAX_BYTES).splitlines():
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


APPROVAL_TTL_SECONDS = 900
APPROVAL_KIND_RELEASE = "release-production-approval"
APPROVAL_KIND_WAIVER = "production-secure-waiver"
APPROVAL_MUTATION_SUBCOMMANDS = frozenset({"approval-issue", "approval-invalidate"})
APPROVAL_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
APPROVAL_TICKET_ID_RE = re.compile(r"^AT-[0-9a-f]{12}$")
APPROVAL_CONSUMPTION_ID_RE = re.compile(r"^AC-[0-9a-f]{12}$")
APPROVAL_INVALIDATION_ID_RE = re.compile(r"^AI-[0-9a-f]{12}$")


class ApprovalEvents(list):
    """Strict approval-ledger view.

    Approval records are authority input, so a partial parse is never useful.  The ordinary
    NDJSON reader intentionally tolerates damaged advisory rows; this reader carries an explicit
    validity bit so every approval consumer can fail closed on one malformed, reordered, or
    truncated event.
    """

    def __init__(self, records=(), *, valid=True, error=""):
        super().__init__(records)
        self.valid = bool(valid)
        self.error = str(error or "")


def _invalid_approval_events(error):
    return ApprovalEvents(valid=False, error=error)


def approval_events_valid(events):
    return isinstance(events, ApprovalEvents) and events.valid


def _approval_event_shape_valid(event):
    if not isinstance(event, dict):
        return False
    event_kind = event.get("event")
    required = {
        "issued": {
            "event", "kind", "subject_digest", "ticket_id", "subject", "issued_at",
            "expires_at", "reason", "work_id", "issued_by",
        },
        "consumed": {
            "event", "kind", "subject_digest", "ticket_id", "at", "work_id", "pathway",
            "consumed_by", "consumption_id",
        },
        "invalidated": {
            "event", "kind", "subject_digest", "ticket_id", "at", "work_id", "reason",
            "invalidated_by", "invalidation_id",
        },
    }
    if event_kind not in required or set(event) != required[event_kind]:
        return False
    if event.get("kind") not in {APPROVAL_KIND_RELEASE, APPROVAL_KIND_WAIVER}:
        return False
    if not APPROVAL_DIGEST_RE.fullmatch(str(event.get("subject_digest") or "")):
        return False
    if not APPROVAL_TICKET_ID_RE.fullmatch(str(event.get("ticket_id") or "")):
        return False
    if not isinstance(event.get("work_id"), str) or not event.get("work_id"):
        return False
    if event_kind == "issued":
        subject = event.get("subject")
        issued_at = parse_ts(str(event.get("issued_at") or ""))
        expires_at = parse_ts(str(event.get("expires_at") or ""))
        return bool(
            isinstance(subject, dict)
            and subject.get("kind") == event.get("kind")
            and subject.get("work_id") == event.get("work_id")
            and approval_subject_digest(subject) == event.get("subject_digest")
            and issued_at is not None
            and expires_at is not None
            and expires_at > issued_at
            and (expires_at - issued_at).total_seconds() <= APPROVAL_TTL_SECONDS
            and isinstance(event.get("reason"), str)
            and event.get("reason")
            and isinstance(event.get("issued_by"), str)
            and event.get("issued_by")
        )
    if event_kind == "consumed":
        return bool(
            parse_ts(str(event.get("at") or "")) is not None
            and isinstance(event.get("pathway"), str)
            and isinstance(event.get("consumed_by"), str)
            and event.get("consumed_by")
            and APPROVAL_CONSUMPTION_ID_RE.fullmatch(
                str(event.get("consumption_id") or "")
            )
        )
    return bool(
        parse_ts(str(event.get("at") or "")) is not None
        and isinstance(event.get("reason"), str)
        and event.get("reason")
        and isinstance(event.get("invalidated_by"), str)
        and event.get("invalidated_by")
        and APPROVAL_INVALIDATION_ID_RE.fullmatch(str(event.get("invalidation_id") or ""))
    )


def _strict_approval_events(path):
    """Read one authority ledger completely or return an invalid empty view."""
    ledger = Path(path)
    if not ledger.exists():
        return ApprovalEvents()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(ledger, flags)
    except OSError as exc:
        return _invalid_approval_events(f"open:{exc.__class__.__name__}")
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            return _invalid_approval_events("not-regular")
        if metadata.st_size > NDJSON_READ_MAX_BYTES:
            return _invalid_approval_events("over-read-cap")
        chunks = []
        remaining = metadata.st_size + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1_048_576, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
    except OSError as exc:
        return _invalid_approval_events(f"read:{exc.__class__.__name__}")
    finally:
        os.close(descriptor)
    if len(raw) != metadata.st_size:
        return _invalid_approval_events("short-read")
    if raw and not raw.endswith(b"\n"):
        return _invalid_approval_events("truncated-tail")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return _invalid_approval_events("invalid-utf8")

    records = []
    issued_by_ticket = {}
    consumed_tickets = set()
    invalidated_tickets = set()
    consumption_ids = set()
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            return _invalid_approval_events(f"blank-line:{line_number}")
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            return _invalid_approval_events(f"malformed-json:{line_number}")
        if not _approval_event_shape_valid(event):
            return _invalid_approval_events(f"invalid-event:{line_number}")
        ticket_id = event["ticket_id"]
        event_kind = event["event"]
        if event_kind == "issued":
            if ticket_id in issued_by_ticket:
                return _invalid_approval_events(f"duplicate-ticket:{line_number}")
            issued_by_ticket[ticket_id] = event
        else:
            issued = issued_by_ticket.get(ticket_id)
            if not issued:
                return _invalid_approval_events(f"event-before-issue:{line_number}")
            if any(
                event.get(field) != issued.get(field)
                for field in ("kind", "subject_digest", "work_id")
            ):
                return _invalid_approval_events(f"ticket-binding-mismatch:{line_number}")
            if event_kind == "consumed":
                consumption_id = event["consumption_id"]
                if ticket_id in consumed_tickets or consumption_id in consumption_ids:
                    return _invalid_approval_events(f"duplicate-consumption:{line_number}")
                consumed_tickets.add(ticket_id)
                consumption_ids.add(consumption_id)
            elif ticket_id in invalidated_tickets:
                return _invalid_approval_events(f"duplicate-invalidation:{line_number}")
            else:
                invalidated_tickets.add(ticket_id)
        records.append(event)
    return ApprovalEvents(records)


def approval_subject_digest(subject):
    """Content binding: canonical JSON (sorted keys, compact separators) so key order can never
    change the digest and any edit to any bound field invalidates the ticket."""
    canonical = json.dumps(subject, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _ephemeral_approval_store(paths):
    """Whether this is an isolated canonical-suite store with no symlink escape.

    The lexical output root matters. A same-user replacement of the live output directory with a
    symlink into a test-shaped path must never make the default CLI unprotected.
    """
    try:
        lexical_root = Path(
            getattr(paths, "output_root_input", Path(paths.approvals_path).parents[1])
        ).absolute()
        test_parent = Path("/private/tmp").absolute()
        relative = lexical_root.relative_to(test_parent)
        if (
            len(relative.parts) != 2
            or not relative.parts[0].startswith("operating-layer-test-")
            or relative.parts[1] != "out"
        ):
            return False
        if lexical_root.resolve(strict=True) != lexical_root:
            return False
        suite_root = test_parent / relative.parts[0]
        metadata = suite_root.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
            return False
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            return False
        expected = lexical_root / "operator-intelligence" / "approvals.ndjson"
        actual = Path(paths.approvals_path).absolute()
        if actual != expected or actual.resolve(strict=False) != actual:
            return False
        cursor = suite_root
        for part in ("out", "operator-intelligence"):
            cursor = cursor / part
            if cursor.exists() and cursor.is_symlink():
                return False
        return True
    except (AttributeError, IndexError, OSError, RuntimeError, ValueError):
        return False


def approval_store_is_protected(paths):
    return not _ephemeral_approval_store(paths)


def _authority_path_is_os_owned(path):
    """Require an unbroken root-owned, non-writable chain for the live trust root."""
    authority = Path(path)
    expected = APPROVAL_AUTHORITY_PATH
    if authority != expected or not authority.is_absolute():
        return False
    components = [authority]
    cursor = authority.parent
    stop = Path("/Library") if sys.platform == "darwin" else Path("/var/lib")
    while True:
        components.append(cursor)
        if cursor == stop:
            break
        if cursor == cursor.parent:
            return False
        cursor = cursor.parent
    try:
        for component in components:
            metadata = component.lstat()
            if stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != 0:
                return False
            if stat.S_IMODE(metadata.st_mode) & 0o022:
                return False
        return stat.S_ISREG(authority.lstat().st_mode)
    except OSError:
        return False


def approval_events_for(paths):
    """Return the effective authority view, never a partial or user-forged one.

    Isolated canonical-suite stores remain self-contained.  Every real store requires the fixed,
    OS-owned authority ledger for issued and invalidated events; the user ledger contributes only
    structurally valid consumptions that bind an exact OS-authorized ticket.
    """
    if not approval_store_is_protected(paths):
        return _strict_approval_events(paths.approvals_path)
    authority_path = Path(
        getattr(paths, "approval_authority_path", APPROVAL_AUTHORITY_PATH)
    )
    if not authority_path.exists():
        return _invalid_approval_events("authority-ledger-missing")
    if not _authority_path_is_os_owned(authority_path):
        return _invalid_approval_events("authority-ledger-permissions")
    authority_events = _strict_approval_events(authority_path)
    if not approval_events_valid(authority_events):
        return _invalid_approval_events(f"authority-{authority_events.error}")
    return authority_events


def latest_approval_event(events, digest, event_kind):
    if not approval_events_valid(events):
        return None
    match = None
    for event in events or []:
        if (isinstance(event, dict) and event.get("event") == event_kind
                and event.get("subject_digest") == digest):
            match = event
    return match


def approval_event_for_ticket(events, ticket_id, event_kind, consumption_id=""):
    """Return the latest exact-ticket event, optionally bound to one consumption id."""
    if not approval_events_valid(events):
        return None
    match = None
    for event in events or []:
        if (not isinstance(event, dict) or event.get("event") != event_kind
                or event.get("ticket_id") != ticket_id):
            continue
        if consumption_id and event.get("consumption_id") != consumption_id:
            continue
        match = event
    return match


def approval_ticket_invalidated(events, ticket_id):
    """An append-only invalidation permanently revokes exactly one issued ticket."""
    if not approval_events_valid(events):
        return True
    return approval_event_for_ticket(events, ticket_id, "invalidated") is not None


@contextlib.contextmanager
def _approvals_write_lock(paths):
    """Exclusive lock around the ledger's read-modify-write. append_records rewrites the whole
    file atomically, which prevents torn files but not lost updates — two unlocked writers can
    each read a consumed-free ledger, both authorize, and the last write erases the first
    consumption. Parallel sessions on one repo are a documented reality here."""
    lock_path = Path(str(paths.approvals_path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _approval_records_size(records):
    return sum(
        len(json.dumps(redact_obj(record), sort_keys=True).encode("utf-8")) + 1
        for record in records
    )


def _approval_write_fits(records):
    """Refuse the write that would cross the read cap, not merely the write after it."""
    return _approval_records_size(records) <= NDJSON_READ_MAX_BYTES


def find_active_approval(events, digest, now=None):
    """Locate a live ticket: issued, unconsumed, unexpired, within the authority's own TTL, with
    a subject that still hashes to its own digest. Returns (issued_event, refusal_reason).

    Consumption is TICKET-scoped, not digest-scoped: only a consumption referencing the latest
    issued event's ticket_id blocks it. A fresh issued event appended after a consumption is a
    new, consumable ticket for the same subject — otherwise one spent ticket would lock a
    legitimate re-approval out forever (adversarial review finding, 2026-08-16)."""
    if not approval_events_valid(events):
        return None, "ledger_invalid"
    now = now or utc_now()
    issued = latest_approval_event(events, digest, "issued")
    if issued is None:
        return None, "no_ticket"
    ticket_id = issued.get("ticket_id", "")
    if not APPROVAL_TICKET_ID_RE.fullmatch(ticket_id):
        return None, "invalid_ticket_id"
    if approval_ticket_invalidated(events, ticket_id):
        return None, "invalidated"
    for event in events or []:
        if (isinstance(event, dict) and event.get("event") == "consumed"
                and event.get("subject_digest") == digest
                and event.get("ticket_id", "") == ticket_id):
            return None, "consumed"
    issued_at = parse_ts(str(issued.get("issued_at") or ""))
    expires_at = parse_ts(str(issued.get("expires_at") or ""))
    if issued_at is None or expires_at is None or expires_at <= issued_at:
        return None, "invalid_window"
    if (expires_at - issued_at).total_seconds() > APPROVAL_TTL_SECONDS:
        return None, "invalid_window"
    if expires_at < now:
        return None, "expired"
    subject = issued.get("subject")
    if not isinstance(subject, dict) or approval_subject_digest(subject) != digest:
        return None, "subject_mismatch"
    return issued, ""


def prebound_approval_for_consumer(events, digest, consumed_by, now=None):
    """Return a root-preconsumed approval only while its first attachment is timely.

    The OS helper binds and consumes at issue time, before the agent can attach the ticket to a
    waiver row or release proof. That pre-consumption must not make the 15-minute review window
    infinite. Status-time corroboration deliberately uses the timeless receipt-specific helpers
    instead, so already persisted historical proof does not expire retroactively.
    """
    if not approval_events_valid(events):
        return None, "ledger_invalid"
    issued = latest_approval_event(events, digest, "issued")
    if issued is None:
        return None, "no_ticket"
    ticket_id = issued.get("ticket_id", "")
    if not APPROVAL_TICKET_ID_RE.fullmatch(ticket_id):
        return None, "invalid_ticket_id"
    if approval_ticket_invalidated(events, ticket_id):
        return None, "invalidated"
    subject = issued.get("subject")
    if not isinstance(subject, dict) or approval_subject_digest(subject) != digest:
        return None, "subject_mismatch"
    issued_at = parse_ts(str(issued.get("issued_at") or ""))
    expires_at = parse_ts(str(issued.get("expires_at") or ""))
    if issued_at is None or expires_at is None or expires_at <= issued_at:
        return None, "invalid_window"
    if (expires_at - issued_at).total_seconds() > APPROVAL_TTL_SECONDS:
        return None, "invalid_window"
    current = now or utc_now()
    if current < issued_at:
        return None, "not_yet_valid"
    if current > expires_at:
        return None, "expired"
    prior = approval_event_for_ticket(events, ticket_id, "consumed")
    if prior is None:
        return None, "consumption_not_human_bound"
    if prior.get("consumed_by") != consumed_by:
        return None, "consumed"
    return prior, ""


def consume_approval(paths, subject, consumed_by, now=None):
    """Single-use consumption bound to one consumer, under the ledger write lock.

    Re-consumption by the SAME consumer is idempotent — a re-logged identical proof or a
    re-covered itinerary row keeps the decision it already earned — while any other consumer
    needs its own live ticket, so one ticket can never authorize two different things. Returns
    (consumed_event, refusal_reason)."""
    digest = approval_subject_digest(subject)
    with _approvals_write_lock(paths):
        events = approval_events_for(paths)
        if not approval_events_valid(events):
            return None, "ledger_invalid"
        if approval_store_is_protected(paths):
            return prebound_approval_for_consumer(
                events, digest, consumed_by, now=now
            )
        issued = latest_approval_event(events, digest, "issued")
        ticket_id = issued.get("ticket_id", "") if isinstance(issued, dict) else ""
        if ticket_id and approval_ticket_invalidated(events, ticket_id):
            return None, "invalidated"
        prior = approval_event_for_ticket(events, ticket_id, "consumed")
        if prior is not None and prior.get("consumed_by") == consumed_by:
            return prior, ""
        issued, refusal = find_active_approval(events, digest, now=now)
        if issued is None:
            return None, refusal
        record = {
            "event": "consumed",
            "kind": issued.get("kind"),
            "subject_digest": digest,
            "ticket_id": issued.get("ticket_id", ""),
            "at": iso_now(),
            "work_id": subject.get("work_id", ""),
            "pathway": subject.get("pathway", ""),
            "consumed_by": consumed_by,
            "consumption_id": f"AC-{sha_text(ticket_id + '|' + digest + '|' + str(consumed_by), 12)}",
        }
        records_to_write = [*events, record]
        if not _approval_write_fits(records_to_write):
            return None, "ledger_over_read_cap"
        # append_records rewrites the whole file atomically, so a true append must carry every
        # existing event forward. The ledger stays append-only at the semantic level: events are
        # never edited or removed, only added.
        write_ndjson(paths.approvals_path, records_to_write)
        return record, ""


def _approval_issuer_identity():
    """Best-effort attribution for an issued ticket. Never a secret, never authentication."""
    try:
        login = os.environ.get("SUDO_USER") or os.environ.get("USER") or ""
        tty = ""
        try:
            tty = os.ttyname(sys.stdin.fileno())
        except Exception:
            tty = "not-a-tty"
        return f"uid={os.getuid()} user={login or 'unknown'} ppid={os.getppid()} tty={tty}"
    except Exception:
        return "unknown"


def _approval_helper_command(action, arguments):
    argv = ["/usr/bin/sudo", "--", str(APPROVAL_HELPER_PATH), action, *map(str, arguments)]
    return "/usr/bin/sudo -k; " + shlex.join(argv)


def release_approval_subject(work_id, project, release_receipt_sha256):
    return {
        "kind": APPROVAL_KIND_RELEASE,
        "work_id": str(work_id or ""),
        "project": str(project or ""),
        "stage": "production",
        "release_receipt_sha256": str(release_receipt_sha256 or ""),
    }


WAIVER_SUBJECT_SCHEMA_VERSION = 2


def work_context_sha256(item, pathway):
    """Bind a waiver to the immutable meaning of one current work obligation.

    Status and proof fields are intentionally excluded because consuming the waiver changes them.
    Identity-shaping fields and the itinerary pathway set are included, so editing the goal,
    project, tier, profile, overlays, or obligation set orphans the human-reviewed waiver.
    """
    if not isinstance(item, dict) or pathway not in PATHWAY_CANON_ORDER:
        return ""
    raw_project = str(item.get("project") or "")
    try:
        resolved_project = str(Path(raw_project).expanduser().resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return ""
    itinerary = item.get("itinerary")
    if not isinstance(itinerary, list):
        return ""
    itinerary_pathways = sorted({
        entry.get("pathway")
        for entry in itinerary
        if isinstance(entry, dict) and entry.get("pathway") in PATHWAY_CANON_ORDER
    }, key=pathway_sort_key)
    if pathway not in itinerary_pathways:
        return ""
    context = {
        "schema_version": 1,
        "work_id": str(item.get("work_id") or ""),
        "project_name": str(item.get("project_name") or ""),
        "project_path_input": raw_project,
        "project_path_resolved": resolved_project,
        "goal": item.get("goal"),
        "tier": item.get("tier"),
        "outcome_profile": item.get("outcome_profile"),
        "risk_overlays": item.get("risk_overlays"),
        "itinerary_pathways": itinerary_pathways,
        "obligation": {"pathway": pathway},
    }
    try:
        encoded = json.dumps(
            context, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        return ""
    return hashlib.sha256(encoded).hexdigest()


def waiver_subject(work_id, project, pathway, reason, context_sha256):
    return {
        "kind": APPROVAL_KIND_WAIVER,
        "schema_version": WAIVER_SUBJECT_SCHEMA_VERSION,
        "work_id": str(work_id or ""),
        "project": str(project or ""),
        "pathway": str(pathway or ""),
        "reason": str(reason or ""),
        "work_context_sha256": str(context_sha256 or ""),
    }


def approval_claim_corroborated(digest, expected_subject, consumer, consumption_id, events):
    """The ledger, not the claiming row, is the approval trust root.

    One join for both ticket kinds, so the four invariants (well-formed digest, an issued event
    whose subject is exactly what the claim implies, a consumption by this exact consumer, and a
    matching consumption id) can never drift apart. Also re-checks the issued window against the
    authority's own TTL, so a hand-widened expiry in the ledger cannot be honored later."""
    if not approval_events_valid(events):
        return False
    digest = str(digest or "")
    if not APPROVAL_DIGEST_RE.fullmatch(digest):
        return False
    consumed = next(
        (
            event for event in reversed(events or [])
            if isinstance(event, dict)
            and event.get("event") == "consumed"
            and event.get("subject_digest") == digest
            and event.get("consumption_id") == consumption_id
            and event.get("consumed_by") == consumer
        ),
        None,
    )
    if consumed is None:
        return False
    ticket_id = consumed.get("ticket_id", "")
    if not APPROVAL_TICKET_ID_RE.fullmatch(ticket_id):
        return False
    issued = approval_event_for_ticket(events, ticket_id, "issued")
    if issued is None or issued.get("subject_digest") != digest:
        return False
    if approval_ticket_invalidated(events, ticket_id):
        return False
    subject = issued.get("subject") if isinstance(issued.get("subject"), dict) else {}
    if subject != expected_subject or approval_subject_digest(subject) != digest:
        return False
    issued_at = parse_ts(str(issued.get("issued_at") or ""))
    expires_at = parse_ts(str(issued.get("expires_at") or ""))
    if issued_at is None or expires_at is None:
        return False
    lifetime = (expires_at - issued_at).total_seconds()
    if lifetime <= 0 or lifetime > APPROVAL_TTL_SECONDS:
        return False
    consumed_at = parse_ts(str(consumed.get("at") or ""))
    if consumed_at is None or not (issued_at <= consumed_at <= expires_at):
        return False
    return (
        consumed.get("consumed_by") == consumer
        and consumed.get("consumption_id") == consumption_id
        and consumed.get("subject_digest") == digest
    )


def release_approval_corroborated(proof, events):
    """A release proof credits only when its claimed approval maps to an issued subject binding
    this exact work/project/receipt digest and to a consumption bound to this exact proof_id."""
    if not isinstance(proof, dict):
        return False
    return approval_claim_corroborated(
        proof.get("release_approval_digest"),
        release_approval_subject(
            proof.get("work_id"), proof.get("project"), proof.get("release_receipt_sha256")),
        proof.get("proof_id"),
        proof.get("release_approval_consumed_id"),
        events,
    )


def release_approval_failure_state(proof, events):
    """Classify why one historical release claim is not currently corroborated."""
    if not approval_events_valid(events):
        return "approval_ledger_invalid"
    if not isinstance(proof, dict):
        return "release_proof_missing"
    consumed = next(
        (
            event for event in events
            if event.get("event") == "consumed"
            and event.get("subject_digest") == proof.get("release_approval_digest")
            and event.get("consumption_id") == proof.get("release_approval_consumed_id")
            and event.get("consumed_by") == proof.get("proof_id")
        ),
        None,
    )
    if consumed and approval_ticket_invalidated(events, consumed.get("ticket_id", "")):
        return "approval_invalidated"
    return "approval_uncorroborated"


def waiver_corroborated(entry, item, events):
    """A production-secure N/A row survives status recomputation only when its waiver claim maps
    back to an issued subject for this exact work/project/pathway/reason and to that row's own
    work-cover consumption."""
    if not isinstance(entry, dict):
        return False
    item = item if isinstance(item, dict) else {}
    pathway = entry.get("pathway")
    context_sha256 = work_context_sha256(item, pathway)
    if not context_sha256:
        return False
    return approval_claim_corroborated(
        entry.get("waiver_digest"),
        waiver_subject(
            item.get("work_id"), item.get("project_name"), pathway,
            entry.get("reason"), context_sha256,
        ),
        f"work-cover:{item.get('work_id')}:{pathway}",
        entry.get("waiver_consumed_id"),
        events,
    )


def proof_credits_pathway(proof, approval_events=None, verifier_binding_cache=None):
    """The single crediting predicate every consumer must use.

    `proof_is_verified` answers "did a verifier really pass"; this adds the trust-root join a
    proof row cannot vouch for on its own. Release credit requires ledger corroboration, so a
    forged row carrying approval fields cannot raise the proof rate, ride a carry-forward baton,
    or inflate audit metrics (adversarial review finding, 2026-08-16)."""
    if not proof_is_verified(proof, verifier_binding_cache):
        return False
    if (proof or {}).get("pathway") != "release":
        return True
    return release_approval_corroborated(proof, approval_events or [])


def proof_result_is_passing(result):
    """Return True only for an explicit pass-like proof result.

    A verifier exiting 0 proves that its checks ran successfully; it does not turn an operator
    outcome such as ``blocked``, ``open``, ``partial``, or ``fail`` into a passing result. Keep the
    accepted vocabulary deliberately small while preserving the legacy proof-add default
    (``present``) and descriptive ``pass: ...`` / ``passed-...`` results already in the ledger.
    """
    normalized = str(result or "").strip().lower()
    if normalized in {
        "approved", "complete", "completed", "green", "ok", "pass", "passed", "present",
        "ready", "succeeded", "success", "verified",
    }:
        return True
    return bool(re.match(r"^(?:pass|passed)(?:[\s:_-].*)$", normalized))


def observability_bound_contract_is_current(proof, contract_root=None):
    """Verify a historical proof against its exact engine-owned contract snapshot."""
    if not isinstance(proof, dict):
        return False
    key = str(proof.get("observability_contract_key") or "")
    project_key = str(proof.get("observability_project_key") or "")
    if (not key or key.startswith("/") or "\\" in key
            or any(part in {"", ".", ".."} for part in key.split("/"))):
        return False
    if (project_key in set(OBSERVABILITY_PROJECT_CONTRACT_ALIASES.values())
            and project_key not in OBSERVABILITY_PROJECT_CONTRACT_ALIASES):
        return False
    if OBSERVABILITY_PROJECT_CONTRACT_ALIASES.get(project_key, project_key) != key:
        return False
    root = observability_contracts_dir(contract_root)
    if root is None:
        return False
    parts = key.split("/")
    expected_path = root.joinpath(*parts[:-1], f"{parts[-1]}.json")
    recorded_path = Path(str(proof.get("observability_contract_path") or ""))
    if recorded_path != expected_path or expected_path.is_symlink():
        return False
    try:
        if expected_path.parent.resolve() != expected_path.parent:
            return False
    except OSError:
        return False
    contract, errors, current_sha256 = load_observability_contract_snapshot(expected_path)
    if errors or contract.get("project_key") != key:
        return False
    bound_sha256 = str(proof.get("observability_contract_sha256") or "")
    verifier_sha256 = str(
        (proof.get("observability_receipt") or {}).get("verifier_source_sha256") or "")
    return (
        bool(re.fullmatch(r"[0-9a-f]{64}", bound_sha256))
        and current_sha256 == bound_sha256
        and proof.get("observability_contract_post_sha256") == bound_sha256
        and proof.get("observability_contract_schema_version") == contract.get("schema_version")
        and verifier_sha256 in set(contract.get("trusted_verifier_sha256") or [])
        and proof.get("observability_executed_verifier_sha256") == verifier_sha256
        and proof.get("observability_post_verifier_sha256") == verifier_sha256
    )


def proof_is_verified(
        proof, verifier_binding_cache=None, observability_contract_root=None):
    """Keystone: a proof counts as REAL verification ONLY when a re-executed verifier exited 0
    on an explicitly passing result. Free-text attestation (a --verified-by string) and bare human
    attestation (a --reviewer name) are claims, not verifications — a name is not a verifiable
    receipt, so it cannot prove on its own (a dual-critic pass caught --reviewer as the same
    forgery under a different flag). Only `executed` proves; `signed`/`attested` are recorded for
    accountability but never flip a pathway to `proved` or raise the autonomy proof rate. This is
    what makes `proved` mean a verification actually passed. (Verifiable human sign-off — a real
    signature/approval receipt — is a future strengthening of the `signed` tier.)"""
    if not isinstance(proof, dict):
        return False
    if not proof_result_is_passing(proof.get("result")):
        return False
    template_check = proof.get("template_check")
    if (proof.get("pathway") in {"release", "observability"} and isinstance(template_check, dict)
            and template_check.get("valid") is False):
        return False
    base_verified = (
        proof.get("verifier_strength") == "executed"
        and proof.get("exit_code") == 0
        and not proof.get("trivial_verifier")
        and proof.get("canary_mutant_failed") is not False
    )
    if not base_verified:
        return False
    if (proof.get("pathway") not in {"release", "observability"}
            and not generic_verifier_source_is_current(proof, verifier_binding_cache)):
        return False
    if proof.get("pathway") == "release":
        if proof.get("release_provider_action_contract") is True:
            return False
        if RELEASE_PRODUCTION_APPROVAL_STATE != "CONFIGURED_AND_VERIFIED":
            return False
        return (
            proof.get("canary_mutant_failed") is True
            and proof.get("release_snapshot_stable") is True
            and not proof.get("release_snapshot_errors")
            and proof.get("release_credit_scope") == "production"
            and not proof.get("release_receipt_errors")
            and set((proof.get("release_artifact_sha256") or {}))
            == set(release_receipt_artifact_fields(proof.get("release_receipt")))
            and all(
                re.fullmatch(r"[0-9a-f]{64}", str(value or ""))
                for value in (proof.get("release_artifact_sha256") or {}).values()
            )
            and proof.get("release_verifier_bound") is True
            and not proof.get("release_verifier_errors")
            and proof.get("release_approval_verified") is True
            and bool(APPROVAL_DIGEST_RE.fullmatch(str(proof.get("release_approval_digest") or "")))
            and bool(proof.get("release_approval_consumed_id"))
        )
    if proof.get("pathway") == "observability":
        if not observability_bound_contract_is_current(
                proof, observability_contract_root):
            return False
        return (
            proof.get("canary_mutant_failed") is True
            and proof.get("observability_snapshot_stable") is True
            and not proof.get("observability_snapshot_errors")
            and proof.get("observability_outcome") == "runtime"
            and proof.get("observability_credit_scope") in {"runtime", "production"}
            and not proof.get("observability_receipt_errors")
            and set((proof.get("observability_artifact_sha256") or {}))
            == set(OBSERVABILITY_RECEIPT_ARTIFACT_FIELDS)
            and all(
                re.fullmatch(r"[0-9a-f]{64}", str(value or ""))
                for value in (proof.get("observability_artifact_sha256") or {}).values()
            )
            and set((proof.get("observability_artifact_canary_results") or {}))
            == set(OBSERVABILITY_RECEIPT_ARTIFACT_FIELDS)
            and all(
                value is True
                for value in (proof.get("observability_artifact_canary_results") or {}).values()
            )
            and proof.get("observability_artifact_restoration_sha256")
            == proof.get("observability_artifact_sha256")
            and not proof.get("observability_artifact_canary_errors")
            and proof.get("observability_verifier_bound") is True
            and not proof.get("observability_verifier_errors")
        )
    return True


def proof_can_carry_forward(proof):
    """Allow verified success or a verified high-risk hold to carry constraints.

    Release and observability holds influence routing without crediting their pathways. This
    predicate accepts only fully bound blocked states, so a baton can reduce authority but never
    manufacture readiness.
    """
    if proof_is_verified(proof):
        return True
    if not isinstance(proof, dict):
        return False
    template = proof.get("template_check") or {}
    if proof.get("pathway") == "observability":
        return (
            proof.get("verifier_strength") == "executed"
            and proof.get("exit_code") == 0
            and not proof.get("trivial_verifier")
            and proof.get("canary_mutant_failed") is not False
            and proof.get("observability_snapshot_stable") is True
            and not proof.get("observability_snapshot_errors")
            and template.get("valid") is True
            and proof.get("observability_outcome") == "blocked_no_runtime"
            and not proof.get("observability_receipt_errors")
            and proof.get("observability_verifier_bound") is True
            and not proof.get("observability_verifier_errors")
            and _is_sha256_digest(proof.get("artifact_sha256"))
            and _is_sha256_digest(proof.get("observability_receipt_sha256"))
            and isinstance(proof.get("observability_receipt"), dict)
            and bool(proof.get("observability_receipt"))
        )
    if proof.get("pathway") != "release":
        return False
    markers = proof.get("release_verifier_markers") or {}
    blocking_marker = (
        markers.get("RELEASE_DECISION", "").upper() in {"NO_RELEASE", "HOLD", "BLOCKED"}
        or markers.get("PATHWAY_RESULT", "").upper() == "BLOCKED"
        or markers.get("PRODUCTION_STATUS", "").upper() == "NOT_DEPLOYED"
    )
    return (
        proof.get("verifier_strength") == "executed"
        and proof.get("exit_code") == 0
        and not proof.get("trivial_verifier")
        and proof.get("release_snapshot_stable") is True
        and not proof.get("release_snapshot_errors")
        and template.get("valid") is True
        and isinstance(proof.get("release_receipt"), dict)
        and bool(proof.get("release_receipt"))
        and blocking_marker
    )


CARRY_FORWARD_LIST_FIELDS = [
    "what_changed",
    "more_relevant",
    "less_relevant",
    "next_pathway_must_use",
    "do_not_do_yet",
    "open_decisions",
    "active_risk_overlays",
]
CARRY_FORWARD_REQUIRED_FIELDS = [
    "carry_forward_id",
    "work_id",
    "project",
    "pathway",
    "source_artifact",
    "summary",
    *CARRY_FORWARD_LIST_FIELDS,
    "artifact_sha256",
    "created_at",
]
VERIFIER_TEMPLATES = {
    "govern": {"required_artifact_terms": ("decision", "verifier"), "recommended_command": "python3 <govern-verifier.py>"},
    "research": {"required_artifact_terms": ("question", "sources"), "recommended_command": "python3 <research-verifier.py>"},
    "data": {"required_artifact_terms": ("lineage", "verification"), "recommended_command": "python3 <data-verifier.py>"},
    "security": {"required_artifact_terms": ("threat", "verification"), "recommended_command": "python3 <security-verifier.py>"},
    "design": {"required_artifact_terms": ("workflow", "verification"), "recommended_command": "python3 <design-verifier.py>"},
    "implementation": {"required_artifact_terms": ("delivered", "verification"), "recommended_command": "python3 <implementation-verifier.py>"},
    "quality": {"required_artifact_terms": ("regression", "verification"), "recommended_command": "python3 <quality-verifier.py>"},
    "field": {"required_artifact_terms": ("reviewer", "send state"), "recommended_command": "python3 <field-verifier.py>"},
    "observability": {"required_artifact_terms": ("signal", "verification"), "recommended_command": "python3 <observability-verifier.py>"},
    "techdebt": {"required_artifact_terms": ("decision", "verification"), "recommended_command": "python3 <techdebt-verifier.py>"},
    "release": {"required_artifact_terms": ("rollback", "verification"), "recommended_command": "python3 <release-verifier.py>"},
    "docs": {"required_artifact_terms": ("delivered", "verification"), "recommended_command": "python3 <docs-verifier.py>"},
}


def carry_forward_id_for(work_id, pathway, source_artifact, artifact_sha256):
    return f"CF-{sha_text('|'.join(str(p) for p in (work_id, pathway, source_artifact, artifact_sha256)), 12)}"


def _bullet_lines(text):
    out = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(("-", "*")):
            stripped = stripped[1:].strip()
        if stripped:
            out.append(stripped)
    return out


def _json_carry_forward_sections(text):
    """Extract a carry-forward baton from one strict JSON object.

    JSON receipts are first-class proof artifacts, so they must preserve the same durable
    continuity fields as Markdown reports. Duplicate keys, non-finite numbers, malformed list
    fields, and non-object roots fail closed instead of silently degrading to fallback prose.
    """
    if not (text or "").lstrip().startswith("{"):
        return None
    duplicates = []

    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                duplicates.append(str(key))
            else:
                obj[key] = value
        return obj

    def reject_constant(value):
        raise ValueError(f"non-finite number {value}")

    def finite_number(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"non-finite number {value}")
        return number

    try:
        data = json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
            parse_float=finite_number,
        )
    except (TypeError, ValueError):
        return {}
    if duplicates or not isinstance(data, dict):
        return {}

    parsed = {}
    summary = data.get("summary") or data.get("scope")
    if isinstance(summary, str) and summary.strip():
        parsed["summary"] = summary.strip()[:500]
    for field in CARRY_FORWARD_LIST_FIELDS:
        if field not in data:
            continue
        values = data[field]
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            return {}
        parsed[field] = [item.strip() for item in values if item.strip()][:12]
    return parsed


def extract_carry_forward_sections(text):
    """Parse durable carry-forward fields from JSON receipts or Markdown artifacts.

    The store is authoritative and structured; this parser lets an artifact provide better values
    than the safe defaults. JSON is strict and fail-closed. Markdown recognizes headings such as
    `## What Changed`. Both paths remain deterministic and stdlib-only.
    """
    json_sections = _json_carry_forward_sections(text)
    if json_sections is not None:
        return json_sections
    aliases = {
        "summary": "summary",
        "what changed": "what_changed",
        "what_changed": "what_changed",
        "more relevant": "more_relevant",
        "more_relevant": "more_relevant",
        "less relevant": "less_relevant",
        "less_relevant": "less_relevant",
        "next pathway must use": "next_pathway_must_use",
        "next_pathway_must_use": "next_pathway_must_use",
        "do not do yet": "do_not_do_yet",
        "do_not_do_yet": "do_not_do_yet",
        "open decisions": "open_decisions",
        "open_decisions": "open_decisions",
        "active risk overlays": "active_risk_overlays",
        "active_risk_overlays": "active_risk_overlays",
    }
    sections, current = {}, None
    for line in (text or "").splitlines():
        m = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if m:
            label = re.sub(r"[^a-z0-9_ ]+", "", m.group(1).strip().lower())
            current = aliases.get(label)
            if current:
                sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)
    parsed = {}
    if "summary" in sections:
        summary = " ".join(_bullet_lines("\n".join(sections["summary"])))[:500]
        if summary:
            parsed["summary"] = summary
    for field in CARRY_FORWARD_LIST_FIELDS:
        if field in sections:
            items = _bullet_lines("\n".join(sections[field]))[:12]
            if items:
                parsed[field] = items
    return parsed


def verifier_template_for(pathway):
    template = VERIFIER_TEMPLATES.get(pathway)
    if not template:
        return {}
    return {
        "id": f"{pathway}-v1",
        "pathway": pathway,
        "required_artifact_terms": list(template["required_artifact_terms"]),
        "required_carry_forward_fields": list(CARRY_FORWARD_LIST_FIELDS),
        "recommended_command": template["recommended_command"],
    }


def check_verifier_template(pathway, evidence_text):
    """Report whether an artifact has the pathway's minimum proof shape.

    This is intentionally additive: executed verification remains the only way to prove an
    itinerary entry, while this check makes hollow artifacts visible to the operator.
    """
    template = verifier_template_for(pathway)
    if not template:
        return {"valid": False, "template_id": "", "missing": ["unknown pathway template"]}
    text = evidence_text or ""
    normalized = text.lower()
    missing = [term for term in template["required_artifact_terms"] if term not in normalized]
    sections = extract_carry_forward_sections(text)
    missing += [field for field in CARRY_FORWARD_LIST_FIELDS if field not in sections]
    return {
        "valid": not missing,
        "template_id": template["id"],
        "missing": missing,
        "required_artifact_terms": template["required_artifact_terms"],
        "required_carry_forward_fields": template["required_carry_forward_fields"],
        "recommended_command": template["recommended_command"],
    }


def first_nonempty_snippet(text, limit=260):
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:limit]
    return ""


def build_carry_forward_record(proof, work_item=None, approval_events=None):
    if not proof or not proof_can_carry_forward(proof):
        return None
    credits_pathway = proof_credits_pathway(proof, approval_events)
    if credits_pathway:
        pathway_outcome = "proved"
    elif proof.get("pathway") == "observability":
        pathway_outcome = "blocked_no_runtime"
    else:
        pathway_outcome = "blocked_no_deploy"
    source_artifact = proof.get("evidence_path", "")
    artifact_sha256 = proof.get("artifact_sha256") or sha256_file(source_artifact)
    pathway = proof.get("pathway", "")
    work_id = proof.get("work_id", "")
    project_path = proof.get("project_path") or (work_item or {}).get("project", "")
    project_name = proof.get("project") or (work_item or {}).get("project_name", "") or Path(project_path).name
    evidence_text = safe_read_text(source_artifact, max_bytes=64_000) if source_artifact else ""
    extracted = extract_carry_forward_sections(evidence_text)
    fallback_summary = first_nonempty_snippet(evidence_text) or f"{pathway} produced proof artifact {Path(source_artifact).name}."
    record = {
        "carry_forward_id": carry_forward_id_for(work_id, pathway, source_artifact, artifact_sha256),
        "work_id": work_id,
        "project": project_name,
        "project_path": project_path,
        "pathway": pathway,
        "source_artifact": source_artifact,
        "summary": extracted.get("summary") or fallback_summary,
        "what_changed": extracted["what_changed"] if "what_changed" in extracted else ([
            f"{pathway} completed with verified evidence at {source_artifact}."
        ] if credits_pathway else [
            f"{pathway} recorded a verified hold at {source_artifact}; coverage remains open."
        ]),
        "more_relevant": extracted["more_relevant"] if "more_relevant" in extracted else [
            f"Use the {pathway} proof before ranking or executing the next pathway."
        ],
        "less_relevant": extracted["less_relevant"] if "less_relevant" in extracted else [],
        "next_pathway_must_use": (
            extracted["next_pathway_must_use"]
            if "next_pathway_must_use" in extracted else [
            f"Read {source_artifact} before acting on the next recommendation."
        ]),
        "do_not_do_yet": extracted["do_not_do_yet"] if "do_not_do_yet" in extracted else [],
        "open_decisions": extracted["open_decisions"] if "open_decisions" in extracted else [],
        "active_risk_overlays": (
            extracted["active_risk_overlays"]
            if "active_risk_overlays" in extracted else [
            o.get("id", "") for o in (work_item or {}).get("risk_overlays", []) if o.get("id")
        ]),
        "artifact_sha256": artifact_sha256,
        "proof_id": proof.get("proof_id", ""),
        "run_id": proof.get("run_id", ""),
        "recommendation_id": proof.get("recommendation_id", ""),
        "credits_pathway": credits_pathway,
        "pathway_outcome": pathway_outcome,
        "result": proof.get("result", ""),
        "created_at": iso_now(),
        "source": "operating-layer carry-forward",
    }
    return record if carry_forward_is_valid(record) else None


def carry_forward_is_valid(record):
    if not isinstance(record, dict):
        return False
    if any(field not in record for field in CARRY_FORWARD_REQUIRED_FIELDS):
        return False
    for field in ("carry_forward_id", "work_id", "pathway", "source_artifact", "summary", "artifact_sha256", "created_at"):
        if not str(record.get(field, "")).strip():
            return False
    return all(isinstance(record.get(field), list) for field in CARRY_FORWARD_LIST_FIELDS)


def upsert_carry_forward(paths, record):
    if not carry_forward_is_valid(record):
        return read_ndjson(paths.carry_forward_path)
    records = [r for r in read_ndjson(paths.carry_forward_path) if r.get("carry_forward_id") != record.get("carry_forward_id")]
    records.append(record)
    write_ndjson(paths.carry_forward_path, records)
    return records


def carry_forwards_for_work(paths, work_id):
    return [r for r in read_ndjson(paths.carry_forward_path)
            if r.get("work_id") == work_id and carry_forward_is_valid(r)]


def latest_carry_forward_for_work(paths, work_id):
    records = carry_forwards_for_work(paths, work_id)
    if not records:
        return {}
    # NDJSON append order is the deterministic tie-breaker when multiple proofs land inside
    # the same timestamp second. The most recently written baton must win continuity.
    latest = max(enumerate(records), key=lambda item: (item[1].get("created_at", ""), item[0]))[1]
    release_batons = [
        record for record in records
        if record.get("pathway") == "release" and record.get("credits_pathway") is True
    ]
    if not release_batons:
        return latest
    proofs = read_ndjson(paths.proofs_path)
    approval_events = approval_events_for(paths)
    release_proof_ids = {
        baton.get("proof_id") for baton in release_batons if baton.get("proof_id")
    }
    valid_release_proof = next(
        (
            proof for proof in reversed(proofs)
            if proof.get("work_id") == work_id
            and (
                proof.get("pathway") == "release"
                or proof.get("proof_id") in release_proof_ids
            )
            and release_approval_corroborated(proof, approval_events)
        ),
        None,
    )
    if valid_release_proof is not None:
        return latest
    latest_release = max(
        enumerate(release_batons),
        key=lambda item: (item[1].get("created_at", ""), item[0]),
    )[1]
    release_proof = next(
        (
            proof for proof in reversed(proofs)
            if proof.get("proof_id") == latest_release.get("proof_id")
        ),
        None,
    )
    release_state = release_approval_failure_state(release_proof, approval_events)
    release_messages = {
        "approval_ledger_invalid": (
            "The approval authority ledger is unavailable or invalid; release proof is open again.",
            "Current approval-ledger state cannot corroborate the historical release credit.",
            "Restore the OS-owned approval authority ledger, then recheck release credit.",
        ),
        "approval_invalidated": (
            "The release approval no longer corroborates; release proof is open again.",
            "Current approval-ledger state invalidated the release credit.",
            "Re-establish independent human approval before release credit.",
        ),
        "approval_uncorroborated": (
            "The release claim does not match current approval authority; release proof is open again.",
            "Current approval-ledger state does not corroborate the historical release claim.",
            "Reconcile the exact issued ticket, consumption, and release proof binding.",
        ),
        "release_proof_missing": (
            "The credited release baton has no referenced proof row; release proof is open again.",
            "The current proof ledger cannot resolve the historical release baton.",
            "Restore or replace the exact release proof before relying on release credit.",
        ),
    }
    release_summary, release_change, release_next = release_messages[release_state]
    release_what_changed = [release_change]
    release_next_pathway_must_use = [release_next]
    release_hold = ["Do not treat the historical release carry-forward as proved."]
    corrected = dict(latest)
    corrected.update({
        "release_credit_current": False,
        "release_pathway_outcome": release_state,
        "release_proof_id": (
            release_proof.get("proof_id", "")
            if release_proof is not None else latest_release.get("proof_id", "")
        ),
        "release_approval_state_reason": (
            getattr(approval_events, "error", "") or release_state
        ),
        "release_approval_summary": release_summary,
        "release_approval_what_changed": release_what_changed,
        "release_approval_next_pathway_must_use": release_next_pathway_must_use,
        "release_approval_do_not_do_yet": release_hold,
    })
    if release_state == "approval_invalidated":
        corrected["invalidated_release_proof_id"] = release_proof.get("proof_id", "")
    if latest.get("pathway") == "release":
        corrected.update({
            "credits_pathway": False,
            "pathway_outcome": release_state,
            "summary": release_summary,
            "what_changed": release_what_changed,
            "next_pathway_must_use": release_next_pathway_must_use,
            "do_not_do_yet": release_hold,
            "source": "operating-layer invalidation-aware carry-forward view",
        })
    return corrected


def release_carry_forward_overlay(carry_forward):
    """Render the namespaced release hold without replacing a later pathway's own baton."""
    carry_forward = carry_forward if isinstance(carry_forward, dict) else {}
    if carry_forward.get("release_credit_current") is not False:
        return ""
    raw_summary = carry_forward.get("release_approval_summary")
    summary = raw_summary.strip() if isinstance(raw_summary, str) else ""

    def string_items(value):
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    next_steps = "; ".join(string_items(
        carry_forward.get("release_approval_next_pathway_must_use")
    )[:2])
    holds = "; ".join(string_items(
        carry_forward.get("release_approval_do_not_do_yet")
    )[:2])
    pieces = [summary]
    if next_steps:
        pieces.append(f"Required: {next_steps}")
    if holds:
        pieces.append(f"Hold: {holds}")
    return " ".join(piece for piece in pieces if piece)


def carry_forward_effect(carry_forward, recommended_pathway):
    if not carry_forward:
        return "No prior carry-forward record exists for this active work item yet."
    must_use = "; ".join(carry_forward.get("next_pathway_must_use", [])[:2]) or "use the source artifact"
    changed = "; ".join(carry_forward.get("what_changed", [])[:2])
    overlays = ", ".join(carry_forward.get("active_risk_overlays", [])[:4])
    changed_part = f" It changed: {changed}." if changed else ""
    overlay_part = f" Active overlays remain: {overlays}." if overlays else ""
    effect = (
        f"Latest `{carry_forward.get('pathway')}` output says: {carry_forward.get('summary')} "
        f"{changed_part}{overlay_part} Therefore `{recommended_pathway}` must use: {must_use}."
    )
    release_overlay = release_carry_forward_overlay(carry_forward)
    if release_overlay:
        effect += f" Release approval overlay: {release_overlay}"
    return effect


def pathways_referenced_by_text(text):
    haystack = (text or "").lower()
    found = []
    for pathway in PATHWAY_ORDER:
        if re.search(rf"\b{re.escape(pathway)}\b", haystack):
            found.append(pathway)
    if not found:
        pseudo = {
            "customer": "field",
            "feedback": "field",
            "approval": "field",
            "send": "field",
            "human-gate": "field",
            "rls": "security",
            "authz": "security",
            "tenant": "security",
            "tenant-authz": "security",
            "privacy-evidence": "security",
            "migration": "data",
            "schema": "data",
            "rollback": "release",
            "production-mutation": "release",
            "deploy": "release",
            "ui-proof": "design",
            "a11y": "design",
            "responsive": "design",
            "llm-agent-eval": "quality",
            "eval": "quality",
            "trace": "observability",
            "alert": "observability",
        }
        for token, pathway in pseudo.items():
            if token in haystack and pathway not in found:
                found.append(pathway)
    return sorted(found, key=pathway_sort_key)


def proved_pathways_from_proofs(
        work_id, proofs, approval_events=None, verifier_binding_cache=None):
    """Evidence side of the itinerary join: every pathway carrying at least one genuinely-verified
    proof (`proof_is_verified` — a re-executed verifier that exited 0) for this work item, mapped
    to the run_id (or proof_id) that earned it. A verified proof proves its pathway no matter which
    command recorded it — an inline work-log, a later `proof-add`, or an earlier ledger row. Without
    this join, verification logged through `proof-add` never reached the itinerary and coverage
    stalled at `logged_unverified` even after a verifier had passed.

    Release proofs additionally require ledger corroboration of their approval claim against
    `approval_events`; a caller that cannot supply the approvals ledger cannot credit release."""
    proved = {}
    verifier_binding_cache = (
        verifier_binding_cache if verifier_binding_cache is not None else {}
    )
    for proof in proofs or []:
        if not isinstance(proof, dict) or proof.get("work_id") != work_id:
            continue
        pathway = proof.get("pathway")
        if (pathway and pathway not in proved
                and proof_is_verified(proof, verifier_binding_cache)
                and not proof_is_stale(proof)):
            if (pathway == "release"
                    and not release_approval_corroborated(proof, approval_events or [])):
                continue
            proved[pathway] = proof.get("run_id") or proof.get("proof_id") or ""
    return proved


def apply_proof_coverage(itinerary, proved_map):
    """Flip every still-`required` itinerary entry that now has a verified proof to `proved`
    (mutating entries in place); return True if anything changed. Never downgrades an explicit
    `na` or an already-`proved` entry — it only closes the join the verifier already earned. This
    mirrors the inline work-log flip so the two proof paths converge on one rule."""
    changed = False
    for entry in itinerary or []:
        pathway = entry.get("pathway")
        if entry.get("status", "required") == "required" and pathway in (proved_map or {}):
            entry["status"] = "proved"
            entry["proved_by_run"] = proved_map[pathway]
            changed = True
    return changed


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


_GENERIC_PYTHON_FLAGS = {"-B"}
_GENERIC_VERIFIER_SNAPSHOT_LOADER = """\
import pathlib
import sys

filename = sys.argv[1]
sys.argv = [filename, *sys.argv[2:]]
script_dir = str(pathlib.Path(filename).parent)
sys.path.insert(0, script_dir)
namespace = {
    "__name__": "__main__",
    "__file__": filename,
    "__cached__": None,
    "__loader__": None,
    "__package__": None,
    "__spec__": None,
}
source = sys.stdin.buffer.read()
exec(compile(source, filename, "exec"), namespace, namespace)
"""
_PROVIDER_ACTION_VERIFIER_SNAPSHOT_LOADER = """\
import sys

filename = sys.argv[1]
reported_executable = sys.argv[2]
sys.argv = [filename, *sys.argv[3:]]
sys.executable = reported_executable
namespace = {
    "__name__": "__main__",
    "__file__": filename,
    "__cached__": None,
    "__loader__": None,
    "__package__": None,
    "__spec__": None,
}
source = sys.stdin.buffer.read()
exec(compile(source, filename, "exec"), namespace, namespace)
"""


def release_provider_action_local_import_errors(source_bytes, source_path):
    """Reject imports that can execute unapproved Python beside a provider-action verifier.

    The approved source may use the standard library or installed packages. A module or package
    available through the verifier's own directory is mutable second-source code, so the closed
    release-provider-action contract refuses it before executing the verifier snapshot.
    """
    try:
        tree = ast.parse(source_bytes, filename=str(source_path))
        source_dir = Path(source_path).resolve(strict=True).parent
    except (OSError, SyntaxError, TypeError, ValueError, UnicodeDecodeError):
        return ["release provider action verifier source could not be parsed safely"]

    def resolves_beside_source(module_name):
        module_name = str(module_name or "").lstrip(".")
        parts = module_name.split(".") if module_name else []
        if not parts or not all(part.isidentifier() for part in parts):
            return False
        module_path = source_dir.joinpath(*parts)
        candidates = (
            module_path.with_suffix(".py"),
            module_path / "__init__.py",
            module_path,
        )
        for candidate in candidates:
            try:
                if candidate.is_symlink() or candidate.is_file() or candidate.is_dir():
                    return True
            except OSError:
                return True
        return False

    errors = []
    importlib_aliases = {"importlib"}
    import_module_aliases = set()
    builtins_aliases = {"builtins"}
    dunder_import_aliases = {"__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    importlib_aliases.add(alias.asname or alias.name)
                if alias.name == "builtins":
                    builtins_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module == "importlib":
                import_module_aliases.update(
                    alias.asname or alias.name
                    for alias in node.names if alias.name == "import_module"
                )
            if node.level == 0 and node.module == "builtins":
                dunder_import_aliases.update(
                    alias.asname or alias.name
                    for alias in node.names if alias.name == "__import__"
                )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if resolves_beside_source(alias.name):
                    errors.append(
                        f"release provider action verifier imports local Python module "
                        f"{alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                errors.append(
                    "release provider action verifier uses a relative Python import"
                )
            elif resolves_beside_source(node.module):
                errors.append(
                    f"release provider action verifier imports local Python module "
                    f"{node.module}"
                )
        elif isinstance(node, ast.Call):
            dynamic_import = False
            if isinstance(node.func, ast.Name):
                dynamic_import = node.func.id in (
                    import_module_aliases | dunder_import_aliases
                )
            elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                dynamic_import = (
                    (node.func.attr == "import_module"
                     and node.func.value.id in importlib_aliases)
                    or (node.func.attr == "__import__"
                        and node.func.value.id in builtins_aliases)
                )
            if dynamic_import:
                target = node.args[0].value if (
                    node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ) else None
                if target is None:
                    errors.append(
                        "release provider action verifier has an unresolved dynamic import"
                    )
                elif target.startswith(".") or resolves_beside_source(target):
                    errors.append(
                        f"release provider action verifier dynamically imports local Python "
                        f"module {target}"
                    )
    return sorted(set(errors))


def parse_generic_verifier_command(command, cwd):
    """Accept only trusted Python directly executing one regular verifier source file."""
    command = str(command or "").strip()
    command_sha256 = hashlib.sha256(command.encode("utf-8", "replace")).hexdigest()
    binding = {
        "kind": "python_file",
        "argv": [],
        "interpreter_path": "",
        "interpreter_sha256": "",
        "path": "",
        "resolved_path": "",
        "extra_python_sources": [],
        "local_python_import_errors": [],
        "source_bytes": b"",
        "isolated_argv": [],
        "source_sha256": command_sha256,
        "command_sha256": command_sha256,
        "error": "generic_verifier_command_unsupported",
    }
    try:
        tokens = shlex.split(command)
    except ValueError:
        binding["error"] = "generic_verifier_command_invalid_quoting"
        return binding
    if not tokens or re.search(r"[;&|<>`$()\r\n]", command):
        binding["error"] = "generic_verifier_shell_composition_unsupported"
        return binding

    supplied_interpreter = Path(tokens[0]).expanduser()
    if not supplied_interpreter.is_absolute():
        located = shutil.which(tokens[0])
        supplied_interpreter = Path(located) if located else supplied_interpreter
    try:
        trusted = supplied_interpreter.is_file() and os.path.samefile(
            supplied_interpreter, sys.executable
        )
    except OSError:
        trusted = False
    trusted_interpreter = Path(sys.executable).resolve()
    if (not trusted or trusted_interpreter.is_symlink()
            or not trusted_interpreter.is_file()):
        binding["error"] = "generic_verifier_interpreter_untrusted"
        return binding

    index = 1
    if index < len(tokens) and tokens[index] in _GENERIC_PYTHON_FLAGS:
        index += 1
    if index >= len(tokens) or tokens[index].startswith("-") or not tokens[index].endswith(".py"):
        binding["error"] = "generic_verifier_python_form_unsupported"
        return binding

    source = Path(tokens[index]).expanduser()
    if not source.is_absolute():
        source = Path(cwd) / source
    # Keep the lexical file location. Resolving it would erase a later symlink replacement and
    # make the read-time freshness check follow the attacker's target instead of failing closed.
    source = Path(os.path.abspath(source))
    extra_python_sources = []
    for raw_arg in tokens[index + 1:]:
        candidate_values = [raw_arg]
        if "=" in raw_arg:
            candidate_values.append(raw_arg.split("=", 1)[1])
        for candidate_raw in candidate_values:
            if not candidate_raw:
                continue
            candidate = Path(candidate_raw).expanduser()
            if not candidate.is_absolute():
                candidate = Path(cwd) / candidate
            try:
                resolved_candidate = candidate.resolve(strict=True)
            except (OSError, ValueError):
                continue
            if (resolved_candidate.is_file()
                    and (candidate.suffix.lower() == ".py"
                         or resolved_candidate.suffix.lower() == ".py")):
                extra_python_sources.append(str(resolved_candidate))
    binding.update({
        "interpreter_path": str(trusted_interpreter),
        "interpreter_sha256": sha256_file(trusted_interpreter),
        "path": str(source),
        "extra_python_sources": sorted(set(extra_python_sources)),
        "source_sha256": "",
        "error": "",
    })
    if not binding["interpreter_sha256"]:
        binding["error"] = "generic_verifier_interpreter_unreadable"
    if source.is_symlink():
        binding["error"] = "verifier_source_symlink"
    else:
        try:
            resolved_source = source.resolve(strict=True)
        except OSError:
            resolved_source = None
        if (resolved_source is None or resolved_source.is_symlink()
                or not resolved_source.is_file()):
            binding["error"] = "verifier_source_missing_or_not_regular"
        else:
            binding["resolved_path"] = str(resolved_source)
            try:
                source_bytes = resolved_source.read_bytes()
            except OSError:
                source_bytes = None
            if source_bytes is None:
                binding["error"] = "verifier_source_unreadable"
            else:
                binding["source_bytes"] = source_bytes
                binding["local_python_import_errors"] = (
                    release_provider_action_local_import_errors(
                        source_bytes, resolved_source
                    )
                )
                binding["argv"] = [
                    str(trusted_interpreter), "-I", "-B", "-S", "-c",
                    _GENERIC_VERIFIER_SNAPSHOT_LOADER, str(resolved_source),
                    *tokens[index + 1:],
                ]
                binding["isolated_argv"] = [
                    str(trusted_interpreter), "-I", "-B", "-S", "-c",
                    _PROVIDER_ACTION_VERIFIER_SNAPSHOT_LOADER, str(resolved_source),
                    str(supplied_interpreter),
                    *tokens[index + 1:],
                ]
                binding["source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
    return binding


def run_generic_verifier_snapshot(binding, cwd, timeout=120, isolate_source_dir=False):
    """Execute the exact verifier bytes captured by ``parse_generic_verifier_command``.

    The trusted interpreter receives the immutable source snapshot on stdin. Both loaders restore
    direct-script ``__file__``, ``sys.argv``, and the requested cwd. Provider actions use the
    isolated loader, which leaves the verifier directory off ``sys.path``.
    """
    source = binding.get("source_bytes") if isinstance(binding, dict) else None
    argv_key = "isolated_argv" if isolate_source_dir else "argv"
    if (not isinstance(source, bytes)
            or hashlib.sha256(source).hexdigest() != binding.get("source_sha256")
            or binding.get("error") or not binding.get(argv_key)):
        return 1, "", 0, ""
    try:
        clean_env = {
            key: value for key, value in os.environ.items()
            if not (
                key.upper().startswith("PYTHON")
                or key == "__PYVENV_LAUNCHER__"
            )
        }
        proc = subprocess.run(
            binding[argv_key], cwd=cwd or None, input=source,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, shell=False,
            env=clean_env,
        )
        stdout = (proc.stdout or b"").decode("utf-8", "replace")
        stdout_bytes = stdout.encode("utf-8", "replace")
        return proc.returncode, hashlib.sha256(stdout_bytes).hexdigest(), len(stdout_bytes), stdout
    except Exception:
        return 1, "", 0, ""


def generic_verifier_source_is_current(proof, binding_cache=None):
    """Revalidate a generic verifier receipt against current command and source bytes.

    Proof rows created before source binding have no ``verifier_source_kind`` and remain readable.
    Newly recorded proofs must be normalized direct Python commands. Unsupported commands cannot
    prove; historical rows without a source-kind field retain their legacy read behavior.
    """
    kind = str((proof or {}).get("verifier_source_kind") or "")
    if not kind:
        return True
    command = str((proof or {}).get("verify_command") or "").strip()
    command_digest = hashlib.sha256(command.encode("utf-8", "replace")).hexdigest()
    recorded_command_digest = str((proof or {}).get("verify_command_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", recorded_command_digest):
        return False
    if command_digest != recorded_command_digest:
        return False
    if kind != "python_file" or (proof or {}).get("verifier_source_error"):
        return False
    if (proof or {}).get("verify_error"):
        return False
    if (proof or {}).get("verifier_snapshot_stable") is not True:
        return False
    verify_cwd = str((proof or {}).get("project_path") or Path(
        str((proof or {}).get("evidence_path") or ".")
    ).parent)
    cache_key = (
        command,
        verify_cwd,
        str((proof or {}).get("verifier_source_path") or ""),
        str((proof or {}).get("verifier_source_target_path") or ""),
        str((proof or {}).get("verifier_interpreter_path") or ""),
    )
    # Parsing a large Python verifier dominates metric scans. Reuse only its matched binding;
    # the path, target, interpreter, and source hashes below are still checked for every proof.
    current_binding = binding_cache.get(cache_key) if binding_cache is not None else None
    if current_binding is None:
        current_binding = parse_generic_verifier_command(command, verify_cwd)
    if (current_binding.get("error")
            or current_binding.get("path") != (proof or {}).get("verifier_source_path")
            or current_binding.get("resolved_path")
            != (proof or {}).get("verifier_source_target_path")
            or current_binding.get("interpreter_path")
            != (proof or {}).get("verifier_interpreter_path")):
        return False
    if binding_cache is not None:
        binding_cache[cache_key] = current_binding
    interpreter_raw = str((proof or {}).get("verifier_interpreter_path") or "")
    interpreter_digest = str((proof or {}).get("verifier_interpreter_sha256") or "")
    if not interpreter_raw or not re.fullmatch(r"[0-9a-f]{64}", interpreter_digest):
        return False
    interpreter = Path(interpreter_raw)
    trusted = Path(sys.executable).resolve()
    try:
        if (not interpreter.is_absolute() or interpreter.is_symlink() or not interpreter.is_file()
                or not os.path.samefile(interpreter, trusted)
                or sha256_file(interpreter) != interpreter_digest):
            return False
    except OSError:
        return False
    source_raw = str((proof or {}).get("verifier_source_path") or "")
    source_target_raw = str((proof or {}).get("verifier_source_target_path") or "")
    expected = str((proof or {}).get("verifier_source_sha256") or "")
    if (not source_raw or not source_target_raw
            or not re.fullmatch(r"[0-9a-f]{64}", expected)):
        return False
    if ((proof or {}).get("verifier_post_source_sha256") != expected
            or (proof or {}).get("verifier_post_interpreter_sha256") != interpreter_digest):
        return False
    source, source_target = Path(source_raw), Path(source_target_raw)
    if (not source.is_absolute() or source.is_symlink()
            or not source_target.is_absolute() or source_target.is_symlink()
            or not source_target.is_file()):
        return False
    try:
        if source.resolve(strict=True) != source_target:
            return False
    except OSError:
        return False
    return sha256_file(source_target) == expected


def generic_verifier_snapshot_is_stable(binding):
    """Rehash interpreter and source after verifier plus canary execution."""
    if not binding or binding.get("error"):
        return False
    interpreter = Path(binding.get("interpreter_path") or ".")
    source = Path(binding.get("path") or ".")
    target = Path(binding.get("resolved_path") or ".")
    try:
        return bool(
            sha256_file(interpreter) == binding.get("interpreter_sha256")
            and sha256_file(target) == binding.get("source_sha256")
            and not interpreter.is_symlink()
            and not source.is_symlink()
            and not target.is_symlink()
            and target.is_file()
            and source.resolve(strict=True) == target
        )
    except OSError:
        return False


# Trivial-verifier receipt (fast-follow dossier item 2). `--verify-cmd true` exits 0 but proves
# nothing — three cheap, recognizable signals expose a no-op verifier: a denylisted command source,
# a stdout transcript below a byte floor, and (the keystone) a canary mutant the verifier fails to
# catch. STDOUT_BYTE_FLOOR is deliberately tiny: `true`/`:`/`exit 0` emit zero bytes, so >=1 byte is
# the floor a no-op cannot clear. (reproducible-builds.org recognizable-no-op; OWASP CICD-SEC-9.)
STDOUT_BYTE_FLOOR = 1


def verifier_command_is_trivial(command):
    """A verifier command that cannot prove anything: it exits 0 without exercising the artifact.
    Denylist of no-ops — true, :, exit 0, echo ... — plus empty. The denylist + the source hash is
    the recognizable-no-op check; the canary mutant is the stronger, behavior-based signal."""
    norm = (command or "").strip()
    if not norm:
        return True
    low = norm.lower()
    if low in ("true", ":", "exit 0", "/bin/true", "/usr/bin/true"):
        return True
    first = low.split()[0] if low.split() else ""
    # An echo is only trivial when it IS the whole command. "echo start && pytest -q" runs a
    # real verifier after the preamble — flagging it trivial would silently skip the canary.
    return first == "echo" and not re.search(r"&&|\|\||;|\|", low)


# The canary re-runs the verifier on a mutant, so it doubles verifier runtime. Run it only for a
# verifier the cheap checks have NOT already proved trivial, and only when the first run was fast
# enough that doubling it is cheap — a multi-minute suite must never be silently run twice.
CANARY_MAX_VERIFY_SECONDS = 30


def _should_run_canary(already_trivial, first_run_secs):
    return (not already_trivial) and first_run_secs <= CANARY_MAX_VERIFY_SECONDS


def run_verifier_command(command, cwd, timeout=120):
    """Re-execute an operator-supplied verifier command; return (exit_code, stdout_sha256,
    stdout_bytes, stdout). The command comes from the operator/agent at the CLI — the same trust boundary as
    running it in their own shell — so shell=True is acceptable; it is never fed untrusted input.
    Fail-closed: a command we cannot run returns a non-zero code, so it cannot prove."""
    try:
        proc = subprocess.run(command, shell=True, cwd=cwd or None, capture_output=True,
                              text=True, timeout=timeout)
        stdout_bytes = (proc.stdout or "").encode("utf-8", "replace")
        return proc.returncode, hashlib.sha256(stdout_bytes).hexdigest(), len(stdout_bytes), proc.stdout or ""
    except Exception:
        return 1, "", 0, ""


def _git_diff_text(cwd, extra):
    try:
        proc = subprocess.run(["git", "-C", str(cwd), "diff", "--unified=0", "--no-color"] + extra,
                              capture_output=True, text=True, timeout=30)
        return proc.stdout if proc.returncode == 0 else ""
    except Exception:
        return ""


def _git_repo_root(cwd):
    """Absolute path of the git work-tree root for cwd, or '' if cwd is not in a repo. Diff paths are
    repo-root-relative, so a changed file must be resolved against this — not cwd, which may be a
    subdirectory (joining a repo-root-relative path to a subdir points at the wrong file)."""
    try:
        proc = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, timeout=30)
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except Exception:
        return ""


def _changed_line_target(cwd, allowed_files=None):
    """A (relative-path, 1-based new-file line number) of a changed line in cwd's git tree — working
    tree, then staged, then last commit. `allowed_files` restricts selection to known-relevant
    repository-relative paths; without it this retains the legacy first-target behavior for callers
    that need to inspect the diff. Returns None when there is no applicable mutable changed line."""
    for extra in ([], ["--cached"], ["HEAD~1", "HEAD"]):
        diff = _git_diff_text(cwd, extra)
        if not diff:
            continue
        rel_file, new_lineno = None, 0
        for line in diff.splitlines():
            if line.startswith("+++ b/"):
                rel_file = line[6:]
            elif line.startswith("@@"):
                m = re.search(r"\+(\d+)", line)
                new_lineno = int(m.group(1)) if m else 0
            elif line.startswith("+") and not line.startswith("+++"):
                if (rel_file and (allowed_files is None or rel_file in allowed_files)
                        and any(c.isalnum() for c in line[1:])):
                    return rel_file, new_lineno
                new_lineno += 1
            elif line.startswith(" "):
                new_lineno += 1
            # '-' (removed) lines do not advance the new-file counter
    return None


def _canary_unavailable(reason):
    return {
        "canary_target": None,
        "canary_target_source": "unavailable",
        "canary_target_reason": reason,
        "line": 0,
    }


def _resolve_canary_file(cwd, raw_path):
    """Return a safe repo-relative file name for a user or verifier path, never an absolute path.

    Relative paths are interpreted from the verification cwd. The canary itself later resolves the
    returned value from the git root, so the receipt and the mutation share the same containment
    boundary even when the verifier runs in a subdirectory.
    """
    root = _git_repo_root(cwd)
    if not root:
        return None, "no_git_worktree"
    try:
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = Path(cwd) / candidate
        if candidate.is_symlink() or not candidate.is_file():
            return None, "not_regular_file"
        root_real = os.path.realpath(root)
        candidate_real = os.path.realpath(candidate)
        if os.path.commonpath([root_real, candidate_real]) != root_real:
            return None, "outside_verification_checkout"
        relative = os.path.relpath(candidate_real, root_real)
        if relative == "." or relative == ".." or relative.startswith(f"..{os.sep}"):
            return None, "outside_verification_checkout"
        return relative.replace(os.sep, "/"), ""
    except (OSError, ValueError):
        return None, "unresolvable_target"


def select_canary_target(verify_cmd, cwd, canary_target=None):
    """Select one changed, regular, in-repository file relevant to the verifier.

    Automatic selection examines only direct shell tokens that name an existing file and refuses to
    fall back to arbitrary dirty worktree files. Explicit input is normalized before persistence and
    must still name a changed mutable line. The returned dictionary contains only a repo-relative
    target plus stable provenance; raw command tokens and absolute inputs never leave this helper.
    """
    if canary_target:
        rel_file, reason = _resolve_canary_file(cwd, canary_target)
        if not rel_file:
            return _canary_unavailable(f"explicit_target_{reason}")
        target = _changed_line_target(cwd, {rel_file})
        if not target:
            return _canary_unavailable("explicit_target_not_changed_regular_file")
        return {
            "canary_target": rel_file,
            "canary_target_source": "explicit",
            "canary_target_reason": "explicit_changed_regular_file",
            "line": target[1],
        }

    try:
        tokens = shlex.split(verify_cmd or "")
    except ValueError:
        tokens = []
    for token in reversed(tokens):
        if not token or token.startswith("-") or token in {"|", "||", "&&", ";"} or "=" in token:
            continue
        rel_file, _reason = _resolve_canary_file(cwd, token)
        if not rel_file:
            continue
        target = _changed_line_target(cwd, {rel_file})
        if target:
            return {
                "canary_target": rel_file,
                "canary_target_source": "verifier_reference",
                "canary_target_reason": "verifier_named_changed_file",
                "line": target[1],
            }
    return _canary_unavailable("no_relevant_changed_file")


def _flip_one_byte(line):
    """Change the first alnum character in a line to a guaranteed-different one; keep the newline."""
    for i, ch in enumerate(line):
        if ch.isdigit():
            return line[:i] + ("9" if ch != "9" else "8") + line[i + 1:], True
        if ch.isalpha():
            return line[:i] + ("X" if ch.lower() != "x" else "Y") + line[i + 1:], True
    return line, False


def _atomic_replace_bytes(path, data):
    """Write bytes to path atomically — same-directory temp file + os.replace — so a failed or
    interrupted write can never leave the file truncated, partial, or half-restored."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".canary-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        # os.replace swaps the inode, and mkstemp files are 0600 — carry the target's
        # permission bits over so a canary pass never strips a script's executable bit.
        try:
            os.chmod(tmp, os.stat(str(path)).st_mode & 0o7777)
        except OSError:
            pass
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def run_canary_mutant(verify_cmd, cwd, timeout=120, canary_target=None, selection=None,
                      verifier_argv=None, generic_binding=None):
    """Keystone anti-gaming check: flip one byte in a changed line, re-run the verifier, restore the
    file. Returns True if the verifier now FAILS (it actually exercised the change), False if it
    still passes (a no-op), or None if no canary could be run. The original bytes are ALWAYS restored
    in a finally — a proof-recording step must never leave the working tree mutated.

    Safety: target selection must identify a relevant changed regular file inside the verification
    checkout. The canary never falls back to an arbitrary dirty path, follows a symlink, or writes
    outside the git root."""
    selection = selection or select_canary_target(verify_cmd, cwd, canary_target)
    rel_file = selection.get("canary_target")
    lineno = selection.get("line", 0)
    if not rel_file or not lineno:
        return None
    base = _git_repo_root(cwd)
    if not base:
        return None
    path = Path(base) / rel_file
    try:
        base_real = os.path.realpath(base)
        if path.is_symlink() or not path.is_file():
            return None
        if os.path.commonpath([base_real, os.path.realpath(path)]) != base_real:
            return None  # path escapes the repo root
        original = path.read_bytes()
        text = original.decode("utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        return None  # missing, binary, or unresolvable -> skip
    lines = text.splitlines(keepends=True)
    if lineno < 1 or lineno > len(lines):
        return None
    mutated_line, ok = _flip_one_byte(lines[lineno - 1])
    if not ok:
        return None
    lines[lineno - 1] = mutated_line
    mutated = "".join(lines).encode("utf-8")
    if mutated == original:
        return None
    try:
        _atomic_replace_bytes(path, mutated)
        if generic_binding:
            exit_code, _, _, _ = run_generic_verifier_snapshot(
                generic_binding, cwd, timeout=timeout
            )
        elif verifier_argv:
            exit_code, _, _, _ = run_observability_verifier_argv(
                verifier_argv, cwd, timeout=timeout
            )
        else:
            exit_code, _, _, _ = run_verifier_command(verify_cmd, cwd, timeout=timeout)
        return exit_code != 0
    finally:
        _atomic_replace_bytes(path, original)


def resolve_project_dir(raw, projects_root=None):
    """Resolve a project value to a real directory: the path itself when it exists, else a
    projects-root join. Work items created via `work-start --project koho` stored the bare NAME,
    which subprocess.run rejects as a cwd — the join recovers the actual project directory.
    Falls back to the expanded raw value (preserving what was asked for in records); verifier
    execution separately gates on is_dir() and records cwd_invalid."""
    raw = str(raw or "").strip()
    if not raw:
        return ""
    p = Path(raw).expanduser()
    if p.exists():
        return str(p.resolve())
    candidate = Path(projects_root or DEFAULT_PROJECTS_ROOT).expanduser() / raw
    if candidate.exists():
        return str(candidate.resolve())
    # Owner-family nesting (FILESYSTEM-PROTOCOL §1.2): the projects root is flat
    # EXCEPT owner families (koho/, prettyfly/, willys/, ...), nested exactly one
    # level. A work item created as `--project consultops-live` stored the bare
    # name of a repo living at koho/consultops-live; the flat join above missed
    # it, the verifier cwd came back invalid, and every proof for a nested
    # project silently stayed logged_unverified (found 2026-08-10 on the
    # clm-pipeline-integrity outcome: three passing live verifiers, zero
    # credit). One level down, UNIQUE hit only — an ambiguous name must not
    # guess a cwd; meta directories (_archive, _views, .git) never match.
    root = Path(projects_root or DEFAULT_PROJECTS_ROOT).expanduser()
    if root.is_dir() and os.sep not in raw and not raw.startswith("."):
        hits = [
            d for d in root.glob(f"*/{raw}")
            if d.is_dir()
            and not d.parent.name.startswith(("_", "."))
        ]
        if len(hits) == 1:
            return str(hits[0].resolve())
    return str(p)


def build_proof_record(args, work_item=None, run_id="", measurement_id_value="", projects_root=None,
                       paths=None, observability_contract_root=None):
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
    if (args.pathway or "") == "observability" and not work_item:
        return None, finding(
            "proof-add-unlinked-observability-work-id",
            "proof-registry",
            "warn",
            f"Observability proof refused for unknown work_id {args.work_id or '<missing>'}.",
            [line_evidence((paths.work_items_path if paths else "<work-items>"),
                           source=args.work_id or "<missing>")],
            "Run work-start first and bind the proof to that canonical work item.",
            "static",
            "high",
        )
    proof_type = args.proof_type or "artifact"
    release_provider_action_contract = (
        (args.pathway or "") == "release"
        and (args.kind or "") == RELEASE_PROVIDER_ACTION_KIND
    )
    template_check = check_verifier_template(args.pathway or "", safe_read_text(evidence_path, max_bytes=64_000))
    cli_project_path = resolve_project_dir(getattr(args, "project", None), projects_root)
    project_path = cli_project_path
    project_name = Path(project_path).name if project_path else ""
    project_context_mismatch = False
    if work_item:
        work_project_path = resolve_project_dir(work_item.get("project", ""), projects_root)
        if cli_project_path and work_project_path:
            try:
                project_context_mismatch = not os.path.samefile(cli_project_path, work_project_path)
            except OSError:
                project_context_mismatch = True
        project_path = work_project_path or project_path
        project_name = work_item.get("project_name", project_name)
    proof_context = {
        "work_id": args.work_id or "",
        "recommendation_id": args.recommendation_id or "",
        "project": project_name,
        "target_project": project_path,
    }
    observability_contract_state = (
        resolve_observability_contract(
            project_path, projects_root, observability_contract_root)
        if (args.pathway or "") == "observability" and work_item
        else _observability_contract_state(
            {}, errors=["observability_contract_not_registered"])
        if (args.pathway or "") == "observability"
        else _OBSERVABILITY_DEFAULT_STATE
    )
    proof_id = proof_id_for(
        evidence_path, args.work_id or "", args.pathway or "", proof_type,
        args.recommendation_id or "")
    # Approval peek (no consumption yet): a production release receipt only validates when a
    # live single-use ticket — or this same proof's earlier consumption — is bound to the exact
    # companion digest. Consumption itself waits until every other release gate has passed, so a
    # failing verifier cannot burn Alex's ticket.
    release_approval_subject_value = None
    release_approval_available = False
    if (args.pathway or "") == "release" and paths is not None:
        _primary = Path(evidence_path).expanduser()
        _candidate = _primary if _primary.suffix.lower() == ".json" else _primary.with_suffix(".json")
        _peek_sha = ""
        if _candidate.is_file() and not _candidate.is_symlink():
            _peek_sha = sha256_file(_candidate)
        if _peek_sha:
            release_approval_subject_value = release_approval_subject(
                args.work_id or "", project_name, _peek_sha)
            _peek_digest = approval_subject_digest(release_approval_subject_value)
            _peek_events = approval_events_for(paths)
            if approval_store_is_protected(paths):
                _prior, _refusal = prebound_approval_for_consumer(
                    _peek_events, _peek_digest, proof_id
                )
                release_approval_available = _prior is not None
            else:
                _active, _refusal = find_active_approval(_peek_events, _peek_digest)
                _prior = latest_approval_event(_peek_events, _peek_digest, "consumed")
                release_approval_available = _active is not None or (
                    _prior is not None and _prior.get("consumed_by") == proof_id)
    release_receipt = (
        release_provider_action_from_evidence(evidence_path)
        if release_provider_action_contract
        else release_receipt_from_evidence(
            evidence_path, proof_context, now=utc_now(),
            production_approval=release_approval_available)
        if (args.pathway or "") == "release"
        else {
            "receipt": {}, "receipt_path": "", "receipt_sha256": "", "credit_scope": "",
            "errors": [], "artifact_sha256": {},
        }
    )
    if release_provider_action_contract:
        template_check = {
            "valid": not release_receipt["errors"],
            "template_id": "release-provider-action-v1",
            "missing": list(release_receipt["errors"]),
        }
    elif (
        (args.pathway or "") == "release"
        and Path(evidence_path).suffix.lower() == ".json"
        and release_receipt["credit_scope"] == "production"
        and not release_receipt["errors"]
    ):
        # A fully valid typed production receipt is the closed release template. This keeps the
        # final proof bound to the exact JSON bytes Alex approved instead of requiring unrelated
        # Markdown headings beside the receipt.
        template_check = {
            "valid": True,
            "template_id": "release-production-receipt-v1",
            "missing": [],
        }
    observability_receipt = (
        observability_receipt_from_evidence(
            evidence_path, proof_context, now=utc_now(),
            contract_state=observability_contract_state)
        if (args.pathway or "") == "observability"
        else {
            "receipt": {}, "receipt_path": "", "receipt_sha256": "", "credit_scope": "",
            "outcome": "", "errors": [], "artifact_sha256": {}, "artifact_paths": {},
            "receipt_kind": "",
        }
    )
    # Keystone: classify HOW the artifact was verified. `executed` = a re-run command (record its
    # exit code + stdout hash); `signed` = a named human reviewer over a hashed artifact; otherwise
    # `attested` = a bare --verified-by string, which is a claim, not a verification.
    reviewer = (getattr(args, "reviewer", None) or "").strip()
    verify_cmd = getattr(args, "verify_cmd", None)
    artifact_sha256 = sha256_file(evidence_path)
    verifier_strength, exit_code, verify_stdout_sha256, verify_command = "attested", None, "", ""
    verify_stdout = ""
    verify_stdout_bytes, verifier_source_sha256 = 0, ""
    verify_command_sha256 = ""
    verifier_source_kind, verifier_source_path, verifier_source_target_path = "", "", ""
    verifier_source_error = ""
    verifier_interpreter_path, verifier_interpreter_sha256 = "", ""
    verifier_post_source_sha256, verifier_post_interpreter_sha256 = "", ""
    verifier_snapshot_stable = True
    generic_binding = {}
    canary_mutant_failed, trivial_verifier = None, False
    canary_target, canary_target_source = None, "unavailable"
    canary_target_reason = "not_executed"
    observability_artifact_canary_results = {}
    observability_artifact_restoration_sha256 = {}
    observability_artifact_canary_errors = []
    observability_executed_verifier_sha256 = ""
    observability_post_verifier_sha256 = ""
    verify_error = ""
    verify_cwd = project_path or str(Path(evidence_path).parent)
    if verify_cmd:
        verifier_strength, verify_command = "executed", verify_cmd
        verify_command_sha256 = hashlib.sha256(
            verify_cmd.strip().encode("utf-8", "replace")
        ).hexdigest()
        verifier_source_sha256 = verify_command_sha256
        if (release_provider_action_contract
                or (args.pathway or "") not in {"release", "observability"}):
            generic_binding = parse_generic_verifier_command(verify_cmd, verify_cwd)
            verifier_source_kind = generic_binding["kind"]
            verifier_source_path = generic_binding["path"]
            verifier_source_target_path = generic_binding["resolved_path"]
            verifier_source_sha256 = generic_binding["source_sha256"]
            verifier_source_error = generic_binding["error"]
            verifier_interpreter_path = generic_binding["interpreter_path"]
            verifier_interpreter_sha256 = generic_binding["interpreter_sha256"]
            if release_provider_action_contract:
                authorized_source_sha256 = release_receipt["receipt"].get(
                    "verifier_source_sha256"
                )
                source_binding_error = ""
                if release_receipt["errors"]:
                    source_binding_error = (
                        "release_provider_action_authorization_invalid"
                    )
                elif generic_binding.get("extra_python_sources"):
                    source_binding_error = (
                        "release_provider_action_extra_verifier_source"
                    )
                    release_receipt = {
                        **release_receipt,
                        "errors": list(release_receipt["errors"]) + [
                            "release provider action command includes an extra existing "
                            "Python source"
                        ],
                    }
                    template_check = {
                        "valid": False,
                        "template_id": "release-provider-action-v1",
                        "missing": list(release_receipt["errors"]),
                    }
                elif generic_binding.get("local_python_import_errors"):
                    source_binding_error = (
                        "release_provider_action_local_verifier_import"
                    )
                    release_receipt = {
                        **release_receipt,
                        "errors": list(release_receipt["errors"]) + list(
                            generic_binding["local_python_import_errors"]
                        ),
                    }
                    template_check = {
                        "valid": False,
                        "template_id": "release-provider-action-v1",
                        "missing": list(release_receipt["errors"]),
                    }
                elif (not verifier_source_error
                      and verifier_source_sha256 != authorized_source_sha256):
                    source_binding_error = (
                        "release_provider_action_verifier_source_not_authorized"
                    )
                    release_receipt = {
                        **release_receipt,
                        "errors": list(release_receipt["errors"]) + [
                            "release provider action verifier_source_sha256 does not match "
                            "the captured verifier source"
                        ],
                    }
                    template_check = {
                        "valid": False,
                        "template_id": "release-provider-action-v1",
                        "missing": list(release_receipt["errors"]),
                    }
                if source_binding_error and not verifier_source_error:
                    verifier_source_error = source_binding_error
        if project_context_mismatch:
            verify_error = "project_context_mismatch"
            canary_target_reason = "project_context_mismatch"
        elif not Path(verify_cwd).is_dir():
            # A cwd that is not a real directory makes subprocess.run raise before the verifier
            # ever executes — the fail-closed wrapper would record that as exit 1 with an empty
            # transcript, indistinguishable from a genuinely failing verifier (and falsely flagged
            # trivial). Record cwd_invalid distinctly; exit_code stays None so it still cannot
            # flip a pathway to proved.
            verify_error = "cwd_invalid"
            canary_target_reason = "cwd_invalid"
        elif release_provider_action_contract:
            # Provider actions are already complete when logged. Re-run the fixed read-only
            # verifier once, then bind its exact four-marker output to the frozen authorization.
            # Do not mutate production evidence to manufacture an anti-gaming canary.
            if verifier_source_error:
                verify_error = "release_provider_action_verifier_not_executed"
                canary_target_reason = verifier_source_error
                verifier_snapshot_stable = False
            else:
                _t0 = time.monotonic()
                exit_code, verify_stdout_sha256, verify_stdout_bytes, verify_stdout = (
                    run_generic_verifier_snapshot(
                        generic_binding, verify_cwd, isolate_source_dir=True
                    )
                )
                first_run_secs = time.monotonic() - _t0
                trivial_verifier = verify_stdout_bytes < STDOUT_BYTE_FLOOR
                canary_target_reason = (
                    "provider_action_contract_bound"
                    if not trivial_verifier and first_run_secs <= CANARY_MAX_VERIFY_SECONDS
                    else "provider_action_verifier_trivial_or_slow"
                )
                verifier_post_source_sha256 = sha256_file(generic_binding["resolved_path"])
                verifier_post_interpreter_sha256 = sha256_file(
                    generic_binding["interpreter_path"]
                )
                verifier_snapshot_stable = (
                    generic_verifier_snapshot_is_stable(generic_binding)
                    and verifier_post_source_sha256 == verifier_source_sha256
                    and verifier_post_interpreter_sha256 == verifier_interpreter_sha256
                )
                if not verifier_snapshot_stable:
                    verifier_source_error = (
                        "release_provider_action_verifier_source_changed_during_execution"
                    )
        elif ((args.pathway or "") == "observability"
              and observability_receipt.get("receipt_kind") == "runtime"):
            command_check = parse_observability_verifier_command(
                verify_cmd, verify_cwd,
                observability_receipt["artifact_paths"].get("verifier_artifact", ""),
            )
            bound_verifier_sha256 = sha256_file(
                observability_receipt["artifact_paths"].get("verifier_artifact", ""))
            receipt_verifier_sha256 = str(
                (observability_receipt.get("receipt") or {}).get(
                    "verifier_source_sha256") or "")
            trust_errors = []
            if bound_verifier_sha256 != receipt_verifier_sha256:
                trust_errors.append(
                    "observability verifier source no longer matches the receipt digest")
            if (bound_verifier_sha256 not in
                    observability_contract_state["trusted_verifier_sha256"]):
                trust_errors.append(
                    "observability verifier source is not registered in the resolved contract")
            if (command_check["errors"] or trust_errors
                    or observability_receipt["outcome"] != "runtime"):
                command_errors = command_check["errors"] + trust_errors or [
                    "runtime observability receipt is invalid; verifier was not executed"
                ]
                observability_receipt = {
                    **observability_receipt,
                    "credit_scope": "",
                    "outcome": "",
                    "errors": list(observability_receipt["errors"]) + command_errors,
                }
                verify_error = "observability_verifier_not_executed"
                canary_target_reason = "observability_receipt_or_command_invalid"
            else:
                _t0 = time.monotonic()
                execution_candidate_sha256 = sha256_file(command_check["argv"][1])
                exit_code, verify_stdout_sha256, verify_stdout_bytes, verify_stdout = (
                    run_observability_verifier_argv(
                        command_check["argv"], verify_cwd,
                        expected_verifier_sha256=receipt_verifier_sha256,
                        trusted_sha256=observability_contract_state[
                            "trusted_verifier_sha256"],
                    )
                )
                if exit_code == 126:
                    verify_error = "observability_verifier_digest_changed_before_execution"
                else:
                    observability_executed_verifier_sha256 = execution_candidate_sha256
                first_run_secs = time.monotonic() - _t0
                trivial_verifier = verify_stdout_bytes < STDOUT_BYTE_FLOOR
                canary_target_reason = "observability_artifact_canaries_recorded_separately"
                if (exit_code == 0 and _should_run_canary(trivial_verifier, first_run_secs)):
                    artifact_canaries = run_observability_artifact_canaries(
                        command_check["argv"], verify_cwd,
                        observability_receipt["artifact_paths"],
                        observability_receipt["artifact_sha256"],
                        expected_verifier_sha256=receipt_verifier_sha256,
                        trusted_sha256=observability_contract_state[
                            "trusted_verifier_sha256"],
                    )
                    observability_artifact_canary_results = artifact_canaries["results"]
                    observability_artifact_restoration_sha256 = artifact_canaries[
                        "restoration_sha256"
                    ]
                    observability_artifact_canary_errors = artifact_canaries["errors"]
                    canary_mutant_failed = (
                        set(observability_artifact_canary_results)
                        == set(OBSERVABILITY_RECEIPT_ARTIFACT_FIELDS)
                        and all(value is True for value in observability_artifact_canary_results.values())
                        and not observability_artifact_canary_errors
                    )
                    if canary_mutant_failed is False:
                        trivial_verifier = True
                elif trivial_verifier:
                    canary_target_reason = "canary_skipped_trivial_verifier"
                else:
                    canary_target_reason = "canary_skipped_failed_or_slow_verifier"
        elif (args.pathway or "") not in {"release", "observability"}:
            if verifier_source_error:
                verify_error = "generic_verifier_not_executed"
                canary_target_reason = verifier_source_error
                verifier_snapshot_stable = False
            else:
                _t0 = time.monotonic()
                exit_code, verify_stdout_sha256, verify_stdout_bytes, verify_stdout = (
                    run_generic_verifier_snapshot(generic_binding, verify_cwd)
                )
                first_run_secs = time.monotonic() - _t0
                trivial_verifier = verify_stdout_bytes < STDOUT_BYTE_FLOOR
                if _should_run_canary(trivial_verifier, first_run_secs):
                    selection = select_canary_target(
                        verify_cmd, verify_cwd, getattr(args, "canary_target", None)
                    )
                    canary_target = selection["canary_target"]
                    canary_target_source = selection["canary_target_source"]
                    canary_target_reason = selection["canary_target_reason"]
                    canary_mutant_failed = run_canary_mutant(
                        verify_cmd, verify_cwd, selection=selection,
                        generic_binding=generic_binding,
                    )
                    if canary_mutant_failed is False:
                        trivial_verifier = True
                elif trivial_verifier:
                    canary_target_reason = "canary_skipped_trivial_verifier"
                else:
                    canary_target_reason = "canary_skipped_slow_verifier"
                verifier_post_source_sha256 = sha256_file(generic_binding["resolved_path"])
                verifier_post_interpreter_sha256 = sha256_file(
                    generic_binding["interpreter_path"]
                )
                verifier_snapshot_stable = (
                    generic_verifier_snapshot_is_stable(generic_binding)
                    and verifier_post_source_sha256 == verifier_source_sha256
                    and verifier_post_interpreter_sha256 == verifier_interpreter_sha256
                )
                if not verifier_snapshot_stable:
                    verifier_source_error = "generic_verifier_source_changed_during_execution"
        else:
            # Release and observability Tier-A verification retain their receipt-specific path
            # plus the existing git-aware canary behavior.
            _t0 = time.monotonic()
            exit_code, verify_stdout_sha256, verify_stdout_bytes, verify_stdout = run_verifier_command(
                verify_cmd, verify_cwd
            )
            first_run_secs = time.monotonic() - _t0
            # Receipt: a no-op verifier is recognizable by a denylisted source or an empty transcript.
            trivial_verifier = verifier_command_is_trivial(verify_cmd) or verify_stdout_bytes < STDOUT_BYTE_FLOOR
            # Keystone: flip a byte in a changed line and re-run — a real verifier now fails; one that
            # still passes ignored the change. Gated so a known-trivial or slow verifier isn't run twice.
            if _should_run_canary(trivial_verifier, first_run_secs):
                selection = select_canary_target(
                    verify_cmd, verify_cwd, getattr(args, "canary_target", None)
                )
                canary_target = selection["canary_target"]
                canary_target_source = selection["canary_target_source"]
                canary_target_reason = selection["canary_target_reason"]
                canary_mutant_failed = run_canary_mutant(verify_cmd, verify_cwd, selection=selection)
                if canary_mutant_failed is False:
                    trivial_verifier = True
            elif trivial_verifier:
                canary_target_reason = "canary_skipped_trivial_verifier"
            else:
                canary_target_reason = "canary_skipped_slow_verifier"
    elif reviewer:
        verifier_strength = "signed"
    release_snapshot_stable = True
    release_snapshot_errors = []
    release_post_artifact_sha256 = artifact_sha256
    release_post_receipt_sha256 = release_receipt["receipt_sha256"]
    release_post_release_artifact_sha256 = dict(release_receipt["artifact_sha256"])
    if release_provider_action_contract:
        # The authorization is the approval subject. It must stay byte-for-byte stable from the
        # approval peek through verifier completion and ticket consumption.
        release_post_artifact_sha256 = sha256_file(evidence_path)
        post_receipt = release_provider_action_from_evidence(evidence_path)
        release_post_receipt_sha256 = post_receipt["receipt_sha256"]
        if release_post_artifact_sha256 != artifact_sha256:
            release_snapshot_errors.append(
                "release provider action authorization changed during verifier execution"
            )
        if post_receipt["receipt_path"] != release_receipt["receipt_path"]:
            release_snapshot_errors.append(
                "release provider action authorization path changed during verifier execution"
            )
        if release_post_receipt_sha256 != release_receipt["receipt_sha256"]:
            release_snapshot_errors.append(
                "release provider action authorization digest changed during verifier execution"
            )
        if post_receipt["action"] != release_receipt["action"]:
            release_snapshot_errors.append(
                "release provider action changed during verifier execution"
            )
        if post_receipt["errors"]:
            release_snapshot_errors.append(
                "post-verification release provider action authorization is invalid: "
                + "; ".join(post_receipt["errors"][:3])
            )
        release_snapshot_stable = not release_snapshot_errors
        if release_snapshot_errors:
            release_receipt = {
                **release_receipt,
                "errors": list(release_receipt["errors"]) + release_snapshot_errors,
            }
    elif (args.pathway or "") == "release":
        # Release evidence is security state, not passive documentation. Snapshot the complete
        # evidence bundle before running an operator-controlled verifier, then re-read it only
        # after the verifier and canary have finished and the canary target has been restored.
        # Any byte change is a TOCTOU violation: the stdout may describe the pre-run state while
        # the ledger would otherwise retain a post-run receipt that says something different.
        release_post_artifact_sha256 = sha256_file(evidence_path)
        post_receipt = release_receipt_from_evidence(
            evidence_path, proof_context, now=utc_now(),
            production_approval=release_approval_available)
        release_post_receipt_sha256 = post_receipt["receipt_sha256"]
        release_post_release_artifact_sha256 = dict(post_receipt["artifact_sha256"])
        if release_post_artifact_sha256 != artifact_sha256:
            release_snapshot_errors.append("release evidence changed during verifier execution")
        if post_receipt["receipt_path"] != release_receipt["receipt_path"]:
            release_snapshot_errors.append("release receipt path changed during verifier execution")
        if release_post_receipt_sha256 != release_receipt["receipt_sha256"]:
            release_snapshot_errors.append("release receipt changed during verifier execution")
        if release_post_release_artifact_sha256 != release_receipt["artifact_sha256"]:
            release_snapshot_errors.append("release artifacts changed during verifier execution")
        if release_receipt["credit_scope"] == "production" and post_receipt["errors"]:
            release_snapshot_errors.append(
                "post-verification release receipt is invalid: "
                + "; ".join(post_receipt["errors"][:3])
            )
        if post_receipt["credit_scope"] != release_receipt["credit_scope"]:
            release_snapshot_errors.append("release credit scope changed during verifier execution")
        release_snapshot_stable = not release_snapshot_errors
        if release_snapshot_errors:
            release_receipt = {
                **release_receipt,
                "credit_scope": "",
                "errors": list(release_receipt["errors"]) + release_snapshot_errors,
            }
    release_binding = (
        release_verifier_binding(
            verify_stdout,
            release_receipt["receipt_sha256"],
            release_receipt.get("receipt"),
        )
        if (args.pathway or "") == "release" and not release_provider_action_contract
        else {"markers": {}, "errors": [], "bound": False}
    )
    release_provider_action_binding = (
        release_provider_action_verifier_binding(
            verify_stdout,
            release_receipt.get("action", ""),
            release_receipt["receipt_sha256"],
        )
        if release_provider_action_contract
        else {"markers": {}, "errors": [], "bound": False}
    )
    observability_snapshot_stable = True
    observability_snapshot_errors = []
    observability_post_artifact_sha256 = artifact_sha256
    observability_post_receipt_sha256 = observability_receipt["receipt_sha256"]
    observability_post_observability_artifact_sha256 = dict(
        observability_receipt["artifact_sha256"]
    )
    if (args.pathway or "") == "observability":
        # Tier A and Tier B both bind the operator artifact and JSON companion. Tier B additionally
        # snapshots every runtime artifact. Re-read only after the verifier and generic canary have
        # completed and the canary target has been restored.
        observability_post_artifact_sha256 = sha256_file(evidence_path)
        post_receipt = observability_receipt_from_evidence(evidence_path, {
            "work_id": args.work_id or "",
            "recommendation_id": args.recommendation_id or "",
            "project": project_name,
            "target_project": project_path,
        }, now=utc_now(), contract_state=observability_contract_state)
        observability_post_receipt_sha256 = post_receipt["receipt_sha256"]
        observability_post_observability_artifact_sha256 = dict(post_receipt["artifact_sha256"])
        if observability_post_artifact_sha256 != artifact_sha256:
            observability_snapshot_errors.append(
                "observability evidence changed during verifier execution"
            )
        if post_receipt["receipt_path"] != observability_receipt["receipt_path"]:
            observability_snapshot_errors.append(
                "observability receipt path changed during verifier execution"
            )
        if observability_post_receipt_sha256 != observability_receipt["receipt_sha256"]:
            observability_snapshot_errors.append(
                "observability receipt changed during verifier execution"
            )
        if (observability_post_observability_artifact_sha256
                != observability_receipt["artifact_sha256"]):
            observability_snapshot_errors.append(
                "observability artifacts changed during verifier execution"
            )
        if post_receipt["errors"]:
            observability_snapshot_errors.append(
                "post-verification observability receipt is invalid: "
                + "; ".join(post_receipt["errors"][:3])
            )
        if post_receipt["outcome"] != observability_receipt["outcome"]:
            observability_snapshot_errors.append(
                "observability outcome changed during verifier execution"
            )
        if post_receipt["credit_scope"] != observability_receipt["credit_scope"]:
            observability_snapshot_errors.append(
                "observability credit scope changed during verifier execution"
            )
        contract_path = Path(observability_contract_state["path"])
        contract_post_sha256 = (
            sha256_file(contract_path)
            if contract_path.is_file() and not contract_path.is_symlink()
            else ""
        )
        if contract_post_sha256 != observability_contract_state["sha256"]:
            observability_snapshot_errors.append(
                "observability contract changed during verifier execution"
            )
        verifier_path = Path(str(
            observability_receipt.get("artifact_paths", {}).get(
                "verifier_artifact", "")))
        observability_post_verifier_sha256 = (
            sha256_file(verifier_path)
            if verifier_path.is_file() and not verifier_path.is_symlink()
            else ""
        )
        if (observability_executed_verifier_sha256
                and observability_post_verifier_sha256
                != observability_executed_verifier_sha256):
            observability_snapshot_errors.append(
                "observability verifier changed during execution"
            )
        observability_snapshot_stable = not observability_snapshot_errors
        if observability_snapshot_errors:
            observability_receipt = {
                **observability_receipt,
                "credit_scope": "",
                "outcome": "",
                "errors": list(observability_receipt["errors"]) + observability_snapshot_errors,
            }
    observability_binding = (
        observability_verifier_binding(
            verify_stdout,
            observability_receipt["receipt_sha256"],
            observability_receipt["receipt"],
            observability_receipt["outcome"],
        )
        if (args.pathway or "") == "observability"
        else {"markers": {}, "errors": [], "bound": False, "mode": ""}
    )
    # Consume the release approval ticket LAST, only when every other release gate has already
    # passed, so a failed verifier, unstable snapshot, or unbound transcript never burns the
    # single-use ticket. A refusal here records why and the proof simply does not credit.
    release_approval_verified = False
    release_approval_digest = ""
    release_approval_consumed_id = ""
    release_approval_error = ""
    release_provider_action_verified = False
    if (args.pathway or "") == "release":
        if paths is None:
            release_approval_error = "approval_context_unavailable"
        elif release_approval_subject_value is None:
            release_approval_error = "no_release_receipt_companion"
        elif release_provider_action_contract and not (
            verifier_strength == "executed"
            and exit_code == 0
            and not trivial_verifier
            and not verifier_source_error
            and verifier_snapshot_stable
            and not release_receipt["errors"]
            and release_snapshot_stable
            and not release_snapshot_errors
            and release_provider_action_binding["bound"]
        ):
            release_approval_error = "release_provider_action_not_verified"
        elif not release_provider_action_contract and not (
            exit_code == 0
            and canary_mutant_failed is True
            and template_check.get("valid") is True
            and release_receipt["credit_scope"] == "production"
            and not release_receipt["errors"]
            and release_snapshot_stable
            and not release_snapshot_errors
            and release_binding["bound"]
        ):
            release_approval_error = "release_evidence_not_creditable"
        else:
            _consumed_event, _refusal = consume_approval(
                paths, release_approval_subject_value, proof_id)
            if _consumed_event is None:
                release_approval_error = f"approval_{_refusal}"
            else:
                release_approval_verified = True
                release_approval_digest = _consumed_event.get("subject_digest", "")
                release_approval_consumed_id = _consumed_event.get("consumption_id", "")
                release_provider_action_verified = release_provider_action_contract
    proof = {
        "proof_id": proof_id,
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
        "verify_command_sha256": verify_command_sha256,
        "verify_error": verify_error,
        "exit_code": exit_code,
        "verify_stdout_sha256": verify_stdout_sha256,
        "verify_stdout_bytes": verify_stdout_bytes,
        "verifier_source_sha256": verifier_source_sha256,
        "verifier_source_kind": verifier_source_kind,
        "verifier_source_path": verifier_source_path,
        "verifier_source_target_path": verifier_source_target_path,
        "verifier_source_error": verifier_source_error,
        "verifier_interpreter_path": verifier_interpreter_path,
        "verifier_interpreter_sha256": verifier_interpreter_sha256,
        "verifier_post_source_sha256": verifier_post_source_sha256,
        "verifier_post_interpreter_sha256": verifier_post_interpreter_sha256,
        "verifier_snapshot_stable": verifier_snapshot_stable,
        "canary_target": canary_target,
        "canary_target_source": canary_target_source,
        "canary_target_reason": canary_target_reason,
        "canary_mutant_failed": canary_mutant_failed,
        "trivial_verifier": trivial_verifier,
        "artifact_sha256": artifact_sha256,
        "template_check": template_check,
        "release_receipt": release_receipt["receipt"],
        "release_receipt_path": release_receipt["receipt_path"],
        "release_receipt_sha256": release_receipt["receipt_sha256"],
        "release_credit_scope": release_receipt["credit_scope"],
        "release_receipt_errors": release_receipt["errors"],
        "release_artifact_sha256": release_receipt["artifact_sha256"],
        "release_snapshot_stable": release_snapshot_stable,
        "release_snapshot_errors": release_snapshot_errors,
        "release_post_artifact_sha256": release_post_artifact_sha256,
        "release_post_receipt_sha256": release_post_receipt_sha256,
        "release_post_release_artifact_sha256": release_post_release_artifact_sha256,
        "release_verifier_markers": release_binding["markers"],
        "release_verifier_errors": release_binding["errors"],
        "release_verifier_bound": release_binding["bound"],
        "release_provider_action": release_receipt.get("action", "")
        if release_provider_action_contract else "",
        "release_provider_action_contract": release_provider_action_contract,
        "release_provider_action_verified": release_provider_action_verified,
        "release_provider_action_verifier_markers": release_provider_action_binding["markers"],
        "release_provider_action_verifier_errors": release_provider_action_binding["errors"],
        "release_provider_action_verifier_bound": release_provider_action_binding["bound"],
        "release_approval_verified": release_approval_verified,
        "release_approval_digest": release_approval_digest,
        "release_approval_consumed_id": release_approval_consumed_id,
        "release_approval_error": release_approval_error,
        "observability_receipt": observability_receipt["receipt"],
        "observability_contract_key": observability_contract_state["key"],
        "observability_project_key": observability_contract_state["project_key"],
        "observability_contract_path": observability_contract_state["path"],
        "observability_contract_schema_version": observability_contract_state["schema_version"],
        "observability_contract_sha256": observability_contract_state["sha256"],
        "observability_contract_post_sha256": (
            contract_post_sha256 if (args.pathway or "") == "observability" else ""),
        "observability_receipt_path": observability_receipt["receipt_path"],
        "observability_receipt_sha256": observability_receipt["receipt_sha256"],
        "observability_credit_scope": observability_receipt["credit_scope"],
        "observability_outcome": observability_receipt["outcome"],
        "observability_receipt_errors": observability_receipt["errors"],
        "observability_artifact_sha256": observability_receipt["artifact_sha256"],
        "observability_snapshot_stable": observability_snapshot_stable,
        "observability_snapshot_errors": observability_snapshot_errors,
        "observability_post_artifact_sha256": observability_post_artifact_sha256,
        "observability_post_receipt_sha256": observability_post_receipt_sha256,
        "observability_post_observability_artifact_sha256": (
            observability_post_observability_artifact_sha256
        ),
        "observability_verifier_markers": observability_binding["markers"],
        "observability_verifier_errors": observability_binding["errors"],
        "observability_verifier_bound": observability_binding["bound"],
        "observability_artifact_canary_results": observability_artifact_canary_results,
        "observability_artifact_restoration_sha256": (
            observability_artifact_restoration_sha256
        ),
        "observability_artifact_canary_errors": observability_artifact_canary_errors,
        "observability_executed_verifier_sha256": observability_executed_verifier_sha256,
        "observability_post_verifier_sha256": observability_post_verifier_sha256,
        "reviewer": reviewer,
        "recommendation_id": args.recommendation_id or "",
        "run_id": run_id,
        "measurement_id": measurement_id_value,
        "project": project_name,
        "project_path": project_path,
        "source": "operating-layer proof registry",
    }
    # A proof that will NOT credit must say so at log time, loudly. Before this,
    # work-log printed a clean summary while cwd_invalid / a failed canary /
    # a trivial transcript quietly parked the pathway in logged_unverified —
    # the caller had no signal until a later work-status archaeology dig
    # (2026-08-10: three re-log rounds before anyone saw cwd_invalid).
    if (verify_cmd and not proof_is_verified(
            proof, observability_contract_root=observability_contract_root)
            and not proof.get("release_provider_action_verified")):
        if verify_error == "cwd_invalid":
            reason = (
                f"the verifier never ran — cwd '{project_path or evidence_path}' is not a directory. "
                "Pass --project with the repo's real path, or fix the work item's project value."
            )
        elif verify_error == "project_context_mismatch":
            reason = (
                "the verifier never ran because --project resolves to a different checkout than "
                "the active work item. Use the canonical work-item project path."
            )
        elif exit_code not in (0, None):
            reason = f"the verifier ran and FAILED (exit {exit_code})."
        elif (proof.get("pathway") not in {"release", "observability"}
              and not generic_verifier_source_is_current(proof)):
            reason = (
                "the direct Python verifier source is missing, symlinked, unreadable, or no "
                "longer matches the source digest recorded in the proof receipt."
            )
        elif proof.get("canary_mutant_failed") is False:
            reason = (
                "the anti-gaming canary was not tripped — the verifier passed unchanged after a "
                "byte-flip in a file it names. Make the verifier's first line a load-bearing local "
                "assertion on a file it reads."
            )
        elif proof.get("template_check", {}).get("valid") is False:
            reason = "the evidence artifact does not satisfy the pathway verifier template."
        elif (proof.get("pathway") == "release"
              and proof.get("release_provider_action_contract") is True
              and proof.get("release_receipt_errors")):
            reason = "the provider-action authorization is invalid: " + "; ".join(
                proof.get("release_receipt_errors", [])[:3]
            )
        elif (proof.get("pathway") == "release"
              and proof.get("release_provider_action_contract") is True
              and proof.get("release_provider_action_verifier_errors")):
            reason = "the provider-action verifier output is invalid: " + "; ".join(
                proof.get("release_provider_action_verifier_errors", [])[:3]
            )
        elif (proof.get("pathway") == "release"
              and proof.get("release_provider_action_contract") is True
              and not proof.get("release_approval_verified")):
            reason = (
                "the provider action did not consume its exact single-use approval ticket "
                f"(refusal: {proof.get('release_approval_error') or 'not_consumed'})."
            )
        elif proof.get("pathway") == "release" and proof.get("release_receipt_errors"):
            reason = "the structured release receipt is not creditable: " + "; ".join(
                proof.get("release_receipt_errors", [])[:3]
            )
        elif proof.get("pathway") == "release" and proof.get("release_verifier_errors"):
            reason = "the release verifier output is not bound to a production receipt: " + "; ".join(
                proof.get("release_verifier_errors", [])[:3]
            )
        elif proof.get("pathway") == "release" and proof.get("canary_mutant_failed") is not True:
            reason = "release proof requires a successful anti-gaming verifier canary."
        elif proof.get("pathway") == "release" and not proof.get("release_approval_verified"):
            reason = (
                "production release credit requires a verified single-use human approval ticket "
                f"(refusal: {proof.get('release_approval_error') or 'not_consumed'}). Have Alex "
                "run `approval-issue --kind release-production-approval --work-id <id> "
                "--release-receipt <receipt.json> --reason \"...\"`, then re-log within its "
                "15-minute window."
            )
        elif proof.get("pathway") == "observability" and proof.get("observability_receipt_errors"):
            reason = "the structured observability receipt is not creditable: " + "; ".join(
                proof.get("observability_receipt_errors", [])[:3]
            )
        elif proof.get("pathway") == "observability" and proof.get("observability_verifier_errors"):
            reason = "the observability verifier output is not bound to its receipt: " + "; ".join(
                proof.get("observability_verifier_errors", [])[:3]
            )
        elif (proof.get("pathway") == "observability"
              and proof.get("observability_outcome") == "blocked_no_runtime"):
            reason = "the verified blocked_no_runtime contract is carry-forward evidence, not observability credit."
        elif (proof.get("pathway") == "observability"
              and not observability_bound_contract_is_current(proof)):
            reason = (
                "runtime observability requires the resolved project contract, its unchanged "
                "bound digest, and a verifier digest registered in that contract."
            )
        elif proof.get("pathway") == "observability" and proof.get("canary_mutant_failed") is not True:
            reason = "positive observability proof requires a successful anti-gaming verifier canary."
        elif proof.get("trivial_verifier"):
            reason = "the verifier looks trivial (denylisted command or near-empty transcript)."
        else:
            reason = "the executed verifier did not meet the crediting predicate."
        return proof, finding(
            "proof-logged-unverified",
            "proof-registry",
            "warn",
            f"Proof for pathway '{args.pathway}' is recorded but will NOT credit coverage: {reason}",
            [line_evidence(evidence_path or "<missing>")],
            "Fix the verifier or its cwd and re-log; a pathway only flips to proved on an executed, non-trivial, canary-honest exit-0 verifier.",
            "runtime",
            "high",
        )
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
    profiles_root = paths.projects_root / "agents" / "hermes" / "profiles"
    if profiles_root.is_dir() and not profiles_root.is_symlink():
        for profile in profiles_root.iterdir():
            manifest = profile / "manifest.json"
            # Active Hermes profiles are the readiness population. Keep the local
            # root boundary from the security review and require a regular manifest.
            if (profile.is_symlink() or not profile.is_dir() or profile.name.startswith(".")
                    or profile.name in PRUNE_DIRS or manifest.is_symlink() or not manifest.is_file()):
                continue
            sources.append(profile)
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
    day = local_day()
    return paths.operator_artifacts / f"{day}-operating-layer-report.md"


def dated_artifact_path(paths, suffix):
    day = local_day()
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


def newest_measurement_per_gate(measurements):
    """Collapse a measurement history to the current reading for each gate.

    The ledger is append-only, so re-measuring a gate adds a row rather than
    replacing one. Keyed on GATE alone, deliberately: the same gate is often
    re-measured under a different pathway, and keying on (pathway, gate) treats
    those as unrelated series. Measured 2026-07-26 against the live ledger — keying
    on (pathway, gate) freed exactly zero outcomes; gate alone freed the one that
    was genuinely superseded.

    Rows with no gate fall back to `kind`, then to their own id, so an unlabelled
    measurement is never silently merged into someone else's series.
    """
    newest = {}
    for measurement in measurements:
        key = (measurement.get("gate")
               or measurement.get("kind")
               or measurement.get("measurement_id")
               or id(measurement))
        current = newest.get(key)
        if current is None or str(measurement.get("timestamp") or "") > str(
                current.get("timestamp") or ""):
            newest[key] = measurement
    return list(newest.values())


def stale_measurements(measurements):
    """Gates whose CURRENT reading is past its freshness window.

    Only the newest row per gate is judged. Superseded history stays in the ledger
    and stops blocking — before this, a work item that had been re-measured and
    passed could never close, because the original row aged out and nothing retired
    it. `W-20260627` was fully verified at 7/7 coverage and permanently unclosable
    for exactly that reason.

    What this deliberately does NOT do is forgive dormancy. If the newest reading
    for a gate is itself stale, the gate is still stale. Measured the same day: 24
    of 31 blocked outcomes have a newest row older than 14 days — that is genuinely
    untouched work, and the flag is right about it. A change that frees those would
    be worse than the bug it fixes. `tests/test_measurement_staleness.py` pins both
    directions.
    """
    now = utc_now()
    stale = []
    for measurement in newest_measurement_per_gate(measurements):
        ts = parse_ts(measurement.get("timestamp"))
        stale_after = int(measurement.get("stale_after_days") or WORK_STALE_DAYS)
        if ts and (now - ts).days > stale_after:
            stale.append(measurement)
    return stale


def work_status_summary(paths, work_id, approval_events_override=None):
    records = load_work_records(paths)
    item = next((w for w in records["items"] if w.get("work_id") == work_id), None)
    runs = [r for r in records["runs"] if r.get("work_id") == work_id]
    measurements = [m for m in records["measurements"] if m.get("work_id") == work_id]
    controls = [c for c in records["controls"] if c.get("work_id") == work_id]
    open_controls = [c for c in controls if c.get("status", "open") != "resolved"]
    missing_evidence = [m for m in measurements if not m.get("evidence_id")]
    stale = stale_measurements(measurements)
    pathways_seen = sorted(set(r.get("pathway") for r in runs if r.get("pathway")), key=pathway_sort_key)
    proof_records = read_ndjson(paths.proofs_path)
    approval_events = (
        approval_events_override
        if approval_events_override is not None
        else approval_events_for(paths)
    )
    proved_pathway_map = proved_pathways_from_proofs(work_id, proof_records, approval_events)
    missing_core_pathways = [p for p in CORE_PATHWAYS if p not in pathways_seen]
    if item:
        profile = item.get("outcome_profile") or classify_outcome_profile(
            item.get("goal", ""), item.get("project_name", ""))
        overlays = item.get("risk_overlays")
        if overlays is None:
            overlays = detect_risk_overlays(
                item.get("goal", ""), item.get("project_name", ""), profile=profile)
        expected = compute_itinerary(item.get("tier", DEFAULT_ITINERARY_TIER), item.get("goal", ""), profile, overlays)
        item = dict(item)
        item["outcome_profile"] = profile
        item["risk_overlays"] = overlays
        item["itinerary"] = merge_itinerary(item.get("itinerary") or [], expected)
        # Persisted labels are caches, not authority. Any ledger-backed proved row reopens when
        # its current proof becomes stale or fails the current verifier. Legacy/manual proved
        # rows with no proof receipt retain their old behavior outside production-secure work.
        # Production-secure outcomes remain stricter: every unsupported proved row and every
        # historical free-text N/A row reopens.
        production_secure = production_secure_waiver_locked(item)
        item["itinerary"] = [dict(entry) for entry in item["itinerary"]]
        for entry in item["itinerary"]:
            pathway = entry.get("pathway")
            pathway_proofs = [
                proof for proof in proof_records
                if proof.get("work_id") == work_id and proof.get("pathway") == pathway
            ]
            proved_by = entry.get("proved_by_run") or ""
            recorded_receipt = any(
                proved_by and proved_by in (proof.get("run_id"), proof.get("proof_id"))
                for proof in pathway_proofs
            ) or (proved_by == "[REDACTED]" and bool(pathway_proofs))
            unsupported_proved = (
                entry.get("status") == "proved"
                and pathway not in proved_pathway_map
                # Release is always an approval-backed current-state claim. Unlike ordinary
                # legacy/manual coverage, a persisted release label cannot survive deletion of
                # the proof row that binds it to the authority ledger.
                and (production_secure or recorded_receipt or pathway == "release")
            )
            waived = waiver_corroborated(entry, item, approval_events)
            if (production_secure and entry.get("status") == "na" and not waived) or unsupported_proved:
                entry["status"] = "required"
                entry["proved_by_run"] = ""
    # Read-time credit: coverage must derive from the proof EVIDENCE, not only the persisted entry
    # status. A verified proof already in the ledger (recorded via proof-add or an earlier run)
    # flips its still-required pathway here, so coverage is retroactive and never stalls at
    # logged_unverified. Mutates the in-memory item only (no write); the write paths persist it.
    if item:
        apply_proof_coverage(item.get("itinerary") or [], proved_pathway_map)
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
            "proved": sorted(proved_pathway_map, key=pathway_sort_key),
            "missing_core": missing_core_pathways,
            "count": len(pathways_seen),
        },
        "missing_evidence": missing_evidence,
        "stale_measurements": stale,
        "open_controls": open_controls,
        "closeout_readiness": "ready" if ready else "not_ready",
        "warnings": work_warnings(item, runs, measurements, open_controls, stale, itinerary_open),
    }


def current_work_item_view(paths, item, summary=None, approval_events=None):
    """Project the effective status of a historically closed item without rewriting history.

    Only a consumed ticket whose removal is the difference between ready and not-ready may reopen
    a closed item as approval-invalidated.  An invalidated but unused ticket is audit history, not
    causal work state.
    """
    if not isinstance(item, dict) or item.get("status", "active") != "closed":
        return item, summary
    work_id = item.get("work_id")
    if not work_id:
        return item, summary
    events = approval_events if approval_events is not None else approval_events_for(paths)
    proof_records = read_ndjson(paths.proofs_path)
    persisted_release_proved = any(
        isinstance(entry, dict)
        and entry.get("pathway") == "release"
        and entry.get("status") == "proved"
        for entry in item.get("itinerary", [])
    )
    if not approval_events_valid(events):
        has_waiver_claim = any(
            isinstance(entry, dict)
            and bool(entry.get("waiver_digest") or entry.get("waiver_consumed_id"))
            for entry in item.get("itinerary", [])
        )
        has_release_claim = any(
            proof.get("work_id") == work_id
            and proof.get("pathway") == "release"
            and bool(
                proof.get("release_approval_digest")
                or proof.get("release_approval_consumed_id")
            )
            for proof in proof_records
        )
        current_summary = summary or work_status_summary(
            paths, work_id, approval_events_override=events
        )
        if current_summary.get("closeout_readiness") == "ready":
            return item, current_summary
        if not (
            has_waiver_claim
            or has_release_claim
            or persisted_release_proved
            or production_secure_waiver_locked(item)
        ):
            return item, current_summary
        current_view = dict(item)
        current_view.update({
            "persisted_status": "closed",
            "status": "active",
            "current_status": "active",
                "current_status_reason": (
                    "approval_ledger_invalid"
                    if has_waiver_claim or has_release_claim or persisted_release_proved
                    else "production_secure_not_ready"
                ),
        })
        current_summary = dict(current_summary)
        current_summary["work_item"] = current_view
        return current_view, current_summary

    # A release `proved` label is a cached projection of a currently corroborated proof, never
    # durable authority by itself. If the user-writable proof ledger loses that row, reopening must
    # not depend on finding approval fields in the now-missing row: otherwise deleting the claim
    # hides both the proof loss and any OS-ledger invalidation that followed it.
    current_release_proofs = [
        proof for proof in proof_records
        if proof.get("work_id") == work_id and proof.get("pathway") == "release"
    ]
    if persisted_release_proved and not any(
            proof_credits_pathway(proof, events) for proof in current_release_proofs):
        current_summary = summary or work_status_summary(
            paths, work_id, approval_events_override=events
        )
        referenced_proof_ids = {
            entry.get("proved_by_run")
            for entry in item.get("itinerary", [])
            if isinstance(entry, dict) and entry.get("pathway") == "release"
        }
        release_proof = next(
            (
                proof for proof in reversed(current_release_proofs)
                if proof.get("run_id") in referenced_proof_ids
                or proof.get("proof_id") in referenced_proof_ids
            ),
            current_release_proofs[-1] if current_release_proofs else None,
        )
        current_view = dict(item)
        current_view.update({
            "persisted_status": "closed",
            "status": "active",
            "current_status": "active",
            "current_status_reason": release_approval_failure_state(release_proof, events),
        })
        current_summary = dict(current_summary)
        current_summary["work_item"] = current_view
        return current_view, current_summary
    consumed_tickets = {
        event.get("ticket_id")
        for event in events
        if event.get("event") == "consumed" and event.get("work_id") == work_id
    }
    causal_ticket_ids = {
        event.get("ticket_id")
        for event in events
        if event.get("event") == "invalidated"
        and event.get("work_id") == work_id
        and event.get("ticket_id") in consumed_tickets
    }
    current_summary = summary
    if causal_ticket_ids:
        current_summary = current_summary or work_status_summary(
            paths, work_id, approval_events_override=events
        )
        if current_summary.get("closeout_readiness") != "ready":
            without_invalidations = ApprovalEvents([
                event for event in events
                if not (
                    event.get("event") == "invalidated"
                    and event.get("ticket_id") in causal_ticket_ids
                )
            ])
            counterfactual = work_status_summary(
                paths, work_id, approval_events_override=without_invalidations
            )
            if counterfactual.get("closeout_readiness") == "ready":
                current_view = dict(item)
                current_view.update({
                    "persisted_status": "closed",
                    "status": "active",
                    "current_status": "active",
                    "current_status_reason": "approval_invalidated",
                })
                current_summary = dict(current_summary)
                current_summary["work_item"] = current_view
                return current_view, current_summary

    def claim_was_explicitly_invalidated(digest, consumption_id):
        consumed = next(
            (
                event for event in events
                if event.get("event") == "consumed"
                and event.get("subject_digest") == digest
                and event.get("consumption_id") == consumption_id
            ),
            None,
        )
        return bool(
            consumed
            and approval_ticket_invalidated(events, consumed.get("ticket_id", ""))
        )

    project_name = item.get("project_name", "")
    has_uncorroborated_claim = any(
        isinstance(entry, dict)
        and bool(entry.get("waiver_digest") or entry.get("waiver_consumed_id"))
        and not waiver_corroborated(entry, item, events)
        and not claim_was_explicitly_invalidated(
            entry.get("waiver_digest"), entry.get("waiver_consumed_id")
        )
        for entry in item.get("itinerary", [])
    )
    if not has_uncorroborated_claim:
        has_uncorroborated_claim = any(
            proof.get("work_id") == work_id
            and bool(
                proof.get("release_approval_digest")
                or proof.get("release_approval_consumed_id")
            )
            and not release_approval_corroborated(proof, events)
            and not claim_was_explicitly_invalidated(
                proof.get("release_approval_digest"),
                proof.get("release_approval_consumed_id"),
            )
            for proof in proof_records
        )
    if not has_uncorroborated_claim:
        if not production_secure_waiver_locked(item):
            return item, current_summary
        current_summary = current_summary or work_status_summary(
            paths, work_id, approval_events_override=events
        )
        if current_summary.get("closeout_readiness") == "ready":
            return item, current_summary
        reason = "production_secure_not_ready"
    else:
        current_summary = current_summary or work_status_summary(
            paths, work_id, approval_events_override=events
        )
        if current_summary.get("closeout_readiness") == "ready":
            return item, current_summary
        reason = "approval_uncorroborated"
    current_view = dict(item)
    current_view.update({
        "persisted_status": "closed",
        "status": "active",
        "current_status": "active",
        "current_status_reason": reason,
    })
    current_summary = dict(current_summary)
    current_summary["work_item"] = current_view
    return current_view, current_summary


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
        if production_secure_waiver_locked(item):
            warnings.append(
                f"{len(itinerary_open)} production-secure pathways still need verified proof "
                "or a verified single-use waiver ticket (approval-issue --kind "
                "production-secure-waiver): " + ", ".join(itinerary_open) + "."
            )
        else:
            warnings.append(
                f"{len(itinerary_open)} required pathways still need proof or an explicit N/A: "
                + ", ".join(itinerary_open) + "."
            )
    return warnings


def build_daily_dashboard(paths):
    records = load_work_records(paths)
    work_items = sorted(records["items"], key=lambda w: w.get("updated_at", ""), reverse=True)
    approval_events = approval_events_for(paths)
    active = []
    invalidation_summaries = {}
    for item in work_items:
        current_view, summary = current_work_item_view(
            paths, item, approval_events=approval_events
        )
        if current_view.get("status", "active") == "closed":
            continue
        active.append(current_view)
        if summary is not None:
            invalidation_summaries[item.get("work_id")] = summary
    summaries = [
        invalidation_summaries.get(item.get("work_id"))
        or work_status_summary(paths, item.get("work_id"))
        for item in active[:25]
    ]
    stuck = [
        s for s in summaries
        if s["open_controls"] or s["stale_measurements"] or any("No pathway runs" in w for w in s["warnings"])
    ]
    queue = read_json_file(paths.improvement_queue_path, {"items": []})
    dashboard = {
        "generated_at": iso_now(),
        "active_work_items": active,
        "active_count": len(active),
        "closed_count": len(work_items) - len(active),
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
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=max(60, int(budget_sec * 8)))
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
    # Resolve a bare project NAME (`--project koho`) to its real directory here, at entry —
    # every downstream consumer (verify cwd, boundary checks, portfolio joins, stable_work_id)
    # treats this field as a path, and stable_work_id would otherwise hash it relative to the
    # invoking process's cwd, making the work_id unstable across invocation directories.
    project_path = resolve_project_dir(args.project, paths.projects_root)
    work_id = stable_work_id(project_path, args.goal)
    context = current_work_context(paths, project_path)
    existing = next((w for w in read_ndjson(paths.work_items_path) if w.get("work_id") == work_id), None)
    explicit_tier = getattr(args, "tier", None)
    existing_itin = (existing or {}).get("itinerary")
    project_name = Path(project_path).name
    scoped_findings = project_scoped_findings(paths, project_path, project_name) + project_local_findings(project_path)[0]
    contract = outcome_contract(args.goal, project_path, project_name, scoped_findings, explicit_tier=explicit_tier)
    if explicit_tier:
        # A tier was chosen → seed (or resize) the coverage itinerary. The /pathway skill
        # always passes a tier, so the coverage guarantee holds for every tracked outcome.
        tier = contract["tier"]
        next_itin = compute_itinerary(tier, args.goal, contract["outcome_profile"], contract["risk_overlays"])
        itinerary = merge_itinerary(existing_itin, next_itin) if existing_itin else next_itin
    elif existing_itin:
        # Re-START without a tier: preserve earned proof, but pull in newly detected profile/overlay
        # gates so old active work cannot close around a freshly visible risk.
        tier = (existing or {}).get("tier", DEFAULT_ITINERARY_TIER)
        next_itin = compute_itinerary(tier, args.goal, contract["outcome_profile"], contract["risk_overlays"])
        itinerary = merge_itinerary(existing_itin, next_itin)
    else:
        # No empty-itinerary work: default through the outcome profile so every tracked outcome
        # has a closeout spine even when a caller omits --tier.
        tier = (existing or {}).get("tier", contract["tier"]) or contract["tier"]
        itinerary = compute_itinerary(tier, args.goal, contract["outcome_profile"], contract["risk_overlays"])
    item = update_work_item(
        paths,
        work_id,
        status="active",
        mode="semi-automatic",
        project=project_path,
        project_name=project_name,
        goal=args.goal,
        context=context,
        tier=tier,
        outcome_profile=contract["outcome_profile"],
        risk_overlays=contract["risk_overlays"],
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
    waiver_consumption = None
    if args.na and production_secure_waiver_locked(item):
        refusal = "waiver_authority_not_configured"
        if PRODUCTION_SECURE_WAIVER_STATE == "CONFIGURED_AND_VERIFIED":
            refusal = "no_ticket"
            if args.reason:
                waiver_consumption, consume_refusal = consume_approval(
                    paths,
                    waiver_subject(
                        args.work_id, item.get("project_name", ""), args.pathway, args.reason,
                        work_context_sha256(item, args.pathway),
                    ),
                    f"work-cover:{args.work_id}:{args.pathway}",
                )
                if waiver_consumption is None:
                    refusal = consume_refusal
        if waiver_consumption is None:
            return {
                "findings": [finding(
                    "work-cover-production-secure-na-blocked",
                    "daily-work",
                    "error",
                    "Production-secure pathway obligations cannot be waived by a free-text N/A "
                    f"reason (waiver ticket refusal: {refusal}).",
                    [line_evidence(paths.work_items_path, source=args.work_id)],
                    "Provide verified pathway proof, or have Alex issue a single-use waiver — "
                    "`approval-issue --kind production-secure-waiver --work-id "
                    f"{args.work_id} --pathway {args.pathway} --reason \"<exact reason>\"` — "
                    "then re-run this exact work-cover within its 15-minute window.",
                    "static",
                    "high",
                )],
                "records": [],
            }
    itinerary = list(item.get("itinerary") or [])
    entry = next((e for e in itinerary if e.get("pathway") == args.pathway), None)
    if args.add:
        if entry:
            # Preserve genuinely earned proof. If an older engine incorrectly marked a pathway
            # proved from an explicitly non-passing proof, --add is also the narrow repair path:
            # reopen only when the recorded proving receipt exists but no verified proof supports
            # the pathway. Legacy/manual proved entries with no matching proof record stay intact.
            pathway_proofs = [
                proof for proof in read_ndjson(paths.proofs_path)
                if proof.get("work_id") == args.work_id and proof.get("pathway") == args.pathway
            ]
            proved_by = entry.get("proved_by_run") or ""
            recorded_receipt = any(
                proved_by and proved_by in (proof.get("run_id"), proof.get("proof_id"))
                for proof in pathway_proofs
            )
            # Older writes redacted the nested generated run id before `proved_by_run` was added
            # to the redactor's generated-id allowlist. If the marker remains and this pathway has
            # proof records, treat it as a recorded receipt; verified support below still decides
            # whether it is earned or must be reopened.
            recorded_receipt = recorded_receipt or (
                proved_by == "[REDACTED]" and bool(pathway_proofs)
            )
            cover_approval_events = approval_events_for(paths)
            verified_support = any(
                proof_credits_pathway(proof, cover_approval_events) for proof in pathway_proofs)
            invalid_recorded_proof = (
                entry.get("status") == "proved" and recorded_receipt and not verified_support
            )
            if entry.get("status") not in ("proved", "na") or invalid_recorded_proof:
                entry["status"] = "required"
                entry["coverage_source"] = "work-cover"
                entry["proved_by_run"] = ""
            if args.reason:
                entry["reason"] = args.reason
        else:
            itinerary.append({
                "pathway": args.pathway,
                "status": "required",
                "reason": args.reason or "revealed during execution",
                "proved_by_run": "",
                "coverage_source": "work-cover",
            })
        itinerary.sort(key=lambda e: pathway_sort_key(e.get("pathway")))
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
            if waiver_consumption is not None:
                entry["waiver_digest"] = waiver_consumption.get("subject_digest", "")
                entry["waiver_consumed_id"] = waiver_consumption.get("consumption_id", "")
        else:
            na_entry = {"pathway": args.pathway, "status": "na", "reason": args.reason, "proved_by_run": ""}
            if waiver_consumption is not None:
                na_entry["waiver_digest"] = waiver_consumption.get("subject_digest", "")
                na_entry["waiver_consumed_id"] = waiver_consumption.get("consumption_id", "")
            itinerary.append(na_entry)
    item = update_work_item(paths, args.work_id, itinerary=itinerary)
    covered, total, open_required = itinerary_coverage(item)
    return {
        "records": [item],
        "findings": [],
        "work_id": args.work_id,
        "itinerary_coverage": {"covered": covered, "total": total, "open": open_required},
    }


def run_approval_issue(args, paths):
    """Issue a single-use, content-bound approval or waiver ticket (Alex's deliberate act).

    Mirrors ~/.claude/scripts/approve-send.py: SHA-256 subject digest, 15-minute expiry, single
    use, append-only audit ledger. This is a forcing function and an audit trail, not a
    cryptographic barrier — issuance is a separate, deliberate, recorded act bound to reviewed
    content, and the standing rule is that Alex runs it."""
    def _refuse(fid, message, remediation):
        return {
            "findings": [finding(
                fid, "approval-authority", "error", message,
                [line_evidence(paths.approvals_path, source=args.work_id or "")],
                remediation, "static", "high",
            )],
            "records": [],
        }

    kind = (args.kind or "").strip()
    if kind not in {APPROVAL_KIND_RELEASE, APPROVAL_KIND_WAIVER}:
        return _refuse(
            "approval-issue-unknown-kind",
            f"approval-issue requires --kind {APPROVAL_KIND_RELEASE} or {APPROVAL_KIND_WAIVER}.",
            "Re-run with one of the two supported ticket kinds.",
        )
    if not args.work_id:
        return _refuse(
            "approval-issue-missing-work-id",
            "approval-issue requires --work-id so the ticket binds one outcome.",
            "Pass the work_id created by work-start.",
        )
    reason = (args.reason or "").strip()
    if not reason:
        return _refuse(
            "approval-issue-missing-reason",
            "approval-issue requires --reason (why this approval is being granted).",
            "Re-run with --reason; for waivers the reason is content-bound and must match the "
            "work-cover --na reason byte for byte.",
        )
    # The ledger is written through the redactor. A reason the redactor rewrites would be stored
    # as different bytes than the digest binds, and the ticket would be stillborn with a refusal
    # that reads like tampering. Refuse loudly at issue time instead.
    if redact(reason) != reason or not _authority_text_safe(reason):
        return _refuse(
            "approval-issue-reason-not-storable",
            "The reason contains secret-like or visually unsafe control text, so the reviewed "
            "authority command cannot preserve it safely.",
            "Reword the reason without credential-shaped, control, bidi, or line-separator text, "
            "then re-issue.",
        )
    item = next(
        (w for w in read_ndjson(paths.work_items_path) if w.get("work_id") == args.work_id), None)
    if item is None:
        return _refuse(
            "approval-issue-unknown-work-id",
            f"No work item exists for {args.work_id}; a ticket cannot bind a missing outcome.",
            "Check the work_id with work-status.",
        )
    project = item.get("project_name", "")
    if not all(_authority_text_safe(value) for value in (str(args.work_id), str(project))):
        return _refuse(
            "approval-issue-unsafe-identity-text",
            "The work ID or project name contains visually unsafe Unicode control text.",
            "Repair the work item identity before requesting approval.",
        )
    if kind == APPROVAL_KIND_WAIVER:
        if (args.pathway or "") not in PATHWAY_CANON_ORDER:
            return _refuse(
                "approval-issue-missing-pathway",
                "A production-secure waiver ticket requires --pathway (a canonical pathway name).",
                f"Choose one of: {', '.join(PATHWAY_CANON_ORDER)}.",
            )
        context_sha256 = work_context_sha256(item, args.pathway)
        if not context_sha256:
            return _refuse(
                "approval-issue-invalid-work-context",
                "The current work context cannot be bound to a waiver subject.",
                "Repair the work item project, goal, tier, profile, overlays, and itinerary "
                "before requesting a waiver.",
            )
        subject = waiver_subject(
            args.work_id, project, args.pathway, reason, context_sha256
        )
        authority_consumer = f"work-cover:{args.work_id}:{args.pathway}"
    else:
        receipt_raw = (getattr(args, "release_receipt", None) or "").strip()
        if not receipt_raw:
            return _refuse(
                "approval-issue-missing-receipt",
                "A release production approval requires --release-receipt (the reviewed JSON "
                "companion the ticket binds to).",
                "Pass the exact release receipt JSON path Alex reviewed.",
            )
        receipt_path = Path(receipt_raw).expanduser()
        if receipt_path.is_symlink() or not receipt_path.is_file():
            return _refuse(
                "approval-issue-receipt-unreadable",
                "The release receipt must be an existing regular file (not a symlink).",
                "Fix the path and re-run.",
            )
        receipt_sha = sha256_file(receipt_path)
        if not receipt_sha:
            return _refuse(
                "approval-issue-receipt-unreadable",
                "The release receipt could not be hashed.",
                "Fix the file and re-run.",
            )
        subject = release_approval_subject(args.work_id, project, receipt_sha)
        recommendation_id = (getattr(args, "recommendation_id", None) or "").strip()
        if not recommendation_id:
            try:
                receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
                if isinstance(receipt_payload, dict):
                    recommendation_id = str(receipt_payload.get("recommendation_id") or "")
            except (OSError, TypeError, ValueError):
                recommendation_id = ""
        derived_consumer = proof_id_for(
            str(receipt_path), args.work_id, "release", "artifact", recommendation_id
        )
        provided_consumer = (getattr(args, "consumer", None) or "").strip()
        if provided_consumer and provided_consumer != derived_consumer:
            return _refuse(
                "approval-issue-consumer-mismatch",
                "--consumer does not match the exact proof id derived from the reviewed receipt.",
                f"Use --consumer {derived_consumer}, then log the same receipt with the same "
                "work id, release pathway, artifact proof type, and recommendation id.",
            )
        authority_consumer = provided_consumer or derived_consumer
    if approval_store_is_protected(paths):
        command = _approval_helper_command(
            "issue",
            [
                "--subject-json",
                json.dumps(subject, sort_keys=True, separators=(",", ":")),
                "--reason",
                reason,
                "--consumer",
                authority_consumer,
            ],
        )
        refusal = _refuse(
            "approval-issue-human-helper-required",
            "The user-writable operating-layer CLI cannot issue live approval authority.",
            f"Review the exact subject, then run this in Alex's normal Terminal: {command}",
        )
        refusal["authority_command"] = command
        return refusal
    digest = approval_subject_digest(subject)
    now = utc_now()
    issued_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    event = {
        "event": "issued",
        "kind": kind,
        "subject_digest": digest,
        # Each issuance is its own ticket. Consumption is ticket-scoped, so a spent ticket never
        # locks out a later, deliberate re-approval of the same subject.
        "ticket_id": f"AT-{sha_text(digest + '|' + issued_at + '|' + secrets.token_hex(8), 12)}",
        "subject": subject,
        "issued_at": issued_at,
        "expires_at": (now + timedelta(seconds=APPROVAL_TTL_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reason": reason,
        "work_id": args.work_id,
        # Who ran the issuing command. This does not authenticate Alex — the agent and the
        # operator share this shell — but it makes the act attributable after the fact, which a
        # ledger with no issuer at all could not do.
        "issued_by": _approval_issuer_identity(),
    }
    with _approvals_write_lock(paths):
        events = approval_events_for(paths)
        if not approval_events_valid(events):
            return _refuse(
                "approval-issue-ledger-invalid",
                "The approvals ledger is malformed, truncated, symlinked, or over its read cap.",
                "Repair or rotate the ledger before issuing another ticket.",
            )
        if not _approval_write_fits([*events, event]):
            return _refuse(
                "approval-issue-ledger-over-cap",
                "This approval event would put the ledger past its exact read cap.",
                "Rotate the approvals ledger before issuing another ticket.",
            )
        write_ndjson(paths.approvals_path, [*events, event])
    next_step = (
        f"work-cover --work-id {args.work_id} --pathway {args.pathway} --na --reason "
        "\"<the exact same reason>\""
        if kind == APPROVAL_KIND_WAIVER
        else f"work-log --work-id {args.work_id} --pathway release ... (the receipt must stay "
        "byte-identical to what was just reviewed)"
    )
    return {
        "findings": [],
        "records": [event],
        "subject_digest": digest,
        "expires_in_seconds": APPROVAL_TTL_SECONDS,
        "single_use": True,
        "next_step": next_step,
    }


def run_approval_invalidate(args, paths):
    """Append an exact-ticket invalidation (Alex's deliberate corrective act).

    Invalidation never rewrites issuance or consumption history. Status-time corroboration
    consults this event, so an invalidated ticket cannot credit a waiver or release proof even
    when its consumption predates the correction.
    """
    def _refuse(fid, message, remediation):
        return {
            "findings": [finding(
                fid, "approval-authority", "error", message,
                [line_evidence(paths.approvals_path, source=args.ticket_id or "")],
                remediation, "static", "high",
            )],
            "records": [],
        }

    ticket_id = (args.ticket_id or "").strip()
    if not APPROVAL_TICKET_ID_RE.fullmatch(ticket_id):
        return _refuse(
            "approval-invalidate-invalid-ticket-id",
            "approval-invalidate requires one exact ticket id in the AT-<12 lowercase hex> form.",
            "Copy the ticket_id from the approvals ledger and re-run the reviewed command.",
        )
    reason = (args.reason or "").strip()
    if not reason:
        return _refuse(
            "approval-invalidate-missing-reason",
            "approval-invalidate requires --reason so the correction is auditable.",
            "State the bounded correction reason and re-run the reviewed command.",
        )
    if redact(reason) != reason or not _authority_text_safe(reason):
        return _refuse(
            "approval-invalidate-reason-not-storable",
            "The invalidation reason contains secret-like or visually unsafe control text.",
            "Reword the reason without credential-shaped, control, bidi, or line-separator text, "
            "then re-run.",
        )
    if approval_store_is_protected(paths):
        command = _approval_helper_command(
            "invalidate", ["--ticket-id", ticket_id, "--reason", reason]
        )
        refusal = _refuse(
            "approval-invalidate-human-helper-required",
            "The user-writable operating-layer CLI cannot invalidate live approval authority.",
            f"Review the exact ticket and reason, then run this in Alex's normal Terminal: {command}",
        )
        refusal["authority_command"] = command
        return refusal

    with _approvals_write_lock(paths):
        events = approval_events_for(paths)
        if not approval_events_valid(events):
            return _refuse(
                "approval-invalidate-ledger-invalid",
                "The approvals ledger is malformed, truncated, symlinked, or over its read cap.",
                "Repair or rotate the ledger before invalidating a ticket.",
            )
        if not _approval_write_fits(events):
            return _refuse(
                "approval-invalidate-ledger-over-cap",
                "The approvals ledger is at or past its exact read cap.",
                "Rotate the approvals ledger before invalidating a ticket.",
            )
        issued = approval_event_for_ticket(events, ticket_id, "issued")
        if issued is None:
            return _refuse(
                "approval-invalidate-ticket-not-found",
                f"No issued approval ticket exists with id {ticket_id}.",
                "Check the exact ticket_id in the approvals ledger.",
            )
        prior = approval_event_for_ticket(events, ticket_id, "invalidated")
        if prior is not None:
            return {
                "findings": [],
                "records": [prior],
                "ticket_id": ticket_id,
                "status": "already_invalidated",
            }
        at = iso_now()
        event = {
            "event": "invalidated",
            "kind": issued.get("kind", ""),
            "subject_digest": issued.get("subject_digest", ""),
            "ticket_id": ticket_id,
            "at": at,
            "work_id": issued.get("work_id", ""),
            "reason": reason,
            "invalidated_by": _approval_issuer_identity(),
            "invalidation_id": f"AI-{sha_text(ticket_id + '|' + at + '|' + reason, 12)}",
        }
        if not _approval_write_fits([*events, event]):
            return _refuse(
                "approval-invalidate-ledger-over-cap",
                "This invalidation event would put the ledger past its exact read cap.",
                "Rotate the approvals ledger before invalidating a ticket.",
            )
        write_ndjson(paths.approvals_path, [*events, event])
    return {
        "findings": [],
        "records": [event],
        "ticket_id": ticket_id,
        "status": "invalidated",
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
    # Keep the append-only ledger row for current-view causality. The summary deliberately
    # recomputes cached itinerary states, so passing its projected item would erase the historical
    # `release: proved` marker before current_work_item_view can detect a deleted release proof.
    persisted_item = next(
        (
            item for item in read_ndjson(paths.work_items_path)
            if item.get("work_id") == args.work_id
        ),
        None,
    )
    summary = work_status_summary(paths, args.work_id)
    current_item, current_summary = current_work_item_view(
        paths, persisted_item or summary.get("work_item"), summary=summary
    )
    if current_item is not None and current_summary is not None:
        summary = current_summary
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
        if args.pathway == "observability":
            return {"findings": findings, "records": []}

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
        proof, proof_finding = build_proof_record(args, work_item=item, run_id=run_id, measurement_id_value=measurement["measurement_id"], projects_root=paths.projects_root, paths=paths)
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
    carry_forward = None
    if proof:
        upsert_proof(paths, proof)
        write_proof_report(paths, read_ndjson(paths.proofs_path))
        carry_forward = build_carry_forward_record(proof, item, approval_events_for(paths))
        if carry_forward:
            upsert_carry_forward(paths, carry_forward)
    if item:
        updates = {"last_pathway": args.pathway, "last_run_id": run_id}
        # Mark the itinerary entry proved ONLY when this log carries (a) a real artifact on disk
        # AND (b) a proof that is genuinely VERIFIED — a non-trivial re-executed verifier that
        # exited 0 (proof_is_verified). A bare --verified-by string is attestation, not
        # verification, and can no longer prove. This is the keystone
        # that makes `proved` — and everything gated on it (coverage, proof rate, autonomy,
        # learning, calibration) — mean a verification actually passed, not that a string was typed.
        proved = (bool(proof) and bool(evidence_path) and Path(evidence_path).is_file()
                  and proof_credits_pathway(proof, approval_events_for(paths)))
        itinerary = item.get("itinerary") or []
        if proved and itinerary:
            for entry in itinerary:
                if entry.get("pathway") == args.pathway and entry.get("status") == "required":
                    entry["status"] = "proved"
                    entry["proved_by_run"] = run_id
                    updates["itinerary"] = itinerary
        update_work_item(paths, args.work_id, **updates)
    dashboard = build_daily_dashboard(paths)
    return {
        "records": [run, measurement] + ([proof] if proof else []) + ([carry_forward] if carry_forward else []) + ([control] if control else []),
        "findings": findings,
        "run_id": run_id,
        "carry_forward": carry_forward or {},
        "dashboard": str(paths.daily_dashboard_path),
        "daily": dashboard,
    }


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
        # Same key schema as the closed=True return (report/html present but null) so
        # callers can rely on the shape without branching on closed first.
        return {"records": [summary], "findings": findings, "closed": False, "work_id": args.work_id, "report": None, "html": None, "dashboard": str(paths.daily_dashboard_path), "daily": dashboard}
    summary_item = summary.get("work_item") or {}
    item = update_work_item(
        paths,
        args.work_id,
        status="closed",
        closed_at=iso_now(),
        closeout_readiness="ready",
        itinerary=summary_item.get("itinerary", []),
        outcome_profile=summary_item.get("outcome_profile", {}),
        risk_overlays=summary_item.get("risk_overlays", []),
    )
    learning = extract_learning_candidate(paths, summary, item)
    _candidates, learning_md, learning_html = write_learning_candidate(paths, learning)
    dashboard = build_daily_dashboard(paths)
    return {
        "records": [item, learning],
        "findings": [],
        "closed": True,
        "work_id": args.work_id,
        "learning": learning,
        "learning_report": str(learning_md),
        "learning_html": str(learning_html),
        "report": str(learning_md),
        "html": str(learning_html),
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
    if args.pathway == "observability" and not work_item:
        return {
            "records": [],
            "findings": [finding(
                "proof-add-unlinked-observability-work-id",
                "proof-registry",
                "warn",
                f"Observability proof refused for unknown work_id {args.work_id or '<missing>'}.",
                [line_evidence(paths.work_items_path, source=args.work_id or "<missing>")],
                "Run work-start first and bind the proof to that canonical work item.",
                "static",
                "high",
            )],
            "proofs_path": str(paths.proofs_path),
        }
    proof, proof_finding = build_proof_record(
        args, work_item=work_item, projects_root=paths.projects_root, paths=paths)
    # No proof at all (e.g. missing evidence) is fatal. A proof accompanied by a
    # finding is the loud will-not-credit advisory (proof-logged-unverified) —
    # record the proof AND surface the warning; swallowing either repeats the
    # silent logged_unverified failure this finding exists to prevent.
    if proof is None:
        return {
            "records": [],
            "findings": [proof_finding] if proof_finding else [],
            "proofs_path": str(paths.proofs_path),
        }
    advisory_findings = [proof_finding] if proof_finding else []
    proofs = upsert_proof(paths, proof)
    md_path, html_path = write_proof_report(paths, proofs)
    carry_forward = build_carry_forward_record(proof, work_item, approval_events_for(paths))
    if carry_forward:
        upsert_carry_forward(paths, carry_forward)
    result = {
        "records": [proof] + ([carry_forward] if carry_forward else []),
        "findings": advisory_findings,
        "proof_id": proof["proof_id"],
        "proofs_path": str(paths.proofs_path),
        "report": str(md_path),
        "html": str(html_path),
        "carry_forward": carry_forward or {},
    }
    # Close the itinerary join at write time: a proof recorded here that clears the verifier bar
    # flips its pathway required->proved, so coverage reflects the verification that actually
    # passed instead of stalling at logged_unverified. Uses the SAME gate as the inline work-log
    # flip (proof_is_verified), so a bare attestation still cannot prove.
    if proof.get("work_id"):
        item = next((w for w in read_ndjson(paths.work_items_path) if w.get("work_id") == proof["work_id"]), None)
        if item:
            itinerary = list(item.get("itinerary") or [])
            if apply_proof_coverage(
                    itinerary,
                    proved_pathways_from_proofs(
                        proof["work_id"], proofs, approval_events_for(paths))):
                item = update_work_item(paths, proof["work_id"], itinerary=itinerary)
            covered, total, open_required = itinerary_coverage(item)
            result["work_id"] = proof["work_id"]
            result["itinerary_coverage"] = {"covered": covered, "total": total, "open": open_required}
    return result


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
    return resolve_project_dir(args.project, paths.projects_root) or None


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
            latest_review = fpath.parent / "latest-findings.json"
            if (
                fpath.parent.name == "review"
                and fpath.name != "latest-findings.json"
                and latest_review.exists()
            ):
                # review-stack writes a current-state snapshot here. Older named
                # review files are retained as evidence, not open findings.
                continue
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
    approval_events = approval_events_for(paths)
    effective_items = [
        current_work_item_view(paths, item, approval_events=approval_events)[0]
        for item in items
    ]
    matches = [
        w for w in effective_items
        if w.get("status", "active") != "closed"
        and (w.get("project") == project_path or w.get("project_name") == project_name)
    ]
    return sorted(matches, key=lambda w: w.get("updated_at", ""), reverse=True)


def work_item_is_within_project(item, project_path, project_name):
    """Whether an explicitly selected work item belongs to this project boundary.

    Default selection keeps its existing exact project/name behavior. Explicit selection may pin
    a work item owned by a nested checkout (for example ConsultOps inside the Koho project root),
    but never a sibling or unrelated project.
    """
    item_project = str(item.get("project") or "").strip()
    if item_project:
        try:
            Path(item_project).resolve().relative_to(Path(project_path).resolve())
            return True
        except (OSError, RuntimeError, ValueError):
            return False
    return item.get("project_name") == project_name


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


def score_pathways(paths, project_path, project_name, scoped_findings, active_summary,
                   outcome_profile=None, risk_overlays=None, latest_carry_forward=None):
    """Score each pathway by how much it is the current constraint.

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

    # Outcome-state signals belong only to the selected active work item. Project findings and
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

    def covered_by_active_work(pathway):
        return pathway in covered_pathways

    profile = outcome_profile or {}
    if profile.get("id"):
        for pathway in profile.get("required_pathways", []) or []:
            if not covered_by_active_work(pathway):
                bump(pathway, 12, f"Outcome profile `{profile.get('id')}` requires {pathway}.")
    for overlay in risk_overlays or []:
        for pathway in overlay.get("required_pathways", []) or []:
            if not covered_by_active_work(pathway):
                bump(pathway, 35, f"Risk overlay `{overlay.get('id')}` requires {pathway}: {overlay.get('title', '')}.")
    if latest_carry_forward:
        for pathway in carry_forward_next_pathways(latest_carry_forward):
            if not covered_by_active_work(pathway):
                bump(pathway, 25, f"Carry-forward `{latest_carry_forward.get('pathway')}` says the next move must use {pathway}.")

    # Foundation gates. For an ACTIVE tracked outcome, govern/research genuinely come first (don't
    # plan from vague context) — they dominate so the itinerary walks foundations before building.
    # But on an UNTRACKED project (a cold ASK), defaulting to a foundation gate BURIES the project's
    # real findings — the measured 0/3 external-precision failure (consult-ops had 36 findings and
    # got "pin a metric"). So the gate only dominates with active work; untracked, it is a small
    # tiebreaker and live findings drive the pick.
    has_active_work = active_summary is not None
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
    for p in CORE_PATHWAYS:
        if p not in seen and p not in ("research", "govern"):
            bump(p, 4, "Pathway has no run for this project's active work yet.")

    # Learning loop (Gap D): closed outcomes reweight the ranking. A pathway this project has
    # repeatedly proved-and-closed is, by that demonstrated track record, less likely to be the
    # current constraint — dampen it so the recommender surfaces pathways not yet demonstrated.
    # No-op until the project has closure history; bounded so it never overrides a real signal.
    for pathway, closed_ids in learned_pathway_closures(paths, project_name, project_path).items():
        n = min(len(closed_ids), LEARN_DAMPEN_CAP)
        # Safety (audit P1): never dampen a pathway that carries a LIVE finding or open control this
        # turn. Past demonstration must not suppress current risk — an always-needed pathway like
        # security with a fresh warning has to stay surfaced, not get buried by old closures.
        has_live_signal = any(
            "finding [" in r or "Open control [" in r for r in scores.get(pathway, {}).get("reasons", []))
        if n and pathway in scores and not has_live_signal:
            bump(pathway, -LEARN_DAMPEN_PER_CLOSE * n,
                 f"Demonstrated: {len(closed_ids)} closed outcome(s) proved {pathway} — "
                 "deprioritized in favor of pathways not yet demonstrated.")

    ranked = sorted(scores.values(), key=lambda s: (-s["score"], pathway_sort_key(s["pathway"])))
    return ranked


def karpathy_card(pathway, project_name, goal, carry_forward=None):
    doctrine = PATHWAY_DOCTRINE.get(pathway, {})
    card = {
        "pathway": pathway,
        "title": doctrine.get("title", pathway),
        "spec_decision": doctrine.get("decision", ""),
        "verifier_good": doctrine.get("good", ""),
        "real_artifact": doctrine.get("artifact", ""),
        "one_percent_move": doctrine.get("move", ""),
        "skill": doctrine.get("skill", ""),
        "execution_stack": list(PATHWAY_EXECUTION.get(pathway, {}).get("stack", [])),
        "execution_tools": list(PATHWAY_EXECUTION.get(pathway, {}).get("tools", [])),
        "verifier_template": verifier_template_for(pathway),
        "goal": goal or f"Advance {project_name} via the {pathway} pathway",
        "do_not_do_yet": list((carry_forward or {}).get("do_not_do_yet", []) or []),
        "open_decisions": list((carry_forward or {}).get("open_decisions", []) or []),
    }
    if pathway == "release" and "release" in carry_forward_deferred_pathways(carry_forward):
        card.update({
            "title": "Release hold and prerequisite closure",
            "verifier_good": "A structured receipt proves the exact preview or production state without overstating a hold.",
            "real_artifact": "typed release receipt plus verifier and rollback evidence",
            "one_percent_move": "Resolve the first named release prerequisite and keep deployment blocked.",
            "skill": "/review-stack --audit",
            "execution_stack": [
                "/review-stack --audit",
                "structured release receipt validation",
                "prerequisite closure before any deploy",
            ],
            "execution_tools": ["local release verifier", "pathway proof ledger"],
        })
    return card


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


# Earning autonomy from a success rate at small n (fast-follow dossier item 3). A Wald point
# estimate (proved/total) is the bug: n=1 at 100% reads 1.0 and wrongly unlocks. The gate instead
# uses a Wilson score lower bound (z=1.96) behind a hard floor of MIN_AUTONOMY_N proofs — below the
# floor no streak unlocks; above it, the lower bound proves the RATE, not a lucky run. Wilson beats
# Clopper-Pearson (over-covers, wastes proofs) and SPRT (needs two hypotheses) for a static gate; a
# Jeffreys cross-check in the test suite confirms the thresholds are not a single-formula artifact.
# At z=1.96 the unlock math is n=10->k>=9, n=20->k>=15, n=50->k>=32. (Brown, Cai & DasGupta 2001.)
MIN_AUTONOMY_N = 10


def wilson_lower_bound(k, n, z=1.96):
    """Lower bound of the Wilson score interval for k successes in n trials — closed-form,
    deterministic, auditable in one line. Fail-closed to 0.0 on no/invalid evidence (n<=0, or a
    corrupted count outside 0<=k<=n): a safety gate must never crash on a bad ledger row."""
    if n <= 0 or k < 0 or k > n:
        return 0.0
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = p + z2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (center - margin) / denom


def autonomy_gate_rate(proved, total):
    """The proof-track-record rate fed to the autonomy gate: the Wilson lower bound of proved/total,
    but ONLY once total clears MIN_AUTONOMY_N; below the floor it is 0.0, so a handful of low-n
    successes can never unlock execute-safe. ('A hard minimum n is non-negotiable.')"""
    if total < MIN_AUTONOMY_N:
        return 0.0
    return wilson_lower_bound(proved, total)


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


def render_pathway_next_report(paths, project_name, recommended, ranked, card, work_id, next_command, has_context, sources=None, trust=None, confidence=None, autonomy=None, latest_carry_forward=None, carry_forward_note="", outcome_profile=None, risk_overlays=None, blocked_on_deferred=False, blocked_next_action=""):
    sources = sources or {}
    trust = trust or {"status": "unknown", "summary": "pathway-trust has not run yet"}
    confidence = confidence or recommendation_confidence(ranked, has_context, trust)
    if blocked_on_deferred:
        cf = latest_carry_forward or {}
        release_overlay = release_carry_forward_overlay(cf)
        open_decisions = cf.get("open_decisions", []) or []
        do_not_do_yet = cf.get("do_not_do_yet", []) or []
        next_requirements = cf.get("next_pathway_must_use", []) or []
        lines = [
            f"# Pathway prerequisite hold: {project_name}",
            "",
            f"Generated: {iso_now()}",
            "",
            "**No pathway recommendation was logged. Every remaining open pathway is explicitly deferred by the latest carry-forward.**",
            "",
            "## Next safe action",
            "",
            f"- {blocked_next_action}",
            "",
            "## Carry-forward authority",
            "",
            f"- Source pathway: `{cf.get('pathway', '')}`",
            f"- Source artifact: `{cf.get('source_artifact', '')}`",
            f"- Outcome: `{cf.get('pathway_outcome', '')}`",
            f"- Credits pathway: `{str(bool(cf.get('credits_pathway'))).lower()}`",
            f"- Continuity effect: {carry_forward_note}",
            *([f"- Release approval overlay: {release_overlay}"] if release_overlay else []),
            "",
            "## Requirements to resolve",
            "",
        ]
        lines.extend(f"- {item}" for item in (next_requirements or ["Resolve the deferred pathway prerequisites."]))
        lines += ["", "## Do not do yet", ""]
        lines.extend(f"- {item}" for item in (do_not_do_yet or ["Do not perform the deferred pathway."]))
        lines += ["", "## Open decisions", ""]
        lines.extend(f"- {item}" for item in (open_decisions or ["No specific open decision was recorded."]))
        lines += [
            "",
            "## Operator state",
            "",
            f"- Work ID: `{work_id or 'none'}`",
            "- Recommendation ID: none",
            "- Suggested autonomy: `recommend`",
            "- Production mutation: none authorized",
        ]
        return "\n".join(lines) + "\n"
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
        '  A["Gather state"] --> B["Classify outcome + overlays"]',
        f'  B --> C["Score {len(PATHWAY_ORDER)} pathways"]',
        f'  C --> D["Run: {rec_pathway}"]',
        '  D --> E["Log measurement against work_id"]',
        "```",
        "",
        "## Karpathy path forward",
        "",
        f"- **Spec (the decision):** {card['spec_decision']}",
        f"- **Verifier (what good looks like):** {card['verifier_good']}",
        f"- **Real artifact (proof):** {card['real_artifact']}",
        f"- **Verifier template:** `{card.get('verifier_template', {}).get('id', 'none')}`",
        f"- **Skill to run:** `{card['skill']}`",
        f"- **Best-execution stack:** {' → '.join(card.get('execution_stack', [])) or card['skill']}",
        f"- **Env / plugins / MCP:** {', '.join(card.get('execution_tools', [])) or '—'}",
        f"- **Do not do yet:** {'; '.join(card.get('do_not_do_yet', [])[:3]) or 'none recorded'}",
        f"- **Open decisions:** {'; '.join(card.get('open_decisions', [])[:3]) or 'none recorded'}",
        "",
        "## Outcome Profile And Risk Overlays",
        "",
        f"- **Outcome profile:** `{(outcome_profile or {}).get('id', 'internal-live-feature')}` — {(outcome_profile or {}).get('label', '')}",
        f"- **Profile tier default:** `{(outcome_profile or {}).get('default_tier', DEFAULT_ITINERARY_TIER)}`",
        f"- **Required by profile:** {', '.join((outcome_profile or {}).get('required_pathways', []) or []) or '—'}",
        "",
        "| Overlay | Pulls In | Why It Matters |",
        "|---|---|---|",
    ]
    for overlay in risk_overlays or []:
        lines.append(
            f"| `{overlay.get('id')}` | {', '.join(overlay.get('required_pathways', [])) or '—'} | {overlay.get('title', '')} |"
        )
    if not risk_overlays:
        lines.append("| — | — | No risk overlay matched the current signals. |")
    lines += [
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
    cf = latest_carry_forward or {}
    release_overlay = release_carry_forward_overlay(cf)
    lines += [
        "",
        "## What Previous Work Changed",
        "",
        f"- **Carry-forward:** {carry_forward_note or carry_forward_effect(cf, rec_pathway)}",
    ]
    if cf:
        lines += [
            f"- **Source artifact:** `{cf.get('source_artifact', '')}`",
            f"- **What changed:** {'; '.join(cf.get('what_changed', [])[:3]) or '—'}",
            f"- **More relevant now:** {'; '.join(cf.get('more_relevant', [])[:3]) or '—'}",
            f"- **Less relevant / deferred:** {'; '.join(cf.get('less_relevant', [])[:3]) or '—'}",
            f"- **Next must use:** {'; '.join(cf.get('next_pathway_must_use', [])[:3]) or '—'}",
            f"- **Do not do yet:** {'; '.join(cf.get('do_not_do_yet', [])[:3]) or '—'}",
            f"- **Open decisions:** {'; '.join(cf.get('open_decisions', [])[:3]) or '—'}",
            f"- **Active risk overlays:** {', '.join(cf.get('active_risk_overlays', [])[:6]) or '—'}",
        ]
        if release_overlay:
            lines.append(f"- **Release approval overlay:** {release_overlay}")
    if autonomy:
        lines += [
            "",
            "## Suggested Autonomy",
            "",
            f"- **Tier:** `{autonomy.get('tier', 'recommend')}`",
            f"- **Why:** {autonomy.get('why', '')}",
            f"- **Inputs:** proof gate-rate {round(autonomy.get('proved_rate', 0), 3)} "
            f"(Wilson LB, n>={MIN_AUTONOMY_N}) · trust "
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
        run_trust_command("techdebt guard trust suite", [sys.executable, str(test_dir / "techdebt_guard_test.py")], 8.0),
        run_trust_command("design guard trust suite", [sys.executable, str(test_dir / "design_guard_test.py")], 12.0),
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


def compute_pathway_next(args, paths):
    """Pure recommendation compute — scores pathways and derives the pick without touching
    disk (no recommendations-ledger append, no report render). run_pathway_next persists the
    result exactly once via persist_pathway_next; callers that need a dry pass (pathway-pilot
    enrollment probing for an active work item) call this directly, so unactionable rows never
    reach the ledger and never corrupt the autonomy_gate_rate denominator."""
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
    requested_work_id = str(getattr(args, "work_id", "") or "").strip()
    if requested_work_id:
        known_item = next(
            (item for item in read_ndjson(paths.work_items_path)
             if item.get("work_id") == requested_work_id),
            None,
        )
        effective_known_item = current_work_item_view(paths, known_item)[0] if known_item else None
        selected_item = (
            effective_known_item
            if effective_known_item
            and effective_known_item.get("status", "active") != "closed"
            and work_item_is_within_project(effective_known_item, project_path, project_name)
            else None
        )
        if not selected_item:
            if known_item and known_item.get("status", "active") == "closed":
                detail = f"Work item {requested_work_id} is closed and cannot drive a new recommendation."
            elif known_item:
                detail = (
                    f"Work item {requested_work_id} does not belong to the selected project "
                    f"{project_name}."
                )
            else:
                detail = f"No work item exists for work_id {requested_work_id}."
            return {
                "findings": [finding(
                    "pathway-next-work-id-not-active",
                    "pathway-next",
                    "warn",
                    detail,
                    [line_evidence(paths.work_items_path, source=requested_work_id)],
                    f"Pass an active work ID for {project_name}, or omit --work-id to use the newest active item.",
                    "static",
                    "high",
                )],
                "records": [],
                "project": project_name,
                "work_id": requested_work_id,
            }
    else:
        selected_item = work_items[0] if work_items else None
    work_id = selected_item.get("work_id") if selected_item else None
    active_summary = work_status_summary(paths, work_id) if work_id else None
    active_item = (active_summary or {}).get("work_item") or selected_item or {}
    latest_carry_forward = latest_carry_forward_for_work(paths, work_id) if work_id else {}
    goal_for_contract = args.goal or active_item.get("goal") or f"Advance {project_name} via /pathway"
    if active_item.get("outcome_profile") or active_item.get("risk_overlays"):
        outcome_profile = active_item.get("outcome_profile") or classify_outcome_profile(
            goal_for_contract, project_name, scoped_findings, latest_carry_forward)
        risk_overlays = active_item.get("risk_overlays") or detect_risk_overlays(
            goal_for_contract, project_name, scoped_findings, latest_carry_forward, outcome_profile)
        contract_tier = active_item.get("tier", DEFAULT_ITINERARY_TIER)
    else:
        contract = outcome_contract(goal_for_contract, project_path, project_name, scoped_findings, latest_carry_forward)
        outcome_profile = contract["outcome_profile"]
        risk_overlays = contract["risk_overlays"]
        contract_tier = contract["tier"]
    ranked = score_pathways(
        paths, project_path, project_name, scoped_findings, active_summary,
        outcome_profile, risk_overlays, latest_carry_forward)
    recommended = ranked[0]
    # Itinerary override: when the active outcome still owes required pathways, the next
    # move comes from the committed itinerary (so coverage is never silently skipped) —
    # but WITHIN that set the order is evidence-driven, not a fixed list. Foundations
    # (govern/research) stay first while open, because they are prerequisites. Among the
    # remaining open-required pathways the router follows live EVIDENCE: it picks the
    # highest-scored one (ranked is score-sorted, with findings/controls already routed to
    # pathways), so the next move bends toward current risk instead of canonical order.
    # (Gap B part 2: coverage guarantee + evidence-grounded ordering, together.)
    itinerary_open = (active_summary or {}).get("itinerary_coverage", {}).get("open", []) if active_summary else []
    # Ready-to-close routing: when the closeout gate itself says ready, the honest next
    # move is work-close, and the result must say so explicitly instead of pointing the
    # operator at another work-log. Gated on closeout_readiness — the SAME gate work-close
    # enforces (runs + controls + evidence + staleness + itinerary) — so pathway-next can
    # never route to a work-close that would refuse (e.g. itinerary covered but a control
    # still open, or an all-na itinerary with no runs).
    ready_to_close = bool(work_id and (active_summary or {}).get("closeout_readiness") == "ready")
    deferred_pathways = set(carry_forward_deferred_pathways(latest_carry_forward))
    selectable_open = [p for p in itinerary_open if p not in deferred_pathways]
    blocked_on_deferred = bool(itinerary_open and not selectable_open)
    if itinerary_open:
        FOUNDATIONS = ("govern", "research")
        open_foundations = [p for p in selectable_open if p in FOUNDATIONS]
        if open_foundations:
            first = open_foundations[0]  # itinerary_open is canonical-ordered: govern before research
        elif selectable_open:
            # A structured baton is the authority for semantic continuity. Once foundations are
            # covered, an explicit non-conditional "X must close/produce/..." directive outranks
            # generic profile/overlay scoring among still-open pathways; otherwise a blocked
            # release can immediately loop back to release despite saying implementation must go
            # first. Scoring still decides when the baton has no actionable open directive.
            baton_open = [
                pathway for pathway in carry_forward_next_pathways(latest_carry_forward)
                if pathway in selectable_open
            ]
            first = baton_open[0] if baton_open else next(
                (r["pathway"] for r in ranked if r["pathway"] in selectable_open),
                selectable_open[0],
            )
        else:
            first = ""
        if first:
            recommended = next((r for r in ranked if r["pathway"] == first), recommended)
    blocked_next_action = ""
    if blocked_on_deferred:
        action_candidates = (
            list(latest_carry_forward.get("open_decisions", []) or [])
            + list(latest_carry_forward.get("next_pathway_must_use", []) or [])
        )
        blocked_next_action = (
            action_candidates[0] if action_candidates
            else "Resolve the latest carry-forward prerequisites before requesting another pathway."
        )
        recommended = {"pathway": "", "score": 0, "reasons": [
            "Every remaining open pathway is deferred by the latest carry-forward."
        ]}
        card = {
            "pathway": "", "title": "Prerequisite hold", "spec_decision": "Do not select a deferred pathway.",
            "verifier_good": "A new verified artifact resolves the named prerequisite without performing the deferred action.",
            "real_artifact": "verified prerequisite-resolution artifact", "one_percent_move": blocked_next_action,
            "skill": "/pathway", "execution_stack": [], "execution_tools": [],
            "verifier_template": {"id": "none"},
            "do_not_do_yet": list(latest_carry_forward.get("do_not_do_yet", []) or []),
            "open_decisions": list(latest_carry_forward.get("open_decisions", []) or []),
        }
    else:
        card = karpathy_card(recommended["pathway"], project_name, goal_for_contract, latest_carry_forward)
    trust = load_pathway_trust_summary(paths)
    has_context = bool(scoped_findings or selected_item)
    # Confidence must reflect the ACTUALLY recommended pathway and the field it competes
    # in. For a tracked outcome the router chooses among the open-required itinerary, so
    # confidence compares within that set (recommended is its highest-scored member) — not
    # against out-of-itinerary foundations. Otherwise why_this/evidence come from the wrong
    # pathway (e.g. research's foundation reason on an observability pick).
    confidence_open = selectable_open if itinerary_open else []
    confidence_pool = [r for r in ranked if not confidence_open or r["pathway"] in confidence_open]
    ranked_for_confidence = [recommended] + [
        r for r in confidence_pool if r["pathway"] != recommended["pathway"]
    ]
    confidence = (
        {
            "level": "low", "score_gap": 0, "runner_up_pathway": "", "runner_up_reason": "",
            "why_this": "No selectable pathway remains.", "why_not_runner_up": "All open pathways are deferred.",
            "top_evidence": ["The latest carry-forward defers every remaining open pathway."],
            "missing_evidence": ["A verified prerequisite-resolution artifact is required."],
        }
        if blocked_on_deferred else recommendation_confidence(ranked_for_confidence, has_context, trust)
    )
    # Gap C (autonomy unlock): the engine — not the skill — computes the LOOP autonomy tier from the
    # proof track record (fresh this turn), trust, and the recommended pick's confidence. The track
    # record is gated through autonomy_gate_rate: a Wilson lower bound behind the MIN_AUTONOMY_N
    # floor, so a single proved pick (n=1 at 100%) can no longer unlock execute-safe — only a
    # demonstrated RATE over >=10 prior recommendations can. Measured over PRIOR recommendations
    # (this run's rec is logged below, after), so it reflects the track record, never the new pick.
    metric = compute_pathway_metric(paths)
    autonomy = suggest_autonomy_tier(
        autonomy_gate_rate(metric.get("proved", 0), metric.get("total_recommendations", 0)),
        trust, confidence)
    return {
        "project_path": project_path,
        "project": project_name,
        "ranked": ranked,
        "recommended": recommended,
        "recommended_pathway": recommended["pathway"],
        "karpathy_card": card,
        "one_percent_move": card["one_percent_move"],
        "pathway_trust": trust,
        "has_context": has_context,
        "signal_sources": sources,
        "recommendation_confidence": confidence,
        "suggested_autonomy_tier": autonomy["tier"],
        "autonomy_rationale": autonomy,
        "ready_to_close": ready_to_close,
        "work_id": work_id,
        "contract_tier": contract_tier,
        "latest_carry_forward": latest_carry_forward,
        "carry_forward_effect": carry_forward_effect(latest_carry_forward, recommended["pathway"]),
        "outcome_profile": outcome_profile,
        "risk_overlays": risk_overlays,
        "deferred_pathways": sorted(deferred_pathways, key=pathway_sort_key),
        "blocked_on_deferred": blocked_on_deferred,
        "blocked_next_action": blocked_next_action,
        "itinerary": (active_summary or {}).get("itinerary", []) if active_summary else [],
        "itinerary_coverage": (active_summary or {}).get("itinerary_coverage", {}) if active_summary else {},
    }


def persist_pathway_next(args, paths, state):
    """Persist step for compute_pathway_next: assigns the recommendation id, renders the
    operator report, and appends the follow-through row to the recommendations ledger — the
    autonomy_gate_rate denominator, so this must run exactly once per acted-on recommendation."""
    if "recommended" not in state:
        return state  # compute-step error result (e.g. missing project) — pass through
    project_path = state["project_path"]
    project_name = state["project"]
    recommended = state["recommended"]
    ranked = state["ranked"]
    card = state["karpathy_card"]
    trust = state["pathway_trust"]
    has_context = state["has_context"]
    sources = state["signal_sources"]
    confidence = state["recommendation_confidence"]
    autonomy = state["autonomy_rationale"]
    ready_to_close = state["ready_to_close"]
    work_id = state["work_id"]
    contract_tier = state["contract_tier"]
    latest_carry_forward = state["latest_carry_forward"]
    carry_forward_note = state["carry_forward_effect"]
    outcome_profile = state["outcome_profile"]
    risk_overlays = state["risk_overlays"]
    deferred_pathways = set(state.get("deferred_pathways", []))
    blocked_on_deferred = bool(state.get("blocked_on_deferred"))
    blocked_next_action = state.get("blocked_next_action", "")
    recommendations = read_ndjson(paths.recommendations_path)
    # No recommendation_id on ready-to-close: nothing is logged to the ledger (see below),
    # so returning an id would hand consumers a dangling reference to a row that never exists.
    recommendation_id = (
        "" if ready_to_close or blocked_on_deferred
        else f"REC-{safe_slug(project_name)}-{recommended['pathway']}-{len(recommendations) + 1:04d}"
    )

    if blocked_on_deferred:
        next_command = ""
    elif ready_to_close:
        next_command = (
            f"python3 ~/.claude/scripts/operating-layer.py work-close \\\n"
            f"  --work-id {work_id} --json"
        )
    elif work_id:
        recommended_result = "blocked" if recommended["pathway"] in deferred_pathways else "pass"
        next_command = (
            f"python3 ~/.claude/scripts/operating-layer.py work-log \\\n"
            f"  --work-id {work_id} \\\n"
            f"  --pathway {recommended['pathway']} --kind verify \\\n"
            f"  --evidence <path-to-real-artifact> --gate {recommended['pathway']}-gate --result {recommended_result} \\\n"
            f"  --proof-type artifact --verify-cmd \"<verification-command>\" \\\n"
            f"  --recommendation-id {recommendation_id}"
        )
    else:
        goal_text = args.goal or f"Advance {project_name} via {recommended['pathway']}"
        next_command = (
            f"python3 ~/.claude/scripts/operating-layer.py work-start \\\n"
            f"  --project {project_path} \\\n"
            f"  --goal \"{goal_text}\" \\\n"
            f"  --tier {contract_tier}"
        )

    md_path = dated_artifact_path(paths, f"pathway-next-{safe_slug(project_name)}")
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_pathway_next_report(
        paths, project_name, recommended, ranked, card, work_id, next_command, has_context,
        sources, trust, confidence, autonomy, latest_carry_forward, carry_forward_note,
        outcome_profile, risk_overlays, blocked_on_deferred, blocked_next_action))
    render_html(md_path, html_path)

    # Log the recommendation so pathway-metric can measure follow-through (govern metric).
    # Skipped when ready_to_close: no pathway is being recommended, and logging one here
    # would seed a follow-through entry that can never be proved (the outcome closes).
    if not ready_to_close and not blocked_on_deferred:
        recommendations.append({
            "recommendation_id": recommendation_id,
            "project": project_name,
            "pathway": recommended["pathway"],
            "work_id": work_id or "",
            "confidence": confidence.get("level", ""),
            "runner_up_pathway": confidence.get("runner_up_pathway", ""),
            "why_this": confidence.get("why_this", ""),
            "why_not_runner_up": confidence.get("why_not_runner_up", ""),
            "carry_forward_id": latest_carry_forward.get("carry_forward_id", ""),
            "outcome_profile": outcome_profile.get("id", ""),
            "risk_overlays": [o.get("id") for o in risk_overlays],
            "suggested_autonomy_tier": autonomy["tier"],
            "timestamp": iso_now(),
        })
        write_ndjson(paths.recommendations_path, recommendations)

    rec_finding = finding(
        "pathway-next-recommendation",
        "pathway-next",
        "info",
        (f"All remaining open pathways for {project_name} are deferred; resolve the carry-forward prerequisite first."
         if blocked_on_deferred else
         f"All itinerary pathways for {project_name} are covered — work item {work_id} is ready to close."
         if ready_to_close else
         f"Next-best pathway for {project_name}: {recommended['pathway']} ({card['title']}) "
         f"— {recommended['reasons'][0] if recommended['reasons'] else 'lowest-coverage pathway'}."),
        [line_evidence(md_path, source=project_name)],
        (blocked_next_action if blocked_on_deferred else
         "Run work-close to close the outcome and bank the learning candidate." if ready_to_close
         else card["one_percent_move"]),
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
        "ready_to_close": ready_to_close,
        "blocked_on_deferred": blocked_on_deferred,
        "blocked_next_action": blocked_next_action,
        "next_command": next_command,
        "ranked": ranked,
        "signal_sources": sources,
        "pathway_trust": trust,
        "recommendation_id": recommendation_id,
        "recommendation_confidence": confidence,
        "suggested_autonomy_tier": autonomy["tier"],
        "autonomy_rationale": autonomy,
        "latest_carry_forward": latest_carry_forward,
        "carry_forward_effect": carry_forward_note,
        "outcome_profile": outcome_profile,
        "risk_overlays": risk_overlays,
        "deferred_pathways": sorted(deferred_pathways, key=pathway_sort_key),
        "itinerary": state["itinerary"],
        "itinerary_coverage": state["itinerary_coverage"],
        "report": str(md_path),
        "html": str(html_path),
    }


def run_pathway_next(args, paths):
    return persist_pathway_next(args, paths, compute_pathway_next(args, paths))


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
        scoped_findings = project_scoped_findings(paths, project_path, project_name) + project_local_findings(project_path)[0]
        contract = outcome_contract(goal_text, project_path, project_name, scoped_findings)
        item = update_work_item(
            paths,
            work_id,
            status="active",
            mode="semi-automatic",
            project=project_path,
            project_name=project_name,
            goal=goal_text,
            context=current_work_context(paths, project_path),
            tier=contract["tier"],
            outcome_profile=contract["outcome_profile"],
            risk_overlays=contract["risk_overlays"],
            itinerary=compute_itinerary(contract["tier"], goal_text, contract["outcome_profile"], contract["risk_overlays"]),
            closeout_readiness="not_ready",
        )

    rec = run_pathway_next(args, paths)
    if rec.get("blocked_on_deferred"):
        return rec
    pathway = rec.get("recommended_pathway", "")
    card = rec.get("karpathy_card", {})
    guard_command = guard_command_for_pathway(paths, pathway, project_path)
    proof_command = (
        f"python3 ~/.claude/scripts/operating-layer.py work-log \\\n"
        f"  --work-id {work_id} \\\n"
        f"  --pathway {pathway} --kind verify \\\n"
        f"  --evidence <path-to-real-artifact> --gate {pathway}-gate --result pass \\\n"
        f"  --proof-type artifact --verify-cmd \"{guard_command or '<verification-command>'}\" \\\n"
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


def pathway_pilot_project_inputs(args):
    raw = getattr(args, "projects", "") or getattr(args, "project", "") or ""
    items = []
    for part in str(raw).split(","):
        value = part.strip()
        if value:
            items.append(value)
    return items


def review_gate_for_recommendation(rec):
    pathway = rec.get("recommended_pathway", "")
    autonomy = rec.get("suggested_autonomy_tier", "recommend")
    confidence = rec.get("recommendation_confidence", {}).get("level", "low")
    trust = rec.get("pathway_trust", {}).get("status", "unknown")
    overlay_ids = {o.get("id") for o in rec.get("risk_overlays", []) if o.get("id")}
    reasons = []
    if autonomy != "execute-safe":
        reasons.append(f"autonomy tier is {autonomy}")
    if confidence != "high":
        reasons.append(f"confidence is {confidence}")
    if trust != "pass":
        reasons.append(f"trust is {trust}")
    if pathway in {"field", "release"}:
        reasons.append(f"{pathway} pathway has an explicit human gate")
    matched_overlays = sorted(overlay_ids & HUMAN_GATE_OVERLAYS)
    if matched_overlays:
        reasons.append("risk overlays require review: " + ", ".join(matched_overlays))
    return {
        "required": bool(reasons),
        "reasons": reasons,
        "default_action": "Alex reviews/approves before autonomous continuation." if reasons
        else "Agentic loop may run the local reversible slice and still log proof before closeout.",
    }


def team_assignment_for_pathway(pathway):
    base = TEAM_ROLE_BY_PATHWAY.get(pathway, {})
    return {
        "pathway": pathway,
        "lead": base.get("lead", "Implementer"),
        "critic": base.get("critic", "Second-model reviewer"),
        "proof_gate": base.get("proof_gate", "Real artifact proof with executed verifier."),
        "human_gate": base.get("human_gate", "Alex reviews material scope, prod, or external-risk decisions."),
        "execution_stack": list(PATHWAY_EXECUTION.get(pathway, {}).get("stack", [])),
        "execution_tools": list(PATHWAY_EXECUTION.get(pathway, {}).get("tools", [])),
    }


def pilot_id_for(cohort_id, project, recommendation_id):
    return f"PILOT-{safe_slug(cohort_id)}-{safe_slug(project)}-{short_hash(cohort_id, project, recommendation_id, length=8)}"


def render_pathway_pilot_report(snapshot):
    metric = snapshot.get("measurement_snapshot", {})
    lines = [
        "# Agentic Dev Team Pilot",
        "",
        f"Generated: {snapshot.get('generated_at')}",
        f"Cohort: `{snapshot.get('cohort_id')}`",
        "",
        "## Final-State Spec",
        "",
        "The operating layer now treats the dev environment as an agentic team, not a bag of commands:",
        "",
        "- `pathway-next` chooses the next pathway from live state, carry-forward memory, risk overlays, and work coverage.",
        "- Each pathway maps to a lead, critic, proof gate, and Alex review gate.",
        "- `pathway-run` creates the execution plan; `work-log` proves it with a real artifact and executed verifier.",
        "- `pathway-metric`, `pathway-evaluate`, carry-forward records, and learning candidates measure improvement over time.",
        "",
        "## Measurement Snapshot",
        "",
        f"- Recommendations: {metric.get('total_recommendations', 0)}",
        f"- Acted-on rate: {metric.get('acted_on_rate', 0)}",
        f"- Proved rate: {metric.get('proved_rate', 0)}",
        f"- Gate target: {metric.get('gate_target', 0)}",
        "",
        "## Pilot Cohort",
        "",
        "| Project | Work | Next Pathway | Lead | Critic | Autonomy | Review Gate |",
        "|---|---|---|---|---|---|---|",
    ]
    for rec in snapshot.get("records", []):
        team = rec.get("team_assignment", {})
        review = rec.get("review_gate", {})
        lines.append(
            "| "
            + " | ".join([
                table_cell(rec.get("project")),
                table_cell(rec.get("work_id") or "needs work-start"),
                f"`{table_cell(rec.get('recommended_pathway'))}`",
                table_cell(team.get("lead")),
                table_cell(team.get("critic")),
                f"`{table_cell(rec.get('suggested_autonomy_tier'))}`",
                "yes" if review.get("required") else "no",
            ])
            + " |"
        )
    lines += [
        "",
        "## Review Gates",
        "",
    ]
    for rec in snapshot.get("records", []):
        review = rec.get("review_gate", {})
        lines += [
            f"### {rec.get('project')} / `{rec.get('recommended_pathway')}`",
            "",
            f"- Required: `{bool(review.get('required'))}`",
            f"- Default action: {review.get('default_action', '')}",
        ]
        reasons = review.get("reasons", [])
        if reasons:
            lines.append("- Reasons:")
            lines.extend(f"  - {reason}" for reason in reasons)
        lines += [
            f"- Proof gate: {rec.get('team_assignment', {}).get('proof_gate', '')}",
            f"- Next command: `{rec.get('next_command', '').splitlines()[0] if rec.get('next_command') else ''}`",
            "",
        ]
    lines += [
        "## Operating Loop",
        "",
        "1. Run the next pathway for one pilot project.",
        "2. Attach a real artifact and executed `--verify-cmd` through `work-log`.",
        "3. Re-run `pathway-pilot` to refresh the cohort.",
        "4. Judge at least one recommendation with `pathway-evaluate` so precision is measured, not assumed.",
        "5. Close work only after required pathways are proved or explicitly N/A with a reason.",
    ]
    return "\n".join(lines) + "\n"


def run_pathway_pilot(args, paths):
    projects = pathway_pilot_project_inputs(args)
    if not projects:
        return {
            "findings": [finding(
                "pathway-pilot-missing-projects",
                "pathway-pilot",
                "warn",
                "pathway-pilot requires --project or --projects with one or more project names/paths.",
                [line_evidence(paths.projects_root)],
                "Run `pathway-pilot --projects koho,prettyfly-os --goal \"pilot goal\"`.",
                "static",
                "high",
            )],
            "records": [],
        }
    cohort_id = f"COHORT-{utc_now().strftime('%Y%m%d')}-{short_hash(','.join(projects), getattr(args, 'goal', ''), length=8)}"
    records = []
    findings_out = []
    for raw_project in projects:
        project_path = resolve_project_path(argparse.Namespace(project=raw_project), paths)
        if not project_path or not Path(project_path).exists():
            findings_out.append(finding(
                "pathway-pilot-unknown-project",
                "pathway-pilot",
                "warn",
                f"Project does not exist: {raw_project}",
                [line_evidence(paths.projects_root, source=raw_project)],
                "Pass an existing project path or project name under the projects root.",
                "static",
                "high",
            ))
            continue
        goal = getattr(args, "goal", "") or f"Pilot the agentic dev team loop on {Path(project_path).name}"
        next_args = argparse.Namespace(**vars(args))
        next_args.project = project_path
        next_args.goal = goal
        # Dry pass: pure compute only. Persisting here would ledger a recommendation the
        # pilot immediately supersedes after work-start — an unactionable row that corrupts
        # the follow-through denominator (autonomy_gate_rate). Exactly one row is persisted
        # per enrollment, below.
        rec = compute_pathway_next(next_args, paths)
        if not rec.get("work_id") and getattr(args, "goal", ""):
            start_args = argparse.Namespace(**vars(args))
            start_args.project = project_path
            start_args.goal = goal
            start_args.tier = rec.get("outcome_profile", {}).get("default_tier") or DEFAULT_ITINERARY_TIER
            run_work_start(start_args, paths)
            rec = compute_pathway_next(next_args, paths)
        rec = persist_pathway_next(next_args, paths, rec)
        pathway = rec.get("recommended_pathway", "")
        team = team_assignment_for_pathway(pathway)
        review = review_gate_for_recommendation(rec)
        record = {
            "pilot_id": pilot_id_for(cohort_id, rec.get("project", Path(project_path).name), rec.get("recommendation_id", "")),
            "cohort_id": cohort_id,
            "timestamp": iso_now(),
            "project": rec.get("project", Path(project_path).name),
            "project_path": project_path,
            "goal": goal,
            "work_id": rec.get("work_id") or "",
            "recommended_pathway": pathway,
            "recommendation_id": rec.get("recommendation_id", ""),
            "confidence": rec.get("recommendation_confidence", {}).get("level", ""),
            "suggested_autonomy_tier": rec.get("suggested_autonomy_tier", ""),
            "outcome_profile": rec.get("outcome_profile", {}),
            "risk_overlays": rec.get("risk_overlays", []),
            "team_assignment": team,
            "review_gate": review,
            "next_command": rec.get("next_command", ""),
            "pathway_next_report": rec.get("report", ""),
            "pathway_next_html": rec.get("html", ""),
            "source": "operating-layer pathway-pilot",
        }
        records.append(record)
    metric = compute_pathway_metric(paths, args.window_days if args.window_days is not None else 1,
                                    args.gate_target if args.gate_target is not None else 0.5)
    snapshot = {
        "generated_at": iso_now(),
        "cohort_id": cohort_id,
        "records": records,
        "measurement_snapshot": metric,
        "team_roles": TEAM_ROLE_BY_PATHWAY,
        "review_gate_overlays": sorted(HUMAN_GATE_OVERLAYS),
    }
    existing = read_ndjson(paths.pathway_pilots_path)
    write_ndjson(paths.pathway_pilots_path, existing + records)
    write_json(paths.pathway_pilot_latest_path, snapshot)
    md_path = dated_artifact_path(paths, "pathway-pilot")
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_pathway_pilot_report(snapshot))
    render_html(md_path, html_path)
    return {
        "records": records,
        "findings": findings_out,
        "cohort_id": cohort_id,
        "pilot_ledger": str(paths.pathway_pilots_path),
        "pilot_latest": str(paths.pathway_pilot_latest_path),
        "measurement_snapshot": metric,
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


def compute_pathway_metric(paths, window_days=1, gate_target=0.5):
    approval_events = approval_events_for(paths)
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
    verifier_binding_cache = {}

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
            if not proof_credits_pathway(
                    proof, approval_events, verifier_binding_cache):
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


AUDIT_DOCUMENT_REQUIREMENTS = {
    "commands/pathway.md": ("pathway-next", "work-close", "--verify-cmd", CANONICAL_PATHWAY_CATALOG),
    "README.md": ("pathway-next", "work-close", "--verify-cmd", CANONICAL_PATHWAY_CATALOG),
    "pathway skill": ("$pathway", "work-log", "--verify-cmd", CANONICAL_PATHWAY_CATALOG),
    "Claude instructions": ("Pathway", "--verify-cmd", CANONICAL_PATHWAY_CATALOG),
    "Codex instructions": ("Pathway", "--verify-cmd", CANONICAL_PATHWAY_CATALOG),
    "Hermes instructions": ("Pathway", "proof", CANONICAL_PATHWAY_CATALOG),
    "technical-operator profile": ("Pathway", "proof", CANONICAL_PATHWAY_CATALOG),
}
PATHWAY_AUDIT_SCHEMA_VERSION = "v1"
PATHWAY_AUDIT_REQUIRED_FIELDS = (
    "overall_score", "pathway_scores", "metric_snapshot", "drift_findings",
    "highest_value_refinements", "data_lineage",
)


def pathway_audit_document_surfaces(paths):
    """Read the small, explicit authority surface for audit drift checks.

    These paths are observations only. A missing or stale surface reduces the score and is
    reported; this command never repairs a document on the caller's behalf.
    """
    repo_root = Path(__file__).resolve().parent.parent
    agents_root = Path(paths.projects_root) / "agents"
    locations = {
        "commands/pathway.md": repo_root / "commands" / "pathway.md",
        "README.md": repo_root / "README.md",
        "pathway skill": _HOME / ".agents" / "skills" / "pathway" / "SKILL.md",
        "Claude instructions": paths.claude_home / "CLAUDE.md",
        "Codex instructions": paths.codex_home / "AGENTS.md",
        "Hermes instructions": agents_root / "CLAUDE.md",
        "technical-operator profile": agents_root / "hermes" / "profiles" / "technical-operator" / "CLAUDE.md",
    }
    return {
        label: {"path": str(path), "text": safe_read_text(path, max_bytes=2_000_000), "exists": path.is_file()}
        for label, path in locations.items()
    }


def pathway_audit_document_drift(surfaces):
    """Return deterministic, explainable drift findings for supplied document texts.

    Keeping this pure makes intentionally drifted fixtures cheap to test and makes every
    documentation deduction visible rather than hidden inside a score.
    """
    findings = []
    checks = 0
    passes = 0
    for label, required in AUDIT_DOCUMENT_REQUIREMENTS.items():
        surface = surfaces.get(label, {})
        text = surface.get("text", "")
        path = surface.get("path", label)
        if not surface.get("exists", bool(text)):
            findings.append({
                "id": f"missing-{safe_slug(label)}",
                "severity": "warn",
                "surface": label,
                "path": path,
                "message": f"Required authority surface is missing: {label}.",
                "refinement": f"Restore {label} and state the current Pathway proof contract.",
            })
            checks += len(required)
            continue
        for token in required:
            checks += 1
            if token.lower() in text.lower():
                passes += 1
                continue
            findings.append({
                "id": f"drift-{safe_slug(label)}-{safe_slug(token)}",
                "severity": "warn",
                "surface": label,
                "path": path,
                "message": f"{label} does not mention the required contract token `{token}`.",
                "refinement": f"Align {label} with the canonical Pathway contract for `{token}`.",
            })
    return findings, passes, checks


def pathway_audit_data_lineage(paths):
    """Name the local ledgers consumed by Audit v1; paths are evidence, never credentials."""
    return {
        "schema_version": PATHWAY_AUDIT_SCHEMA_VERSION,
        "sources": {
            "proofs": str(paths.proofs_path),
            "work_items": str(paths.work_items_path),
            "carry_forward": str(paths.carry_forward_path),
            "recommendations": str(paths.recommendations_path),
        },
    }


def validate_pathway_audit_payload(audit):
    """Validate Audit v1's local JSON contract before another tool relies on its score."""
    errors = []
    if not isinstance(audit, dict):
        return ["audit payload must be an object"]
    for field in PATHWAY_AUDIT_REQUIRED_FIELDS:
        if field not in audit:
            errors.append(f"missing required field: {field}")
    score = audit.get("overall_score")
    if not isinstance(score, int) or not 0 <= score <= 100:
        errors.append("overall_score must be an integer from 0 to 100")
    scores = audit.get("pathway_scores")
    if not isinstance(scores, list) or not scores:
        errors.append("pathway_scores must be a non-empty list")
    else:
        names = set()
        for item in scores:
            if not isinstance(item, dict) or not item.get("dimension"):
                errors.append("each pathway score needs a dimension")
                continue
            names.add(item["dimension"])
            value, maximum = item.get("score"), item.get("max_score")
            if not isinstance(value, int) or not isinstance(maximum, int) or not 0 <= value <= maximum:
                errors.append(f"invalid score bounds for {item.get('dimension', 'unknown')}")
        if len(names) != len(scores):
            errors.append("pathway score dimensions must be unique")
    metric = audit.get("metric_snapshot")
    if not isinstance(metric, dict):
        errors.append("metric_snapshot must be an object")
    else:
        for field in ("project_proof_count", "verified_project_proof_count", "covered_pathways", "required_pathways"):
            if not isinstance(metric.get(field), int) or metric[field] < 0:
                errors.append(f"metric_snapshot.{field} must be a non-negative integer")
        if metric.get("verified_project_proof_count", 0) > metric.get("project_proof_count", 0):
            errors.append("verified project proofs cannot exceed project proof count")
        if metric.get("covered_pathways", 0) > metric.get("required_pathways", 0):
            errors.append("covered pathways cannot exceed required pathways")
    lineage = audit.get("data_lineage")
    if not isinstance(lineage, dict) or lineage.get("schema_version") != PATHWAY_AUDIT_SCHEMA_VERSION:
        errors.append("data_lineage must declare the current audit schema version")
    elif set(lineage.get("sources", {})) != {"proofs", "work_items", "carry_forward", "recommendations"}:
        errors.append("data_lineage must name each Audit v1 source ledger")
    return errors


def _audit_score(name, score, maximum, evidence, status="measured"):
    return {
        "dimension": name,
        "score": max(0, min(maximum, int(round(score)))),
        "max_score": maximum,
        "status": status,
        "evidence": evidence,
    }


def audit_proof_integrity_snapshot(proofs, active_work_ids, approval_events=None):
    """Separate active readiness from historical proof hygiene without rewriting history."""
    active_ids = {work_id for work_id in active_work_ids if work_id}
    active = [proof for proof in proofs if proof.get("work_id") in active_ids]
    scoped = active if active else proofs
    verified = [proof for proof in scoped if proof_credits_pathway(proof, approval_events)]
    historical_unverified = [
        proof for proof in proofs
        if proof.get("work_id") not in active_ids
        and not proof_credits_pathway(proof, approval_events)
    ]
    return {
        "scope": "active outcomes" if active else "project history (no active outcome)",
        "proof_count": len(scoped),
        "verified_count": len(verified),
        "historical_unverified_count": len(historical_unverified),
    }


def render_pathway_audit_report(audit):
    lines = [
        f"# Pathway Audit - {audit['project']}",
        "",
        f"Generated: {audit['generated_at']}",
        "",
        "## Score",
        "",
        f"- Overall score: **{audit['overall_score']}/100**",
        f"- Target: {audit['target_score']} (reported only; this command exits zero after measurement)",
        "",
        "| Dimension | Score | Evidence |",
        "|---|---:|---|",
    ]
    for item in audit["pathway_scores"]:
        lines.append(f"| {item['dimension']} | {item['score']}/{item['max_score']} | {item['evidence']} |")
    lines.extend(["", "## Drift Findings", ""])
    if audit["drift_findings"]:
        for item in audit["drift_findings"]:
            lines.append(f"- `{item['id']}` ({item['surface']}): {item['message']}")
    else:
        lines.append("- No configured documentation drift found.")
    lines.extend(["", "## Highest-Value Refinements", ""])
    for item in audit["highest_value_refinements"]:
        lines.append(f"{item['rank']}. {item['message']}")
    lines.extend(["", "## Metric Snapshot", ""])
    metric = audit["metric_snapshot"]
    lines.extend([
        f"- Proof integrity ({metric['proof_integrity_scope']}): {metric['proof_integrity_verified_count']}/{metric['proof_integrity_proof_count']} verified",
        f"- Historical unverified proofs: {metric['historical_unverified_proof_count']}",
        f"- Active work items: {metric['active_work_items']}",
        f"- Itinerary coverage: {metric['covered_pathways']}/{metric['required_pathways']}",
        f"- Recommendation proof rate: {metric['recommendation_proved_rate']}",
        f"- Documentation checks: {metric['documentation_checks_passed']}/{metric['documentation_checks_total']}",
        f"- Verifier templates: {metric['verifier_template_count']} configured",
        "",
        "## Boundary",
        "",
        "This is a local read-only scorecard. It reports missing controls and drift but does not change project files, runtime configuration, external systems, or the pass/fail policy for the target score.",
    ])
    return "\n".join(lines) + "\n"


def build_pathway_audit_signal(audit, proofs):
    """Return a compact, safe-to-display local health signal for Audit v1.

    The snapshot deliberately excludes evidence paths, verifier commands, and artifact text.
    It is an operator signal, not production telemetry or an authorization to deploy.
    """
    project_proofs = [proof for proof in proofs if isinstance(proof, dict)]
    template_mismatches = sum(
        1 for proof in project_proofs
        if proof.get("template_check") and not proof["template_check"].get("valid")
    )
    canary = {
        "caught": sum(1 for proof in project_proofs if proof.get("canary_mutant_failed") is True),
        "missed": sum(1 for proof in project_proofs if proof.get("canary_mutant_failed") is False),
        "unavailable": sum(1 for proof in project_proofs if proof.get("canary_mutant_failed") is None),
    }
    metric = audit["metric_snapshot"]
    return {
        "schema_version": 1,
        "generated_at": audit["generated_at"],
        "project": audit["project"],
        "overall_score": audit["overall_score"],
        "target_score": audit["target_score"],
        "coverage": {"covered": metric["covered_pathways"], "required": metric["required_pathways"]},
        "recommendation_proved_rate": metric["recommendation_proved_rate"],
        "verifier_template_count": metric["verifier_template_count"],
        "template_mismatch_count": template_mismatches,
        "canary": canary,
        "drift_count": len(audit["drift_findings"]),
    }


def run_pathway_audit(args, paths):
    """Measure Pathway proof integrity without treating a below-target score as an error."""
    project_path = resolve_project_path(args, paths)
    if not project_path:
        raise ValueError("pathway-audit requires --project")
    project = Path(project_path).expanduser()
    project_name = project.name
    active_work = active_work_for_project(paths, str(project), project_name)
    # Audit one current outcome at a time. A project may have unrelated active work with a
    # different proof posture; mixing it into this outcome's readiness score would make the
    # selected work impossible to interpret or close on its own evidence.
    selected_work = active_work[:1]
    summaries = [work_status_summary(paths, item.get("work_id")) for item in selected_work]
    proofs = [
        proof for proof in read_ndjson(paths.proofs_path)
        if proof.get("project") == project_name or proof.get("project_path") == str(project)
    ]
    audit_approval_events = approval_events_for(paths)
    verified_proofs = [
        proof for proof in proofs if proof_credits_pathway(proof, audit_approval_events)]
    proof_integrity = audit_proof_integrity_snapshot(
        proofs, [item.get("work_id") for item in selected_work], audit_approval_events)
    carry_forward = [
        item for item in read_ndjson(paths.carry_forward_path)
        if item.get("project") == project_name or item.get("project_path") == str(project)
    ]
    surfaces = pathway_audit_document_surfaces(paths)
    drift_findings, doc_passes, doc_checks = pathway_audit_document_drift(surfaces)
    covered = sum(summary["itinerary_coverage"]["covered"] for summary in summaries)
    required = sum(summary["itinerary_coverage"]["total"] for summary in summaries)
    field_required = any(any(entry.get("pathway") == "field" for entry in summary.get("itinerary", [])) for summary in summaries)
    release_required = any(any(entry.get("pathway") == "release" for entry in summary.get("itinerary", [])) for summary in summaries)
    field_verified = any(proof.get("pathway") == "field" for proof in verified_proofs)
    release_verified = any(proof.get("pathway") == "release" for proof in verified_proofs)
    metric = compute_pathway_metric(paths)

    if not proofs:
        drift_findings.append({"id": "no-project-proofs", "severity": "warn", "surface": "proof ledger", "path": str(paths.proofs_path), "message": "No project proof records exist.", "refinement": "Log an executed verifier against the next completed pathway."})
    if selected_work and required and covered < required:
        drift_findings.append({"id": "open-itinerary-coverage", "severity": "warn", "surface": "work itinerary", "path": str(paths.work_items_path), "message": f"{required - covered} required pathway entries remain open.", "refinement": "Complete or explicitly justify the remaining itinerary entries with real evidence."})
    if selected_work and not carry_forward:
        drift_findings.append({"id": "missing-carry-forward", "severity": "warn", "surface": "carry-forward ledger", "path": str(paths.carry_forward_path), "message": "Active work has no project-scoped carry-forward receipt.", "refinement": "Record what changed, what is deferred, and the next pathway inputs."})
    if field_required and not field_verified:
        drift_findings.append({"id": "missing-field-receipt", "severity": "warn", "surface": "field proof", "path": str(paths.proofs_path), "message": "The itinerary requires field validation but no verified field proof exists.", "refinement": "Add a structured, locally verifiable field receipt in the field pathway slice."})
    if release_required and not release_verified:
        drift_findings.append({"id": "missing-release-proof", "severity": "warn", "surface": "release proof", "path": str(paths.proofs_path), "message": "The itinerary requires release evidence but no verified release proof exists.", "refinement": "Add rollback-aware release proof before closeout."})

    scores = [
        _audit_score(
            "proof integrity",
            25 * proof_integrity["verified_count"] / proof_integrity["proof_count"] if proof_integrity["proof_count"] else 0,
            25,
            f"{proof_integrity['verified_count']}/{proof_integrity['proof_count']} {proof_integrity['scope']} proofs verified",
        ),
        _audit_score("itinerary coverage", 20 * covered / required if required else 0, 20, f"{covered}/{required} required entries proved or N/A"),
        _audit_score("continuity", 15 if carry_forward else 0, 15, f"{len(carry_forward)} project carry-forward receipt(s)"),
        _audit_score("documentation alignment", 15 * doc_passes / doc_checks if doc_checks else 0, 15, f"{doc_passes}/{doc_checks} authority checks present"),
        _audit_score("field readiness", 10 if not field_required or field_verified else 0, 10, "not required" if not field_required else ("verified field proof" if field_verified else "field proof missing")),
        _audit_score("release readiness", 15 if not release_required or release_verified else 0, 15, "not required" if not release_required else ("verified release proof" if release_verified else "release proof missing")),
    ]
    refinements = sorted(drift_findings, key=lambda item: (item["severity"] != "critical", item["id"]))[:8]
    highest_value_refinements = [
        {"rank": index, "id": item["id"], "message": item["refinement"], "source": item["surface"]}
        for index, item in enumerate(refinements, 1)
    ]
    if not highest_value_refinements:
        highest_value_refinements.append({"rank": 1, "id": "maintain-scorecard", "message": "Keep the scorecard current with each Pathway contract change.", "source": "audit"})
    audit = {
        "generated_at": iso_now(),
        "project": project_name,
        "project_path": str(project),
        "target_score": 92,
        "overall_score": sum(item["score"] for item in scores),
        "pathway_scores": scores,
        "metric_snapshot": {
            "project_proof_count": len(proofs),
            "verified_project_proof_count": len(verified_proofs),
            "proof_integrity_scope": proof_integrity["scope"],
            "proof_integrity_proof_count": proof_integrity["proof_count"],
            "proof_integrity_verified_count": proof_integrity["verified_count"],
            "historical_unverified_proof_count": proof_integrity["historical_unverified_count"],
            "active_work_items": len(active_work),
            "selected_work_id": selected_work[0].get("work_id", "") if selected_work else "",
            "other_active_work_items": max(0, len(active_work) - len(selected_work)),
            "covered_pathways": covered,
            "required_pathways": required,
            "recommendation_proved_rate": metric["proved_rate"],
            "documentation_checks_passed": doc_passes,
            "documentation_checks_total": doc_checks,
            "verifier_template_count": len(VERIFIER_TEMPLATES),
        },
        "data_lineage": pathway_audit_data_lineage(paths),
        "drift_findings": drift_findings,
        "highest_value_refinements": highest_value_refinements,
    }
    md_path = dated_artifact_path(paths, f"pathway-audit-{safe_slug(project_name)}")
    html_path = md_path.with_suffix(".html")
    write_text(md_path, render_pathway_audit_report(audit))
    render_html(md_path, html_path)
    signal_path = paths.operator_intel / "pathway-audit-signals" / f"{safe_slug(project_name)}.json"
    write_json(signal_path, build_pathway_audit_signal(audit, proofs))
    audit["report"] = str(md_path)
    audit["html"] = str(html_path)
    audit["signal"] = str(signal_path)
    return {"records": scores, "findings": [], **audit}


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
    approval_events = approval_events_for(paths)
    effective_work_items = [
        current_work_item_view(paths, item, approval_events=approval_events)[0]
        for item in work_records["items"]
    ]
    for project in projects:
        name = project.get("name", "")
        work_items = [
            w for w in effective_work_items
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
    trivial_verifier_proofs = [p for p in proofs if p.get("trivial_verifier")]
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
        "trivial_verifier_count": len(trivial_verifier_proofs),
        "trivial_verifier_proofs": [
            {"proof_id": p.get("proof_id"), "pathway": p.get("pathway"), "project": p.get("project")}
            for p in trivial_verifier_proofs[:8]
        ],
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


def latest_recommendation_proof_status(latest_rec, proofs, approval_events=None):
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
    verified = [p for p in matches if proof_credits_pathway(p, approval_events)]
    if not verified:
        return "unverified"  # keystone: attested-only proofs don't read as proved in the cockpit
    return "stale" if all(proof_is_stale(p) for p in verified) else "proved"


def safe_latest_recommendation(latest_rec, proofs, approval_events=None):
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
        "proof_status": latest_recommendation_proof_status(latest_rec, proofs, approval_events),
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
    if latest_rec and latest_recommendation_proof_status(
            latest_rec, cockpit.get("proofs_for_status", []),
            cockpit.get("approval_events_for_status", [])) != "proved":
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
    cockpit_approval_events = approval_events_for(paths)
    cockpit["approval_events_for_status"] = cockpit_approval_events
    metric = cockpit.get("metric") or {}
    latest_rec = cockpit.get("latest_recommendation") or {}
    portfolio_items = (read_json_file(paths.portfolio_next_path, {"items": []}).get("items") or [])
    safe_rec = safe_latest_recommendation(latest_rec, proofs, cockpit_approval_events)
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
        f"- Trivial verifiers (no-op `--verify-cmd`): {cockpit.get('trivial_verifier_count', 0)}",
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
    approval_events = approval_events_for(paths)
    closed = []
    for item in items:
        if item.get("status") not in ("closed", "done") or item.get("tier") not in PATHWAY_TIERS:
            continue
        work_id = item.get("work_id")
        summary = (
            work_status_summary(paths, work_id, approval_events_override=approval_events)
            if work_id else None
        )
        current_item, current_summary = current_work_item_view(
            paths, item, summary=summary, approval_events=approval_events
        )
        if current_item.get("status") not in ("closed", "done"):
            continue
        # Calibration learns from the same current, corroborated itinerary that status and
        # routing expose. Persisted labels are history, not authority after an approval or proof
        # loses corroboration.
        projected = dict(current_item)
        if current_summary is not None:
            projected["itinerary"] = current_summary.get("itinerary", [])
        closed.append(projected)

    def canon_key(pathway):
        return (pathway_sort_key(pathway), pathway)  # name tiebreak keeps off-canon pathways deterministically ordered

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


# Evaluation harness (fast-follow dossier item 1). Recommendation-quality measurement earns a
# defensible precision claim only behind: a 3-FAMILY jury (correlated same-family judges collapse to
# one effective vote), kappa validation of the judges against a human label set BEFORE scaling, and
# position-swap + rubric-fingerprint bias controls. These are the deterministic, no-API core; the
# live judges plug in on top. (Verga et al. PoLL arXiv 2404.18796; Brown/Cai/DasGupta; Zheng 2023.)
def cohens_kappa(rater_a, rater_b):
    """Cohen's kappa: chance-corrected agreement between two raters (human vs one judge). Returns 0.0
    for empty or mismatched-length inputs; 1.0 when both raters concentrate on a single category."""
    n = len(rater_a)
    if n == 0 or n != len(rater_b):
        return 0.0
    po = sum(1 for a, b in zip(rater_a, rater_b) if a == b) / n
    categories = set(rater_a) | set(rater_b)
    pe = sum((rater_a.count(c) / n) * (rater_b.count(c) / n) for c in categories)
    return 1.0 if pe >= 1.0 else (po - pe) / (1 - pe)


def fleiss_kappa(count_matrix):
    """Fleiss' kappa: chance-corrected agreement across n raters. count_matrix rows are items, columns
    are categories, each entry the number of raters that chose that category for that item. Returns
    0.0 when there are no items or fewer than two raters per item."""
    num_items = len(count_matrix)
    if num_items == 0:
        return 0.0
    categories = len(count_matrix[0])
    raters = sum(count_matrix[0])
    # Fleiss assumes a fixed rater count and category set per item; reject ragged or inconsistent
    # input (or fewer than two raters) rather than miscompute or crash indexing a short row.
    if raters < 2 or any(len(row) != categories or sum(row) != raters for row in count_matrix):
        return 0.0
    item_agreement = [(sum(c * c for c in row) - raters) / (raters * (raters - 1)) for row in count_matrix]
    p_bar = sum(item_agreement) / num_items
    p_cat = [sum(row[j] for row in count_matrix) / (num_items * raters) for j in range(categories)]
    p_e = sum(p * p for p in p_cat)
    return 1.0 if p_e >= 1.0 else (p_bar - p_e) / (1 - p_e)


def kappa_reliability(kappa):
    """The dossier's go/no-go on a judge before scaling a precision claim."""
    if kappa < 0.4:
        return "unreliable"
    if kappa < 0.6:
        return "moderate"
    return "trustworthy"


def jury_verdict(votes, min_families=3):
    """Aggregate a heterogeneous LLM jury. Correlated (same-family) judges collapse to ONE effective
    vote — a family contributes its own majority verdict, or abstains if internally split — then the
    decision is the strict majority across FAMILIES. `family_diverse` is the dossier's >=3 distinct
    families bar; below it, a precision claim does not count (a one-vendor jury is one judge)."""
    by_family = {}
    for vote in votes:
        by_family.setdefault(vote.get("family", "?"), []).append(vote.get("verdict"))
    family_votes = {}
    for family, verdicts in by_family.items():
        tally = Counter(verdicts)
        top, count = tally.most_common(1)[0]
        if list(tally.values()).count(count) == 1:  # a strict within-family majority
            family_votes[family] = top
    across = Counter(family_votes.values())
    decision = None
    if across:
        top, count = across.most_common(1)[0]
        if count * 2 > sum(across.values()):  # a STRICT majority of the effective (family) votes
            decision = top
    known_families = [fam for fam in by_family if fam not in ("unknown", "?")]
    return {
        "verdict": decision,
        "distinct_families": len(by_family),
        "effective_votes": len(family_votes),
        "family_diverse": len(known_families) >= min_families,
        "tally": dict(across),
    }


def position_swap_resolve(verdict_order1, verdict_order2):
    """Position-bias control: a fair judge gives the same verdict with the options swapped. Return the
    agreed verdict, or None when the two orders disagree (position bias detected -> discard)."""
    return verdict_order1 if verdict_order1 == verdict_order2 else None


def rubric_fingerprint(rubric_text, model_ids):
    """Pin the rubric text + the (order-independent) set of judge model ids, so a change to either —
    judge drift or a rubric edit — is detectable as a different fingerprint."""
    payload = (rubric_text or "") + "\x00" + "\x00".join(sorted(model_ids or []))
    return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()


JUDGE_FAMILY_PATTERNS = [
    (("claude", "anthropic"), "anthropic"),
    (("gpt", "openai", "codex", "o1", "o3"), "openai"),
    (("gemini", "google", "bard"), "google"),
    (("glm", "zai", "zhipu"), "zhipu"),
    (("llama", "meta"), "meta"),
    (("mistral",), "mistral"),
    (("grok", "xai"), "xai"),
    (("deepseek",), "deepseek"),
]


def judge_family(judge):
    """Map a judge identity to its model FAMILY (vendor). Correlated same-family judges do not add an
    independent vote, so family — not judge-count — is what makes a jury's precision claim count."""
    low = (judge or "").strip().lower()
    for needles, family in JUDGE_FAMILY_PATTERNS:
        if any(n in low for n in needles):
            return family
    return "unknown"


def run_pathway_evaluate(args, paths):
    evals = read_ndjson(paths.evaluations_path)
    if getattr(args, "summary", False):
        total = len(evals)
        correct = sum(1 for e in evals if e.get("verdict") == "correct")
        by_verdict = {}
        for e in evals:
            by_verdict[e.get("verdict", "?")] = by_verdict.get(e.get("verdict", "?"), 0) + 1
        external = {e.get("project") for e in evals if e.get("project") and e.get("project") != SELF_PROJECT}
        families = sorted({judge_family(e.get("judge", "")) for e in evals if e.get("judge")})
        known_families = [f for f in families if f != "unknown"]
        diverse = len(known_families) >= 3
        summary = {
            "metric": "recommendation precision (independent judgments)",
            "generated_at": iso_now(),
            "total": total,
            "correct": correct,
            "precision": round(correct / total, 3) if total else 0.0,
            "by_verdict": by_verdict,
            "external_projects_judged": len(external),
            "judge_families": families,
            "family_diverse": diverse,
            # The dossier's honesty gate: a precision number is a vibe until a >=3-family jury backs
            # it. Surface the status so the number is never mistaken for a validated claim.
            "precision_claim_status": (
                "validated (>=3 judge families)" if diverse
                else f"unvalidated (needs >=3 judge families; have {len(known_families)})"
            ),
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
        "improve", "compare", "portfolio-next", "rule-map", "cockpit", "pfos-cockpit", "work-start", "work-status", "work-log", "work-close", "work-cover", "work-daily", "approval-issue", "approval-invalidate",
        "proof-add", "proof-report", "pathway-trust", "pathway-next", "pathway-run",
        "pathway-pilot", "pathway-decision", "ingest-review", "pathway-metric", "pathway-audit", "tier-calibrate", "pathway-evaluate", "all"
    ])
    parser.add_argument("--claude-home", default=str(DEFAULT_CLAUDE_HOME))
    parser.add_argument("--codex-home", default=str(DEFAULT_CODEX_HOME))
    parser.add_argument("--projects-root", default=str(DEFAULT_PROJECTS_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--since-days", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check-write", help="Boundary check mode for a future write path.")
    parser.add_argument("--project", help="Project path for work-start.")
    parser.add_argument("--projects", help="Comma-separated projects for pathway-pilot.")
    parser.add_argument("--goal", help="User-visible outcome for work-start.")
    parser.add_argument(
        "--work-id",
        help="Shared outcome identifier; pathway-next pins its active selection when supplied.",
    )
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
    parser.add_argument("--canary-target", help="Optional changed file for a strict proof-canary; persisted only as a repository-relative path.")
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
    parser.add_argument("--release-receipt", help="approval-issue: exact release receipt JSON the single-use production approval binds to.")
    parser.add_argument("--ticket-id", help="approval-invalidate: exact AT- ticket to revoke append-only.")
    parser.add_argument("--consumer", help="approval-issue: exact root-bound consumer for a live release ticket.")
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
    elif args.subcommand == "approval-issue":
        result = run_approval_issue(args, paths)
    elif args.subcommand == "approval-invalidate":
        result = run_approval_invalidate(args, paths)
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
    elif args.subcommand == "pathway-pilot":
        result = run_pathway_pilot(args, paths)
    elif args.subcommand == "pathway-decision":
        result = run_pathway_decision(args, paths)
    elif args.subcommand == "ingest-review":
        result = run_ingest_review(args, paths)
    elif args.subcommand == "pathway-metric":
        result = run_pathway_metric(args, paths)
    elif args.subcommand == "pathway-audit":
        result = run_pathway_audit(args, paths)
    elif args.subcommand == "tier-calibrate":
        result = run_tier_calibrate(args, paths)
    elif args.subcommand == "pathway-evaluate":
        result = run_pathway_evaluate(args, paths)
    else:
        result = run_all(args, paths)
    print_result(result, args.json)
    if args.subcommand in APPROVAL_MUTATION_SUBCOMMANDS:
        records = result.get("records") if isinstance(result, dict) else None
        if result.get("findings") or not isinstance(records, list) or not records:
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
