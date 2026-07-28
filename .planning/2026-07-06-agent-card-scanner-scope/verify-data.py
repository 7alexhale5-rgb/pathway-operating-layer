#!/usr/bin/env python3
"""Verify the data contract for the agent-card scanner scope correction."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
AGENTS = Path("/Users/alexhale/Projects/agents")
ARTIFACT_DIR = ROOT / ".planning" / "2026-07-06-agent-card-scanner-scope"
FIXTURE = ARTIFACT_DIR / "agent-card-scope-fixture.json"
RECEIPT = ARTIFACT_DIR / "DATA_RECEIPT.json"


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def main() -> int:
    if not (ARTIFACT_DIR / "DATA.md").is_file():
        return fail("missing DATA.md")
    try:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return fail(f"invalid scanner scope fixture: {exc}")

    records = fixture.get("records")
    if fixture.get("schema_version") != "agent-card-scope-v1" or not isinstance(records, list):
        return fail("fixture schema is not agent-card-scope-v1")
    by_id = {record.get("id"): record for record in records if isinstance(record, dict)}
    required = {
        "real-hermes-profile": ("hermes-profile", True, True),
        "helper-tenants": ("helper-folder", False, False),
        "helper-mcp-servers": ("helper-folder", False, False),
        "legacy-codex-automation": ("legacy-automation", False, False),
        "symlinked-agent-candidate": ("symlinked-candidate", False, False),
    }
    if set(by_id) != set(required):
        return fail(f"fixture records differ from contract: {sorted(by_id)}")
    for record_id, (kind, selected, incomplete) in required.items():
        record = by_id[record_id]
        if (record.get("kind"), record.get("expected_selected"), record.get("expected_incomplete")) != (kind, selected, incomplete):
            return fail(f"incorrect expected selection for {record_id}")

    manifest_path = AGENTS / by_id["real-hermes-profile"]["source_path"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest.get("rung"), int) or not (manifest.get("name") or manifest.get("display_name")):
        return fail("real Hermes manifest does not provide a usable agent record")
    for helper_id in ("helper-tenants", "helper-mcp-servers"):
        helper_readme = AGENTS / by_id[helper_id]["source_path"] / "README.md"
        if not helper_readme.is_file():
            return fail(f"missing real helper fixture input: {helper_readme}")

    selected = [record_id for record_id, record in by_id.items() if record["expected_selected"]]
    false_blockers = [record_id for record_id, record in by_id.items()
                      if not record["expected_selected"] and record["expected_incomplete"]]
    if selected != ["real-hermes-profile"] or false_blockers:
        return fail("fixture selection does not preserve one real agent with zero false blockers")

    RECEIPT.write_text(json.dumps({
        "status": "pass",
        "schema_version": fixture["schema_version"],
        "selected_records": selected,
        "agent_cards_scope_false_blockers": len(false_blockers),
        "real_manifest": manifest_path.relative_to(AGENTS).as_posix(),
        "external_calls": False,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("PASS agent-card scanner data contract verifier")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
