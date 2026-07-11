#!/usr/bin/env python3
"""Exercise the scanner's local-root boundary against symlinked candidates."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
CLI = ROOT / "scripts" / "operating-layer.py"
ARTIFACT_DIR = ROOT / ".planning" / "2026-07-06-agent-card-scanner-scope"
RECEIPT = ARTIFACT_DIR / "SECURITY_RECEIPT.json"


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def main() -> int:
    if not (ARTIFACT_DIR / "SECURITY.md").is_file():
        return fail("missing SECURITY.md")

    temp = Path(tempfile.mkdtemp(prefix="agent-card-security-"))
    try:
        projects = temp / "projects"
        agents = projects / "agents"
        outside = temp / "outside-agent"
        outside.mkdir(parents=True)
        (outside / "manifest.json").write_text('{"name":"Outside","marker":"EXTERNAL_AGENT_MARKER"}\n', encoding="utf-8")
        profiles = agents / "hermes" / "profiles"
        profiles.mkdir(parents=True)
        (profiles / "linked-agent").symlink_to(outside, target_is_directory=True)
        marker = profiles / "linked-marker"
        marker.mkdir()
        (marker / "manifest.json").symlink_to(outside / "manifest.json")
        real = profiles / "real-agent"
        real.mkdir()
        (real / "manifest.json").write_text('{"name":"Real","rung":1}\n', encoding="utf-8")

        for name in ("claude", "codex", "out"):
            (temp / name).mkdir()
        command = [
            sys.executable, str(CLI), "agent-cards",
            "--claude-home", str(temp / "claude"),
            "--codex-home", str(temp / "codex"),
            "--projects-root", str(projects),
            "--output-root", str(temp / "out"),
            "--json",
        ]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return fail(f"agent-cards failed: {proc.stderr.strip()}")
        result = json.loads(proc.stdout)
        systems = {record["system"] for record in result.get("records", [])}
        if systems != {"real-agent"}:
            return fail(f"unexpected scanner candidates: {sorted(systems)}")
        cards_path = temp / "out" / "operator-intelligence" / "agent-capability-cards.json"
        cards_text = cards_path.read_text(encoding="utf-8")
        if "EXTERNAL_AGENT_MARKER" in cards_text or "outside-agent" in cards_text:
            return fail("scanner output contains external symlink content or path")
        if (temp / "out" / "agent-capability-cards" / "linked-agent.md").exists():
            return fail("scanner wrote a card for the symlinked candidate")

        receipt = {
            "status": "pass",
            "scanner_candidates": sorted(systems),
            "symlinked_candidates_rejected": True,
            "external_marker_emitted": False,
            "external_calls": False,
        }
        RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("PASS agent-card scanner security boundary verifier")
        return 0
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
