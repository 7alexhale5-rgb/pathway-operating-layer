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
- **Gap E — tier calibration — SHIPPED:** the heuristic `PATHWAY_TIERS` map is a guess; closed
  outcomes are evidence. New `tier-calibrate` command (`compute_tier_calibration`) measures, per tier
  across ALL closed outcomes, how often each pathway was proved vs marked N/A, and flags where the
  measured need diverges from the default — `docs` over-included, `security` under-included, etc.
  **Advisory only:** it never mutates the map (silently dropping a pathway would break the coverage
  guarantee); a human adopts changes by ADR. A tier under a 2-close floor makes no claim (fail-closed).
  Falsifiable gate (green): seeded "live" closes where docs is always N/A and security always proved
  yield docs=drop-candidate + security=add-candidate (measured divergence), while a sub-floor tier
  yields none. Test `test_tier_calibration_measures_defaults_from_closed_outcomes`. Dual second-model
  critic (Codex + GLM-5.2) on the diff — both flagged duplicate-counting (fixed: one status per
  pathway per outcome), plus raw-rate thresholds + deterministic sort. Proven live: demoable (4 closes)
  measures exactly its default; live (1 close) withholds under the floor.

## Post-audit (after A–E shipped): world-class verdict = NOT-YET, keystone fixed

A dual-critic adversarial audit (Codex + GLM-5.2, independent families) on the WHOLE system both
returned **NOT-YET**, converging on one root: **proof was self-attested theater.** Demonstrated live —
a junk file + the string `"lol yeah i totally ran the tests, trust me bro"` flipped a pathway to
`proved`. Everything gated on `proved` (coverage, proof rate, autonomy, learning, calibration) was
therefore standing on sand, and the whole thing was validated only by dogfooding itself (circular).

- **Keystone — proof realness — SHIPPED:** a pathway now reaches `proved` ONLY via a verifier the
  engine RE-EXECUTES (`--verify-cmd`, must exit 0 on a non-failing result); bare `--verified-by` is
  `attested` and cannot prove. Each proof records `verifier_strength` (executed/signed/attested),
  `exit_code`, `verify_command`, stdout + full-file artifact SHA-256. `compute_pathway_metric` counts
  only verified proofs, so autonomy can't be farmed by self-attestation. Dual-critic on the diff caught
  a residual hole — `--reviewer "<name>"` was the same forgery under a different flag — now closed
  (only `executed` proves; a name is not a verifiable receipt). Falsifiable gate (green, proven live):
  `--verified-by`/`--reviewer`/`--result fail` → stays `required`; a real exit-0 `--verify-cmd` →
  `proved`. Tests `test_proof_requires_real_verifier_not_freetext` + `test_autonomy_metric_counts_only_verified_proofs`. 311/311.

## Remaining roadmap to world-class (ranked, from the audit — NOT yet done)

- **P0 · circular validation — INSTRUMENTED, and the first signal is damning.** Built
  `pathway-evaluate` (records an independent judge's verdict per recommendation → precision, counts
  external/non-self projects). Ran `pathway-next` blind on 3 real external projects (consult-ops,
  advisory-board, prettyfly-os); an independent judge (Codex/GPT-5) scored the picks: **precision 0.0
  (0/3)** — consult-ops `wrong` (36 real findings buried under a generic govern/metric gate),
  advisory-board `late`, prettyfly-os `unnecessary` (research at MEDIUM confidence with ZERO signals).
  Test `test_pathway_evaluate_records_independent_verdicts_and_precision`; live report at
  `memory-vault/operator-artifacts/2026-06-30-pathway-evaluations.md`.
  **→ Recommender fix — SHIPPED, precision moved 0/3 → 3/3.** `score_pathways`: foundation gates
  dominate only with active tracked work; on an untracked project they drop to a +8 tiebreaker so real
  findings drive the pick. `recommendation_confidence`: level tracks evidence (not foundation-inflated
  score_gap) — zero signal now yields LOW, never the content-free medium. Re-ran the SAME 3 external
  projects, independently re-judged (Codex): **3/3 correct** — advisory-board `research/late → quality`
  (engages the AI-eval gap), prettyfly-os `research/medium → research/low` (honest zero-signal default),
  consult-ops `govern` confirmed correct (tracked outcome, govern-backed by real governance gaps).
  Dual-critic: Codex timed out (single-pass noted); GLM found a scaffolding-leak (completeness-nudge +
  learning reasons counted as evidence) — fixed via one `SCAFFOLDING_REASON_MARKERS` list. Test
  `test_recommender_engages_findings_over_foundation_on_untracked_project`. 321/321.
  **→ NEXT: the remaining P1/P2 below (trivial verifiers, store concurrency, statistical thresholds,
  learning-loop pathology, module split) and a larger external-precision sample (n=3 is a start, not proof).**
- **P1 · store robustness — DONE.** All store writes go through `_atomic_write` (tempfile + fsync +
  `os.replace`), so a killed process can no longer truncate the NDJSON store. (Lost-update races from
  two concurrent read-modify-write cycles remain out of scope for single-operator use.)
- **P2 · portability — DONE.** Defaults derive from `$HOME`/env; no hardcoded username. An existing
  install keeps its legacy store via auto-detection; a fresh clone gets `~/.pathway-operating-layer`.
- **P1 · learning-loop pathology — DONE.** The dampener now never suppresses a pathway carrying a live
  finding/control this turn (security with a fresh warning stays surfaced). Test
  `test_learning_dampener_never_suppresses_a_pathway_with_live_findings`.

### Fast-follow — now research-backed (see [`docs/research/fast-follow-dossiers.md`](../docs/research/fast-follow-dossiers.md))
Four targeted research dossiers turned the vague items into exact specs (and cut one):
- **autonomy gate** — implement **Wilson score LB (z=1.96) ≥ 0.5 with a hard floor n ≥ 10** (n=10→k≥8,
  n=20→k≥14, n=50→k≥31). Replaces the `0.5` point estimate; closed-form, one line, Jeffreys cross-check
  in tests. *This is the next move — fully specified.*
- **trivial verifier** — emit a per-proof **verifier receipt**: `verifier_source_sha256` (denylist
  `true`/`exit 0`/`echo`), `stdout_sha256` + byte floor, coverage∩diff > 0, assertion_count > 0, and a
  **canary mutant** (flip a byte in a changed line, re-run; a real verifier must now fail) — the keystone check.
- **evaluation** — a **3-family LLM jury + a ~20-pick Cohen's/Fleiss' κ check** before any precision
  claim; same-family judges don't count. (n=3 / one judge is not a number.)
- **bandit — CUT.** Research verdict: not justified at this data scale (need ~thousands of trials for 11
  arms). Instead *instrument the heuristic* — log score-vector + outcome, surface a rolling per-pathway
  win-rate, make the dampener an explicit ε-greedy knob; revisit only after ~100 logged outcomes.
- **still open** — module split; entropy-based secret redaction; per-test isolation (`check()` raises under pytest).

## Original scope (Gap A loop)

Ship **Gap A end-to-end with proof** (the one move from the eval). B–E are recorded above and
deferred to later loop turns. One thing, end-to-end, against a falsifiable number — Karpathy ladder.
