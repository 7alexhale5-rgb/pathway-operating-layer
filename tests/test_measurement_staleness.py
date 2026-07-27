#!/usr/bin/env python3
"""Staleness must supersede by GATE — the test that would have caught the 30x miss.

WHY THIS EXISTS
---------------
2026-07-26. An outcome (`W-20260627`) was fully verified — 7/7 coverage, every gate
proved or explicitly N/A — and still could not close. `stale_measurements()` reads
EVERY measurement ever logged for a work item and flags any row past its window.
Nothing supersedes an old row, so a fresh passing measurement for the same gate does
not retire the stale one. The outcome was permanently unclosable.

The first impact estimate was **"31 of 75 active outcomes are permanently
unclosable."** Simulating the proposed rule against the live ledger before writing
code refuted it: newest-per-`(pathway, gate)` frees **nothing**, newest-per-`gate`
frees **1**, newest-per-item frees **5**. Of the 31 blocked, **24 have a NEWEST
measurement older than 14 days** — genuinely dormant work the flag correctly
identifies. The claim conflated "blocked by a stale record" with "blocked by a
superseded record"; only the second is a defect. The estimate was off ~30x.

So this file pins BOTH properties, because fixing one by breaking the other is the
easy mistake:

  1. SUPERSESSION — a newer row for the same gate retires the older one, even when
     the two were logged under different pathways. (Currently FAILS.)
  2. DORMANCY — if the newest row for a gate is itself past its window, the outcome
     stays blocked. No blanket amnesty. (Currently passes; must keep passing.)

Property 2 is the one that matters. A change that frees more than a handful of
outcomes has loosened dormancy detection and is wrong.

Decision: memory-vault/decisions/2026-07-26-pathway-staleness-supersession-metric-lock.md

Usage:  python3 tests/test_measurement_staleness.py
Exit 0 = both properties hold.
"""
from __future__ import annotations

import datetime
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "scripts" / "operating-layer.py"

spec = importlib.util.spec_from_file_location("operating_layer", ENGINE)
ol = importlib.util.module_from_spec(spec)
sys.modules["operating_layer"] = ol
spec.loader.exec_module(ol)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name} — {detail}")


def ts(days_ago: int) -> str:
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def row(pathway: str, gate: str, days_ago: int, result: str = "pass", window: int = 14) -> dict:
    return {"work_id": "W-TEST", "pathway": pathway, "gate": gate,
            "timestamp": ts(days_ago), "result": result, "stale_after_days": window}


# ── property 1 · supersession ───────────────────────────────────────────────────

def test_supersession_same_gate_different_pathway() -> None:
    """The exact W-20260627 shape: an old `research/root-cause-target` row and a
    fresh `govern/root-cause-target` row. Same gate, different pathway. The old row
    must not block — keying on (pathway, gate) is what makes this frees-nothing."""
    rows = [row("research", "root-cause-target", 29),
            row("govern", "root-cause-target", 0)]
    stale = ol.stale_measurements(rows)
    check("supersession by gate (the W-20260627 shape)", not stale,
          "a fresh row retires the old one for the same gate" if not stale
          else f"{len(stale)} stale row(s) survive a fresh same-gate measurement")


def test_supersession_same_gate_same_pathway() -> None:
    rows = [row("govern", "govern-gate", 40), row("govern", "govern-gate", 1)]
    stale = ol.stale_measurements(rows)
    check("supersession within one pathway", not stale,
          "newest row wins" if not stale else f"{len(stale)} old row(s) still counted")


# ── property 2 · dormancy (must NOT regress) ────────────────────────────────────

def test_dormant_newest_row_still_blocks() -> None:
    """The anti-amnesty gate. If the NEWEST row for a gate is itself past its
    window, the work is dormant and must stay blocked. 24 live outcomes are in this
    state and a fix must not free a single one of them."""
    rows = [row("govern", "govern-gate", 60), row("govern", "govern-gate", 30)]
    stale = ol.stale_measurements(rows)
    check("dormancy still blocks", bool(stale),
          "an old newest-row keeps the outcome blocked" if stale
          else "AMNESTY BUG — dormant work would now close")


def test_one_dormant_gate_blocks_even_when_another_is_fresh() -> None:
    rows = [row("govern", "govern-gate", 0), row("quality", "quality-gate", 45)]
    stale = ol.stale_measurements(rows)
    check("a single dormant gate is enough to block", bool(stale),
          "fresh gates do not mask a dormant one" if stale
          else "a stale gate was masked by an unrelated fresh one")


def test_all_fresh_does_not_block() -> None:
    rows = [row("govern", "govern-gate", 0), row("quality", "quality-gate", 3)]
    stale = ol.stale_measurements(rows)
    check("all-fresh is not blocked", not stale,
          "no false positives" if not stale else "fresh rows wrongly flagged")


def test_respects_per_row_window() -> None:
    """20 days old with a 30-day window is fresh; with a 14-day window it is not."""
    ok = (not ol.stale_measurements([row("govern", "g", 20, window=30)])
          and bool(ol.stale_measurements([row("govern", "g", 20, window=14)])))
    check("per-row stale_after_days honoured", ok,
          "window comes from the row, not a constant")


def main() -> int:
    print("measurement staleness — supersession must not become amnesty\n")
    for fn in (test_supersession_same_gate_different_pathway,
               test_supersession_same_gate_same_pathway,
               test_dormant_newest_row_still_blocks,
               test_one_dormant_gate_blocks_even_when_another_is_fresh,
               test_all_fresh_does_not_block,
               test_respects_per_row_window):
        try:
            fn()
        except Exception as exc:
            check(fn.__name__, False, f"crashed: {exc}")

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n  {passed}/{len(RESULTS)} properties hold")
    if passed < len(RESULTS):
        print("  Failing supersession checks are the build list. A failing DORMANCY "
              "check means the fix went too far — that is worse than the bug.")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
