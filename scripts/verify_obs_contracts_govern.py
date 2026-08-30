#!/usr/bin/env python3
"""Govern-gate verifier for the per-project observability contracts outcome.

Usage: verify_obs_contracts_govern.py /abs/receipt.ndjson
Re-measures: spec exists with the required sections, work_id binding, gate
conditions G1-G3 present, 5 phases, and the spec's PREMISE is still true of
the engine (the tradebot metric-set equality pin exists in source) so the
plan governs a real problem, not a stale one.
"""

import json, re, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def die(msg):
    print(f"FAIL: {msg}")
    sys.exit(3)


def require(cond, msg):
    if not cond:
        die(msg)


def main():
    rc = json.loads(Path(sys.argv[1]).read_text().strip())
    require(rc["gate"] == "obs-contracts-govern-gate", f"wrong gate {rc.get('gate')!r}")
    require(rc.get("work_id", "").startswith("W-"), "receipt missing work_id")
    spec = Path(rc["spec_path"])
    require(spec.is_absolute() and spec.exists(), f"spec missing at {spec}")
    text = spec.read_text()
    require(rc["work_id"] in text, "work_id absent from spec")
    for heading in (
        "## Goal",
        "## Locked design decisions",
        "## Gate metric",
        "## Phases",
        "## Out of scope",
        "## Verifier criteria",
    ):
        require(heading in text, f"spec heading missing: {heading}")
    for g in ("G1", "G2", "G3"):
        require(re.search(rf"^- {g}:", text, re.M), f"gate condition {g} missing")
    phases = len(re.findall(r"^### Phase ", text, re.M))
    require(
        phases == rc["phase_count"], f"{phases} phases != claimed {rc['phase_count']}"
    )
    engine = (REPO / "scripts" / "operating-layer.py").read_text()
    require(
        "OBSERVABILITY_METRIC_NAMES" in engine
        and "name_set != OBSERVABILITY_METRIC_NAMES" in engine,
        "engine no longer carries the tradebot pin — the spec premise is stale, re-govern",
    )
    print("PASS: obs-contracts-govern-gate re-measured clean")
    sys.exit(0)


if __name__ == "__main__":
    main()
