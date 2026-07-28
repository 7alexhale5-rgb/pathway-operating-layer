#!/usr/bin/env python3
"""Validate that the pending field packet is explicitly no-send and not proof."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
FIELD = ROOT / ".planning" / "full-cycle-pathway-marketplace" / "field"
PACKET = FIELD / "FIELD_PACKET.md"
RECEIPT = FIELD / "FIELD_RECEIPT.json"
ARTIFACT = ROOT / ".planning" / "full-cycle-pathway-marketplace" / "research" / "AUDIT_READINESS.md"


def main() -> int:
    expected = sys.argv[1] if len(sys.argv) == 2 else "pending"
    if expected not in {"pending", "approved"}:
        raise SystemExit("usage: verify-field-packet.py [pending|approved]")
    packet = PACKET.read_text(encoding="utf-8")
    required = ["Alex Hale", "Send state: `not-sent`", "External action: none", "Exact Ask", "Review Questions"]
    missing = [item for item in required if item not in packet]
    if missing:
        raise SystemExit(f"field packet missing: {missing}")
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    if receipt.get("artifact_path") != str(ARTIFACT.relative_to(ROOT)):
        raise SystemExit("field receipt records the wrong artifact")
    if receipt.get("artifact_sha256") != hashlib.sha256(ARTIFACT.read_bytes()).hexdigest():
        raise SystemExit("field receipt artifact hash does not match")
    if receipt.get("send_state") != "not-sent" or receipt.get("external_action") != "none":
        raise SystemExit("field receipt claims an external action")
    if expected == "pending":
        if receipt.get("review_status") != "pending" or receipt.get("feedback") is not None:
            raise SystemExit("pending field packet has invalid proof state")
        print("PASS pending field packet is no-send and unproved")
    else:
        if receipt.get("review_status") != "approved" or not receipt.get("feedback"):
            raise SystemExit("approved field packet lacks a human decision or feedback")
        if "Approve Audit v1" not in receipt["feedback"] or "read-only" not in receipt["feedback"]:
            raise SystemExit("field receipt does not preserve the approved audit boundary")
        print("PASS approved field packet is no-send and review-backed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
