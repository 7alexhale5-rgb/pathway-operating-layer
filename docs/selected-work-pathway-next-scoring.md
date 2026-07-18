# Selected-Work Scoring for `pathway-next`

Decision status: accepted. Runtime conformance is verified separately; this ADR does not claim that an unreleased local change is deployed.

## The Answer

`pathway-next` chooses one active work item, and that same work ID must own every outcome-scoped signal used to rank its next pathway. When `--work-id` is supplied, that active item is selected even if it is not the newest. An older active outcome can remain visible in work and portfolio reporting, but its coverage, controls, stale measurements, missing evidence, or carry-forward state must not change the selected outcome's recommendation.

Current project findings and bounded learning from closed outcomes remain project-scoped. Pathway trust and the global proof metric remain system-scoped. This is a scoping correction, not a new scoring model.

## Operator Invariant

For one `pathway-next` result, these values share one selected work ID:

- returned `work_id`;
- goal, tier, outcome profile, and risk overlays;
- pathway coverage and required itinerary;
- open controls, stale measurements, and missing evidence;
- carry-forward and itinerary override;
- closeout readiness;
- ranked outcome-state reasons;
- the work ID embedded in the generated next command.

If two older active outcomes change while the selected item is unchanged, all normalized values above remain unchanged. Recommendation IDs and timestamps are excluded because persistence intentionally increments them.

## Delivered Contract

The selected-work data contract is:

```text
active_items = active_work_for_project(project)
selected_item = active_items.by_id(work_id) if work_id else active_items[0]
active_summary = work_status_summary(selected_item.work_id) if selected_item else None
ranked = score_pathways(..., active_summary, project_findings, project_learning, ...)
```

`score_pathways` should accept a singular optional summary, named `active_summary`. The name makes aggregation a type-shape error in ordinary review instead of a valid-looking list operation.

### Selected outcome input

| Field | Empty/no-active value | Scoring behavior |
| --- | --- | --- |
| `pathway_coverage.seen` | `[]` | Controls foundation and completeness reasons |
| `pathway_coverage.proved` | `[]` | Counts only selected proof coverage |
| `itinerary` proved/N/A entries | `[]` | Counts only selected required coverage |
| `open_controls` | `[]` | Adds `+50` only for selected controls |
| `stale_measurements` | `[]` | Adds `+5` per selected stale measurement |
| `missing_evidence` | `[]` | Adds `+4` per selected measurement without evidence |
| summary presence | `None` | Uses untracked foundation nudges, not tracked foundation weights |

The scorer must not infer a work ID. `compute_pathway_next` selects the item and passes the matching summary.

### Project and system input

These inputs intentionally remain broader than the selected outcome:

| Input | Scope | Reason |
| --- | --- | --- |
| operating-layer and project-local findings | Project | Current live risks must cross outcome boundaries |
| bounded closed-outcome learning | Project history | Demonstrated capability may dampen future urgency |
| Pathway trust | System | Changes recommendation confidence, not pathway ownership |
| global proof/recommendation metric | System | Changes autonomy guidance, not pathway score |

### Portfolio input

`work-status`, `work-daily`, dashboards, and `portfolio-next` continue to aggregate all relevant active work. They do not use the singular outcome scorer to answer portfolio-health questions.

## Selection And No-Active Behavior

Without `--work-id`, active work remains ordered by `updated_at` descending and the first item is selected. With `--work-id`, `pathway-next` must find that active ID within the selected project boundary; a nested checkout under the requested project root is valid, while a sibling is not. An unknown, closed, or different-project ID fails closed without rendering or persisting a recommendation.

When there is no active work:

- `work_id` and `active_summary` are absent;
- `has_active_work` is false;
- the existing untracked foundation nudges remain in force;
- the command continues to propose `work-start`;
- project findings may still rank a current live problem above a weak foundation nudge.

## Required Regression Corpus

The implementation is not complete until a deterministic test proves all of these:

1. Older `17` stale measurements do not affect selected work with `0` stale measurements.
2. Two selected stale measurements produce exactly `+10` and a reason naming `2`.
3. Older missing-evidence records do not affect selected work.
4. Two selected missing-evidence records produce exactly `+8` and a reason naming `2`.
5. An older control has no effect; a selected control adds its exact reason and target score.
6. Older govern/research coverage does not satisfy selected foundations or itinerary.
7. A current project security finding retains its score and reason.
8. Changing only non-selected work leaves normalized ranking, recommendation, confidence, identity, itinerary, closeout, and autonomy unchanged.
9. One persisted result names the selected work in its recommendation row and next command.
10. Older work remains visible through work-status and portfolio-next.
11. `--work-id` selects the matching older active outcome—including one owned by a nested checkout—and scopes goal, contract, carry-forward, measurements, persistence, and next command to it.
12. Unknown, closed, and different-project IDs create no recommendation row.
13. The full standard-library suite passes.

Seed older-work records directly in isolated fixtures. Do not use `work-log` for the older mutation because it updates `updated_at` and changes which item is selected. Compare pure compute output before persistence; persisted recommendation IDs are expected to differ.

## Control Safety

A live central-ledger audit found three open controls. Each belongs to its project's selected active outcome, so singular scoring does not suppress a current control. If a future work-local control is genuinely project-wide, promote it to a current project finding with an evidence path the project-scoping function recognizes.

This contract does not add control-scope fields, rewrite controls, close older outcomes, or weaken project-finding escalation.

## Verification

Documentation verification:

```text
python3 /Users/alexhale/Projects/pathway-operating-layer/.planning/2026-07-17-selected-work-pathway-next-scoring/docs/verify-docs.py
```

Pre-implementation research evidence:

```text
python3 .planning/2026-07-17-selected-work-pathway-next-scoring/research/verify-research.py
```

Runtime conformance after implementation:

```text
python3 scripts/tests/operating_layer_test.py
python3 .planning/2026-07-17-selected-work-pathway-next-scoring/implementation/verify-selected-work-scoring.py
```

The research verifier deliberately binds to the before-fix seam and live Koho evidence. Implementation must add the named conformance verifier before release rather than claiming the research check proves the new runtime.

## Compatibility And Rollback

No ledger schema, existing work item, proof, control, carry-forward record, or portfolio report is migrated. The expected runtime change is a singular scorer parameter and focused tests. Reverting that call boundary restores prior aggregate scoring without changing stored data.

No deployment, external send, production flag, data migration, or work close is authorized by this ADR.

## Summary

This ADR removes the recurring ambiguity between outcome scoring and portfolio health: one selected summary drives `pathway-next`; an explicit active work ID pins that selection; project findings and portfolio reporting keep their broader scopes.

## What Changed

- Documented the singular `active_summary` contract and exact no-active behavior.
- Defined fail-closed explicit selection for active work IDs.
- Captured the eleven-case regression corpus and deterministic fixture rules.
- Recorded which project, system, and portfolio inputs intentionally remain broader.
- Preserved the live-control and rollback boundaries.

## More Relevant

- Singular selected-summary input.
- Exact stale, missing-evidence, control, coverage, and identity assertions.
- Project-finding preservation and portfolio independence.

## Less Relevant

- New control-scope schema.
- Scoring-weight or portfolio-priority redesign.

## Next Pathway Must Use

- Data must verify the singular `active_summary` contract, null/no-active behavior, and deterministic fixture records before implementation changes the scorer.

## Do Not Do Yet

- Do not change scoring weights, portfolio aggregation, or control schema.
- Do not deploy, release, mutate production, close work, or edit historical ledger records.

## Open Decisions

- None for this bounded contract. Resolved-local-finding filtering remains a separate outcome.

## Active Risk Overlays

- privacy-evidence
- rollback
- incident-response
- human-gate
