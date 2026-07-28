# Selected-Work `pathway-next` Closeout

Date: 2026-07-18
Work ID: `W-20260718-pathway-operating-layer-scope-pathway-next-scori-81ef31`
Release state: local release candidate; no deployment or production mutation

## Outcome

`pathway-next --work-id <active-id>` now pins recommendation scoring, goal, contract, carry-forward, itinerary, persistence, and next command to that outcome. The default remains the newest exact project match. An explicit nested checkout under the requested project root is valid; unknown, closed, sibling, and unrelated work IDs fail closed without a recommendation row.

## Security

- Explicit selection validates canonical resolved-path containment.
- A nested project is accepted; a same-name sibling is rejected.
- Unknown or inactive selection returns `pathway-next-work-id-not-active` before report rendering or ledger persistence.
- No schema, secret, credential, network authorization, base-table access, or production surface was added.

Verification:

```text
python3 .planning/2026-07-17-selected-work-pathway-next-scoring/closeout/verify-closeout.py --gate security
```

## Field Proof

The real Koho collision is the operator canary:

- requested project root: `/Users/alexhale/Projects/koho`;
- explicitly selected nested work: `W-20260630-koho-consultops-1.13-oliver-sdr-ux-faithful-i-ad8a56`;
- competing newer Koho work remains active;
- returned work ID, Oliver SDR UX goal, and latest carry-forward all match the explicit ID;
- the selected outcome's nine stale measurements remain visible without importing older sibling measurements.

Verification uses the pure compute path over the live local ledger, so it proves real selection without appending another recommendation:

```text
python3 .planning/2026-07-17-selected-work-pathway-next-scoring/closeout/verify-closeout.py --gate field
```

## Observability

The JSON surface makes the boundary inspectable:

- success returns `work_id`, selected `karpathy_card.goal`, `latest_carry_forward.work_id`, ranked reasons, and `itinerary_coverage`;
- invalid selection returns the requested `work_id` plus one stable finding ID and no ranked recommendation;
- selected stale-measurement count appears in the quality reason.

Verification:

```text
python3 .planning/2026-07-17-selected-work-pathway-next-scoring/closeout/verify-closeout.py --gate observability
```

## Tech Debt

The change keeps one outcome-state boundary instead of adding another scoring model:

- `score_pathways` accepts one optional `active_summary`;
- one containment helper owns explicit project-boundary validation;
- project findings and bounded closed-outcome learning retain their documented broader scopes;
- `work-status`, `work-daily`, and `portfolio-next` retain aggregate reporting;
- there is no schema migration, compatibility adapter, fallback selector, or new dependency.

Verification:

```text
python3 .planning/2026-07-17-selected-work-pathway-next-scoring/closeout/verify-closeout.py --gate techdebt
```

## Release Readiness

The local release gate requires:

- deterministic 32-assertion selected-work conformance;
- aggregate-scoring mutation killed;
- `593/593` standard-library suite checks passing;
- CLI help smoke passing;
- whitespace/error scan passing;
- real Koho nested-selection canary passing.

Rollback is code-only: revert the selected-work commits. There is no stored-data migration or production state to repair. Deployment, merge, push, and work close remain separate gates.

Verification:

```text
python3 .planning/2026-07-17-selected-work-pathway-next-scoring/closeout/verify-closeout.py --gate release
```

## Summary

Selected-outcome scoring is now singular and explicitly pinnable, including the real nested Koho/ConsultOps boundary that exposed the defect.

## What Changed

- Added active, project-bound `--work-id` selection to `pathway-next`.
- Kept default newest-work selection backward compatible.
- Scoped selected goal, contract, carry-forward, itinerary, measurements, persistence, and next command to the same ID.
- Added fail-closed invalid-selection behavior and real-ledger verification.
- Updated Pathway instructions to keep the returned work ID pinned for later determine calls.

## More Relevant

- One explicit work identity across every outcome-scoped recommendation input.
- Nested-checkout containment and same-name sibling denial.
- Real Koho regression proof and immutable portfolio visibility.

## Less Relevant

- Scoring-weight changes.
- Schema or portfolio redesign.
- Production deployment.

## Next Pathway Must Use

- Release may publish only after the local release gate passes and an authorized merge/push decision is made.

## Do Not Do Yet

- Do not deploy, mutate production, rewrite historical ledger rows, or force-push.

## Open Decisions

- Whether to merge and push the local release candidate after review.

## Active Risk Overlays

- rollback
- incident-response
- human-gate
