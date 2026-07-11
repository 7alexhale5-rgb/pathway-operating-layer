# Proof Canary Observability

Date: 2026-07-11
Pathway work: W-20260711-pathway-operating-layer-harden-proof-canary-muta-c7a065
Pathway: observability

## Signal

`scripts/proof-canary-observability.py` reads the local proof ledger and writes a local JSON report. It intentionally emits counts, status, and an action only: no verifier command, absolute evidence path, or canary target path is copied into the report.

| Condition | Status | Operator Action |
| --- | --- | --- |
| A strict provenance-backed canary is ignored | `alert` | Inspect the verifier before accepting new proof coverage. |
| A legacy canary is ignored | `alert` | Treat it as historical risk until target provenance distinguishes relevance. |
| Invalid receipt or malformed ledger row | `watch` | Repair the receipt before relying on the signal. |
| No strict provenance-backed success yet | `watch` | Run a relevant strict canary after implementation. |
| Strict successes and no alerts | `pass` | Keep the report in the routine proof review. |

The receipt boundary from `DATA.md` remains authoritative: legacy records carry no provenance, while future records must separate `canary_target`, target source, selection reason, and the nullable mutation result.

## Local Runbook

```text
python3 scripts/proof-canary-observability.py \
  --proofs /Users/alexhale/Projects/memory-vault/operator-intelligence/proofs.ndjson \
  --out .planning/2026-07-11-proof-canary-target-selection/PROOF_CANARY_OBSERVABILITY.json
```

The report is local-only. A nonzero command exit means the ledger or report destination could not be read or written. An `alert` report is a signal, not a command failure; it preserves the condition for review.

## Current Observation

The initial local run records historical ignored canaries as an `alert`. Their receipts predate the target-provenance contract, so this report does not claim those mutations were relevant. The implementation and quality pathways must turn future strict results into provenance-backed observations.

## Verifier

```text
/bin/bash /Users/alexhale/Projects/pathway-operating-layer/.planning/2026-07-11-proof-canary-target-selection/verify-observability.sh
```

## Summary

The proof ledger now has a privacy-preserving local signal for ignored canary mutations, malformed receipts, and the absence of strict provenance-backed checks.

## What Changed

- Added a deterministic local JSON report for proof-canary status and counts.
- Separated legacy canary outcomes from future provenance-backed strict outcomes.
- Added a runbook that keeps the report local and exposes no command or target-path content.

## More Relevant

- Implementation must populate the four receipt fields so the report can distinguish strict checks from legacy history.
- Quality must assert that a relevant ignored mutation increments `strict_probe_ignored`.

## Less Relevant

- This slice does not add network alerts, hosted telemetry, or a new data store.
- Legacy false outcomes are not retroactively assigned a target or source.

## Next Pathway Must Use

- Preserve the report schema and its no-raw-command, no-canary-target-path output boundary.

## Do Not Do Yet

- Do not mark historical legacy false outcomes as relevant-target failures.
- Do not send this report outside the local operator environment.

## Open Decisions

- Whether a future scheduled local run is useful after the implementation and release gates are complete.

## Active Risk Overlays

- rollback
