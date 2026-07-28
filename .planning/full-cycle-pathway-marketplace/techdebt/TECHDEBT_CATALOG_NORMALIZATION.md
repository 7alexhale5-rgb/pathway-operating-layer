# Canonical Pathway Catalog Normalization

Date: 2026-07-11
Project: `pathway-operating-layer`
Work item: `W-20260706-pathway-operating-layer-raise-pathway-command-to-3402fb`
Pathway: techdebt
Status: pass

## Decision

The highest-risk duplication was not executable code: the human-facing Pathway
catalog had multiple orders. The engine already used the governed catalog, but the
README and Codex skill could teach a different one. Those descriptions are now
normalized to one literal source value:

`govern, research, data, security, design, implementation, quality, field, observability, techdebt, release, docs`

## Delivered

- Added `CANONICAL_PATHWAY_CATALOG` beside the engine's canonical order.
- Added the catalog as a required audit token for every configured authority surface.
- Normalized the command guide, README table, Codex skill, Claude instructions,
  Codex instructions, Hermes instructions, and technical-operator profile.
- Added an aligned-documentation regression fixture so the audit proves both a
  deliberately drifted case and the zero-drift case.

## Real Local Result

`pathway-audit` now reports `24/24 authority checks present`, no catalog/document
drift, and an overall score of `78/100`. The remaining deduction is explicit
itinerary coverage, not a hidden cross-environment wording disagreement.

## Verification

```bash
cd /Users/alexhale/Projects/pathway-operating-layer && python3 .planning/full-cycle-pathway-marketplace/techdebt/verify-pathway-catalog.py && python3 scripts/tests/operating_layer_test.py && git diff --check
```

## What Changed

The audit can now detect the exact catalog-order drift that prompted this cleanup;
all audited sources agree with the router's catalog.

## More Relevant

Quality can use the stable zero-drift baseline while adding verifier-template and
hollow-proof fixtures that move the remaining score.

## Less Relevant

No project runtime, external system, deployment, release behavior, or authority
level changed in this cleanup.

## Next Pathway Must Use

Quality should preserve the canonical-catalog regression and focus on proof
templates and negative fixtures before treating the score target as enforceable.

## Do Not Do Yet

Do not use the audit score as an automatic release decision, change selected
projects, send anything externally, or close the work item.

## Open Decisions

The location for a future `>= 92` enforcement policy and the storage shape for
verifier templates remain intentionally open.

## Active Risk Overlays

`rollback`, `human-gate`, `llm-agent-eval`.
