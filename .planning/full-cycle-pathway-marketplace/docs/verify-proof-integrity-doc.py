#!/usr/bin/env python3
"""Verify the Pathway proof-integrity reference describes live local behavior."""

from __future__ import annotations

from pathlib import Path


ROOT = Path("/Users/alexhale/Projects/pathway-operating-layer")
DOC = ROOT / "docs" / "pathway-proof-integrity.md"
README = ROOT / "README.md"
ENGINE = ROOT / "scripts" / "operating-layer.py"


def main() -> int:
    text = DOC.read_text(encoding="utf-8")
    required = [
        "# Pathway Proof Integrity", "`pathway-audit`", "executed `--verify-cmd`",
        "xai-", "github_pat_", "HTTP bearer", "Preview `ready`",
        "Production `deployed`", "External `send-ready`", "External `sent`",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise SystemExit(f"proof-integrity doc missing: {missing}")
    if "docs/pathway-proof-integrity.md" not in README.read_text(encoding="utf-8"):
        raise SystemExit("README does not link the proof-integrity doc")
    source = ENGINE.read_text(encoding="utf-8")
    for token in ("pathway-audit", "validate_release_receipt", "authorization\\s*:\\s*bearer", "github_pat_"):
        if token not in source:
            raise SystemExit(f"engine no longer provides documented behavior: {token}")
    print("PASS proof-integrity documentation matches the local engine")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
