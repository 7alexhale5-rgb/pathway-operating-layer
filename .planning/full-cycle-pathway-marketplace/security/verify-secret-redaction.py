#!/usr/bin/env python3
"""Verify that sensitive provider and bearer credential forms cannot persist in Pathway output."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
ENGINE = ROOT / "scripts" / "operating-layer.py"


def main() -> int:
    spec = importlib.util.spec_from_file_location("pathway_security_redaction", ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    values = [
        "xai-abcdefghijklmnopqrstuvwx123456",
        "github_pat_abcdefghijklmnopqrstuvwx123456",
        "bearer_abcdefghijklmnopqrstuvwx123456",
    ]
    raw = f"Authorization: Bearer {values[2]} XAI_API_KEY={values[0]} token={values[1]}"
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "receipt.json"
        module.write_json(output, {"payload": raw})
        persisted = output.read_text(encoding="utf-8")
    leaked = [value for value in values if value in module.redact(raw) or value in persisted]
    if leaked:
        raise SystemExit(f"credential redaction failed for {len(leaked)} test value(s)")
    print("PASS provider and bearer credentials are redacted before persistence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
