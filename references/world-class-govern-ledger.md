# Govern Ledger — /pathway → world-class

**Outcome:** W-20260629-pathway-operating-layer-elevate-pathway-to-world-2819f3
**Decision:** What falsifiable metric does the "world-class" upgrade move, and what is the gate number?

## The metric that matters (Gap A — the keystone)

**Today's failure:** `proved` means a proof *file exists*, not that a *verification passed*. A pathway
is marked covered by logging any artifact. Coverage is presence, not sufficiency.

**The world-class bar:** `proved` requires a **recorded verifier result**, not just an evidence file.

**Falsifiable gate (red→green):**
- `work-log --evidence <real file>` with **no** verifier recorded → pathway stays `required`
  (a bare artifact is NOT proof).
- `work-log --evidence <real file> --verified-by "<cmd>"` (a named verification) → pathway flips `proved`.
- A regression test asserts both, **fails on the pre-upgrade engine** (presence-only proves) and
  **passes after** the change. The native runner stays 100% green.

**Cost/risk:** Low. Extends the existing proof system (`--verified-by` / proof records) rather than
adding machinery; backward-compatible (bare `work-start` without a tier stays loose-tracking). No
external surface, no deploy.

## Backlog metrics (later loop iterations, recorded so they aren't lost)

- **Gap B — evidence-grounded recommender:** confidence rises from `low` when a repo carries live
  signals (seed a project with an open finding → `pathway-next` confidence ≠ `low`). Falsifiable.
- **Gap C — autonomy unlock — SHIPPED:** `pathway-next` now computes `suggested_autonomy_tier`
  (`recommend` | `execute-safe`) from the proof track record + trust + the pick's confidence, fresh
  each determine turn; the `/pathway` loop reads the field instead of re-deriving the Tier-2 rule.
  Falsifiable gate (green): a project with `proved_rate ≥ 0.5` AND trust = `pass` AND a high-confidence
  pick returns `execute-safe`; any signal short of the bar fails closed to `recommend`. Regression test
  `test_suggested_autonomy_tier_gates_on_proof_trust_confidence` (unit truth-table + end-to-end wiring).
- **Gap D — learning loop — SHIPPED:** closed outcomes now reweight the ranking. `score_pathways`
  reads the learning candidates persisted at `work-close` (`learned_pathway_closures`) and dampens
  each pathway a project has proved-and-closed (−3 per distinct close, capped at 3), bounded so it
  never overrides a finding/foundation/control — the recommender shifts toward pathways not yet
  demonstrated. No-op until the project has closure history. Falsifiable gate (green): with two
  closes proving implementation, the next pick shifts implementation→quality, the shift is
  attributable (the dampened row carries a "Demonstrated" reason), and it is project-scoped (another
  project's closes don't bleed). Test `test_learning_loop_closed_outcomes_reweight_rankings`; proven
  live (this repo's closes dampened govern/implementation/quality, surfacing `release` as next).
- **Gap E — tier calibration:** replace the heuristic tier→pathway map with measured defaults.

## Scope locked for THIS loop

Ship **Gap A end-to-end with proof** (the one move from the eval). B–E are recorded above and
deferred to later loop turns. One thing, end-to-end, against a falsifiable number — Karpathy ladder.
