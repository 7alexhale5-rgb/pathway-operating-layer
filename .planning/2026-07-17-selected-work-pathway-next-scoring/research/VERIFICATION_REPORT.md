# Research Verification Report — Selected-Work Scoring

Date: 2026-07-17
Work ID: `W-20260718-pathway-operating-layer-scope-pathway-next-scori-81ef31`

## Result

`PASS` — the dossier is planning-ready, every high-impact claim is tied to source or live-ledger evidence, and no unresolved blocker remains.

## Verifier

```text
python3 /Users/alexhale/Projects/pathway-operating-layer/.planning/2026-07-17-selected-work-pathway-next-scoring/research/verify-research.py
```

## Verified Claims

- `score_pathways` has one direct call site.
- The selected work identity is singular before scoring.
- Every active work summary is currently passed into that scorer.
- The scorer aggregates coverage, controls, stale measurements, and missing evidence across the collection.
- Project findings, closed-outcome learning, trust/autonomy, and portfolio aggregation are independent inputs or surfaces.
- Live Koho counts are selected `0`, older `9`, and older `8` stale measurements.
- The selected Koho outcome owns the live Supabase credential control.
- The target project has one active work item and no open controls, so the promotion audit has no blocker.
- All three current open controls globally belong to their projects' selected active work items.
- The dossier contains the complete carry-forward contract and regression plan.

## Independent Review

| Perspective | Result | Material contribution |
| --- | --- | --- |
| Architecture | PASS | Singular scorer contract; one call site; portfolio is independent |
| Product skeptic | PASS | Isolated-root metamorphic fixture; avoid `work-log` timestamp reselection |
| Security | PASS | No control-promotion blocker; preserve path-valid project findings |

## Limitations

- This is research proof, not implementation proof. The verifier intentionally confirms the current leakage seam so the next data and implementation pathways have a falsifiable target.
- Live ledger counts will eventually age; the Pathway proof record already applies its normal staleness window.
- One independent critic accidentally invoked the advisory command once, adding at most one central recommendation record without editing the repository.

## Sources

- `research/DOSSIER.md`
- `scripts/operating-layer.py`
- `scripts/tests/operating_layer_test.py`
- `/Users/alexhale/Projects/memory-vault/operator-intelligence/work-items.ndjson`
- `/Users/alexhale/Projects/memory-vault/operator-intelligence/pathway-measurements.ndjson`
- `/Users/alexhale/Projects/memory-vault/operator-intelligence/controls.ndjson`
- `/Users/alexhale/Projects/memory-vault/operator-artifacts/2026-07-18-pathway-next-koho.md`

## Summary

The research verifier binds the planning decision to both the exact source seam and the live Koho failure evidence.

## What Changed

- Converted source and ledger observations into an executable research check.
- Recorded all three independent reviews.

## More Relevant

- Singular selected-summary scoring.
- Live Koho zero-versus-seventeen regression.

## Less Relevant

- Selector redesign and control-schema expansion.

## Next Pathway Must Use

- Data must turn this boundary into a deterministic input/output contract before implementation.

## Do Not Do Yet

- Do not implement, deploy, or close the outcome from this research proof.

## Open Decisions

- Final singular parameter name remains for the data contract.

## Active Risk Overlays

- privacy-evidence
- rollback
- incident-response
- human-gate
