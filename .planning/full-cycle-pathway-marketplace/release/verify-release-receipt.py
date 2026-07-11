#!/usr/bin/env python3
"""Verify the local preview release receipt without invoking deployment tooling."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
ENGINE = ROOT / "scripts" / "operating-layer.py"
RECEIPT = ROOT / ".planning" / "full-cycle-pathway-marketplace" / "release" / "PREVIEW_RELEASE_RECEIPT.json"


def main() -> int:
    spec = importlib.util.spec_from_file_location("pathway_release_receipt", ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    errors = module.validate_release_receipt(receipt)
    if errors:
        raise SystemExit(f"preview receipt invalid: {errors}")
    if receipt["production_status"] != "not-deployed" or receipt["external_send_state"] != "not-sent":
        raise SystemExit("preview receipt claims a production mutation or external send")
    if module.release_receipt_supports_send(receipt):
        raise SystemExit("preview receipt must not satisfy a sent condition")
    print("PASS preview-ready receipt is local, not deployed, and not sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
