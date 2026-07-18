# Governance Decision — Selected-Work Scoring for `pathway-next`

Date: 2026-07-17
Pathway work: `W-20260718-pathway-operating-layer-scope-pathway-next-scori-81ef31`
Pathway: `govern`

## Decision

`pathway-next` will use one selected active work ID as the sole authority for outcome-scoped scoring. For this bounded change, "selected" means the active work ID that `compute_pathway_next` already resolves before scoring: the first item from the existing most-recently-updated active-work ordering. The selected work is the same work ID returned to the operator and named in the generated next command. Changing that selection policy or adding an explicit `--work-id` is a separately governed interface decision, not a prerequisite for stopping cross-outcome scoring leakage.

Only that work summary may contribute pathway coverage, itinerary coverage, open controls, stale measurements, missing evidence, and carry-forward state to the recommendation. Older active work remains independently visible through work status, daily, dashboard, and portfolio surfaces, but its outcome state must not alter the selected outcome's pathway ranking.

Project-scoped findings and bounded learning from closed outcomes remain project-scoped inputs. A current security or operational finding must therefore still influence the recommendation even when it is not attached to the selected work. A risk that must apply across outcomes belongs in the project finding surface; an old work control is not a safe substitute for that surface. Before release, research must inspect open controls on non-selected active work and promote any genuinely project-wide live blocker to a current project finding with provenance. Legacy unscoped controls remain work-scoped under the present data contract; no risk scope may be inferred from wording alone.

## Signal Boundary

| Scope | Signals | `pathway-next` treatment |
| --- | --- | --- |
| Selected outcome | pathway seen/proved state, required itinerary, open controls, stale measurements, missing evidence, carry-forward | Score from the selected active work ID only |
| Project | current local and operating-layer findings; bounded closed-outcome learning | Continue to score across the project |
| Portfolio | other active work IDs and their controls, measurements, evidence, and coverage | Keep visible in aggregate/operator surfaces; do not score into the selected outcome |

The decision boundary is behavioral rather than an implementation prescription. The smallest expected seam is at the `compute_pathway_next` call into the scorer: provide only the selected summary to outcome scoring. Prefer a singular `active_summary` scorer argument so accidental aggregation cannot recur. Leave multi-work collection to dashboard and portfolio paths. Do not silently change project-finding semantics or make the scorer choose a work ID implicitly.

## Metric And Acceptance Criteria

Primary metric: `cross_outcome_signal_leakage_count`.

Acceptance target: `0` leaked scoring signals from non-selected active work summaries in every deterministic regression case. A leaked signal is any non-selected work item's coverage, itinerary, control, stale measurement, missing evidence, or carry-forward state that changes a pathway score or reason for the selected outcome.

The quality gate must prove all of the following:

| Case | Fixture | Expected result |
| --- | --- | --- |
| `older-stale-ignored` | Selected work has `0` stale measurements; two older active outcomes have `17` total | Quality receives no stale-measurement bump or reason |
| `selected-stale-counted` | Selected work has `2` stale measurements; older work has any count | Quality receives the exact selected-work bump and reports `2`, not the project total |
| `control-boundary` | Older work has an open control; selected work first has none and then has one | The older control never ranks a pathway; the selected control does |
| `coverage-boundary` | Older work proved govern/research; selected work has no runs | Selected work still owes its own foundation gates and coverage |
| `project-finding-preserved` | A current project-scoped critical security finding exists | Security still receives the project-finding score |
| `identity-coherence` | Multiple active work IDs exist | Returned `work_id`, itinerary, carry-forward, score reasons, and generated next command all refer to the same selected work |
| `portfolio-visibility` | Older work retains stale measurements or controls | Work-status and portfolio reporting still expose that older outcome independently |
| `metamorphic-isolation` | Only a non-selected outcome is changed between two otherwise identical runs | The selected outcome's ranking, reasons, recommendation, confidence, itinerary, closeout state, and next command do not change |

The Koho regression fixture is the release-defining example: when the selected Koho work has zero stale measurements and older outcomes have seventeen, `pathway-next` must report zero stale measurements for recommendation scoring. The older outcomes must remain discoverable without contaminating the selected recommendation.

## Cost And Risk

The expected code change is small, but the safety boundary is important. Excluding old work controls can expose a modeling mistake if a genuinely project-wide live risk was recorded only inside an older outcome. The mitigation is explicit: research must audit non-selected open controls, and project-wide risk must be promoted with provenance to a current project finding before release. Tests must prove that current project findings still outrank normal routing when severity warrants it.

The change may alter existing recommendations for projects carrying several unfinished outcomes. That is the intended correction when the prior ranking was driven by another outcome. It must not close, delete, or rewrite those outcomes, and it must not change portfolio prioritization.

## Rollback

The implementation should remain a caller-level scoping change plus regression tests. Reverting that seam restores aggregate active-work scoring without modifying work ledgers, proof records, findings, or user data. No migration, deployment, external send, or production mutation is part of this decision.

## Verifier

```text
python3 /Users/alexhale/Projects/pathway-operating-layer/.planning/2026-07-17-selected-work-pathway-next-scoring/verify-govern.py
```

The verifier checks that this decision contains the selected-work authority, zero-leakage metric, complete signal boundary, regression matrix, cost/risk note, rollback, and Pathway carry-forward contract.

## Summary

The recommendation and the command that acts on it will share one outcome authority: the selected active work ID. Older active outcomes stay visible, while only current project findings remain intentionally cross-outcome.

## What Changed

- Pinned `cross_outcome_signal_leakage_count = 0` before implementation.
- Separated selected-outcome state from project findings and portfolio reporting.
- Defined the Koho `0` versus `17` stale-measurement case as a required regression.
- Required identity coherence across ranking, itinerary, carry-forward, returned work ID, and next command.

## More Relevant

- The selected active work ID is the recommendation's outcome authority.
- Project-scoped current findings must continue to influence safety routing.
- Non-selected open controls need a one-time scope audit before release; real project blockers must be promoted to project findings with provenance.
- Regression proof must cover staleness, controls, coverage, identity, and portfolio visibility together.

## Less Relevant

- Aggregate active-work health is not a valid proxy for the next step inside one selected outcome.
- Older outcome coverage cannot satisfy the selected outcome's itinerary.
- Rewriting the general scoring algorithm is unnecessary if the caller can provide the correct scope.

## Next Pathway Must Use

- Research must map every outcome-scoped field consumed by `score_pathways`, confirm the selected-work rule at the caller boundary, and preserve project findings plus portfolio visibility.

## Do Not Do Yet

- Do not implement or release the change until research proves the full input boundary and the quality fixture design.
- Do not close or rewrite older work items to hide the bug.
- Do not suppress current project findings, weaken safety escalation, deploy, or mutate production.

## Open Decisions

- A later governed change may add an explicit `--work-id` or fail-closed selection prompt for projects with multiple active outcomes; this outcome preserves the existing most-recently-updated selector and makes its downstream state coherent.
- Research must confirm whether any current aggregate-only operator surface reuses `score_pathways`; if so, preserve that surface with an explicit portfolio scope instead of changing its semantics accidentally.

## Active Risk Overlays

- privacy-evidence
- rollback
- incident-response
- human-gate
