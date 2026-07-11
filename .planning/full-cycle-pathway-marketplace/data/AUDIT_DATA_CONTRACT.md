# Audit Data Contract Receipt

Date: 2026-07-11
Project: `pathway-operating-layer`
Work item: `W-20260706-pathway-operating-layer-raise-pathway-command-to-3402fb`
Pathway: data
Status: pass

## Decision

Audit v1 now declares its local input lineage and validates its own JSON contract
before downstream tools rely on the score. This is a schema and boundary change,
not a migration or a new database.

## Lineage

The audit reads four authoritative local sources:

1. `proofs.ndjson` for executed-proof integrity.
2. `work-items.ndjson` for active itinerary coverage.
3. `pathway-carry-forward.ndjson` for continuity.
4. `pathway-recommendations.ndjson` for the recommendation proof-rate snapshot.

The audit emits `data_lineage.schema_version = "v1"` and validates score bounds,
unique dimensions, non-negative metric values, coverage consistency, and the exact
source-ledger set. It remains local and read-only for the selected project.

## Verification

```bash
cd /Users/alexhale/Projects/pathway-operating-layer && python3 .planning/full-cycle-pathway-marketplace/data/verify-audit-data-contract.py && python3 scripts/tests/operating_layer_test.py && git diff --check
```

## What Changed

The scorecard has a typed lineage contract. An impossible payload, such as more
covered pathways than required, is rejected instead of being treated as a valid
measurement.

## More Relevant

Quality and observability can validate the audit payload before using it in a
report, dashboard, or future CI policy.

## Less Relevant

No database, tenant data, migration, external API, runtime profile, or production
state changed.

## Next Pathway Must Use

Quality should use the typed audit contract when adding verifier-template and
hollow-proof checks.

## Do Not Do Yet

Do not turn these local ledgers into a shared database or infer tenant authority
from project names.

## Open Decisions

The long-term schema-storage and compatibility policy remains intentionally open.

## Active Risk Overlays

`rollback`, `human-gate`, `llm-agent-eval`.
