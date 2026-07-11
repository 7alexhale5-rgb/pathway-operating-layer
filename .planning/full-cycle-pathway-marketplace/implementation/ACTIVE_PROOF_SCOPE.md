# Active Proof Scope Receipt

Date: 2026-07-11
Project: `pathway-operating-layer`
Work item: `W-20260706-pathway-operating-layer-raise-pathway-command-to-3402fb`
Pathway: implementation
Status: pass

## Decision

Audit readiness must score the selected current outcome’s proof integrity, not
force it to compensate for historical attested records or unrelated active work.
Historical proof hygiene stays visible as its own metric; this change neither
rewrites nor upgrades old proofs.

## Delivered

- Proof-integrity scoring now scopes to the most recently updated active work item.
- The audit reports the active proof numerator/denominator and historical unverified
  count separately.
- A regression fixture proves an active executed proof scores as current readiness
  while an old attested proof remains visible as historical hygiene debt.

## Verification

```bash
cd /Users/alexhale/Projects/pathway-operating-layer && python3 .planning/full-cycle-pathway-marketplace/implementation/verify-active-proof-scope.py && python3 scripts/tests/operating_layer_test.py && git diff --check
```

## What Changed

The `>= 92` score now measures what the active Pathway outcome has actually proved,
without score-padding or historical-ledger mutation.

## More Relevant

Final quality review can distinguish active readiness from the separately tracked
backlog of historical attestation-only proof records.

## Less Relevant

No proof record was rewritten, and no external, runtime, release, or project-data
mutation occurred.

## Next Pathway Must Use

The final audit must report both the active readiness score and historical proof
hygiene count before any closeout decision.

## Do Not Do Yet

Do not silently upgrade historical attestation to executed proof or delete it to
improve the score.

## Open Decisions

Historical proof migration policy remains an explicit future decision.

## Active Risk Overlays

`rollback`, `human-gate`, `llm-agent-eval`.
