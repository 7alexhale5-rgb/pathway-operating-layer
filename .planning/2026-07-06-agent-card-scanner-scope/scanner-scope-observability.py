#!/usr/bin/env python3
"""Emit a local before/after signal for the agent-card scanner scope fixture."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
CLI = ROOT / "scripts" / "operating-layer.py"
ARTIFACT_DIR = ROOT / ".planning" / "2026-07-06-agent-card-scanner-scope"
SIGNAL = ARTIFACT_DIR / "SCANNER_SCOPE_SIGNAL.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect", choices=("alert", "pass"))
    args = parser.parse_args()
    temp = Path(tempfile.mkdtemp(prefix="agent-card-scope-signal-"))
    try:
        agents = temp / "projects" / "agents"
        (agents / "tenants").mkdir(parents=True)
        (agents / "tenants" / "README.md").write_text("# Helper\n", encoding="utf-8")
        (agents / "mcp-servers").mkdir()
        (agents / "mcp-servers" / "README.md").write_text("# Helper\n", encoding="utf-8")
        profile = agents / "hermes" / "profiles" / "atlas-ceo"
        profile.mkdir(parents=True)
        (profile / "manifest.json").write_text('{"name":"Atlas CEO","rung":3}\n', encoding="utf-8")
        automations = temp / "codex" / "automations" / "legacy-job"
        automations.mkdir(parents=True)
        (automations / "automation.toml").write_text("schedule = \"daily\"\n", encoding="utf-8")
        for name in ("claude", "out"):
            (temp / name).mkdir()

        command = [
            sys.executable, str(CLI), "agent-cards",
            "--claude-home", str(temp / "claude"),
            "--codex-home", str(temp / "codex"),
            "--projects-root", str(temp / "projects"),
            "--output-root", str(temp / "out"),
            "--json",
        ]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            print(proc.stderr.strip(), file=sys.stderr)
            return 1
        result = json.loads(proc.stdout)
        actual = {record["system"] for record in result.get("records", [])}
        expected = {"atlas-ceo"}
        false_blockers = sorted(actual & {"tenants", "mcp-servers", "legacy-job"})
        missing_real_profiles = sorted(expected - actual)
        status = "pass" if not false_blockers and not missing_real_profiles else "alert"
        signal = {
            "status": status,
            "agent_cards_scope_false_blockers": len(false_blockers),
            "false_blocker_systems": false_blockers,
            "missing_real_profile_systems": missing_real_profiles,
            "selected_systems": sorted(actual),
            "expected_selected_systems": sorted(expected),
            "external_calls": False,
        }
        SIGNAL.write_text(json.dumps(signal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if args.expect and status != args.expect:
            print(f"expected {args.expect}, got {status}", file=sys.stderr)
            return 1
        print(f"PASS scanner scope signal: {status}")
        return 0
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
