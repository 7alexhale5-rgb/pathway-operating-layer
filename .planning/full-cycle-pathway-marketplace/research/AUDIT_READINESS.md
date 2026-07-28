# Pathway-Audit Research Addendum

Date: 2026-07-11
Project: `pathway-operating-layer`
Work item: W-20260706-pathway-operating-layer-raise-pathway-command-to-3402fb
Pathway: research
Status: pass

## Question

Are the existing local dossiers sufficient to implement the first
`pathway-audit` slice, or does a current unknown block its schema?

## Answer

They are sufficient. `GOVERN.md` fixes the first slice as a read-only
`pathway-audit --project <project> --json` command with these required fields:
`overall_score`, `pathway_scores`, `metric_snapshot`, `drift_findings`,
`highest_value_refinements`, `report`, and `html`.

`KARPATHY-SPEC.md` supplies the audit inputs: carry-forward continuity,
executed-verifier proof integrity, itinerary coverage, outcome profiles, risk
overlays, field receipts, release state, and wording/order/authority drift.
`SYSTEM-AUDIT.md` explains why each input must be measurable rather than a
prose claim. The existing `DOSSIER.md` adds local evidence for the risk and
proof requirements, including the warning against trivial verifier acceptance.

## Stabilized Implementation Contract

The first implementation is an observational scorecard, not a policy engine:

1. Read the selected project's current work item, proofs, carry-forward, and
   configured documentation surfaces.
2. Emit a score and one score entry per audit dimension; absent future features
   are deductions and listed refinements, not invented passing evidence.
3. Report drift separately from the score so a caller can see exactly which
   surface disagrees on pathway order, proof syntax, or authority boundaries.
4. Write Markdown and HTML operator artifacts beside the JSON result.
5. Exit zero when the command completed its measurement, even below `92`; a
   separate verifier or CI policy decides whether the score meets a threshold.

This exit behavior is deliberate: the governed goal needs a measuring surface
before the later verifier-template, field, release, trust-timing, and typed
overlay work can raise the score.

## Unknowns And Classification

| Unknown | Class | Effect on Audit v1 |
| --- | --- | --- |
| Exact `>= 92` threshold enforcement location | Warn | Audit reports score; CI/quality owns enforcement. |
| Python vs schema vs Markdown verifier templates | Warn | Report template coverage as missing until a later slice decides storage. |
| High-risk N/A approval receipt shape | Warn | Report the missing control; do not implement policy in Audit v1. |
| Historical trivial-verifier migration | Warn | Audit records present proof integrity; it does not rewrite history. |
| Audit JSON schema and required output fields | No blocker | Fixed by `GOVERN.md`. |
| Local sources for drift/proof checks | No blocker | Fixed by the existing source inventory and engine files. |

No blocker prevents implementation. The first slice must not attempt remote A2A
submission, external research, verifier-template storage, or field-send action.

## Sources

- `.planning/full-cycle-pathway-marketplace/GOVERN.md` — governed metric,
  required JSON fields, and first-slice priority.
- `.planning/full-cycle-pathway-marketplace/KARPATHY-SPEC.md` — continuity,
  proof-safety, overlay, and audit design requirements.
- `.planning/full-cycle-pathway-marketplace/SYSTEM-AUDIT.md` — proof-integrity
  failure modes the audit must expose.
- `.planning/full-cycle-pathway-marketplace/research/DOSSIER.md` — local
  stabilized claims, unknown classification, and implementation priorities.
- `scripts/operating-layer.py` — current CLI has no `pathway-audit` command,
  confirming this is a new, local measurement surface rather than a hidden mode.

## Verification

```bash
cd /Users/alexhale/Projects/pathway-operating-layer && python3 .planning/full-cycle-pathway-marketplace/research/verify-audit-readiness.py && git diff --check
```

## Summary

Status pass: existing local research is sufficient for a read-only
`pathway-audit` scorecard; no schema blocker prevents that first implementation
slice.

## What Changed

Classified the open decisions as warnings for later policy slices and fixed the
Audit v1 boundary: measure and report current integrity, drift, and missing
coverage without treating absent future controls as passing proof.

## More Relevant

Implementation must add the audit command and its seven-field JSON contract,
report zero/nonzero drift explicitly, and return a measurement even below the
target score.

## Less Relevant

External market research, A2A proof submission, template storage design,
high-risk N/A approval policy, and external field sends do not block Audit v1.

## Next Pathway Must Use

Implementation must start with the read-only audit scorecard, then let its
highest-value refinements guide template, field, release, trust, and overlay
work.

## Do Not Do Yet

Do not add remote handoff, send a field packet, make RAG authoritative, change
runtime profiles, deploy, force-push, or close the work item.

## Open Decisions

Keep the threshold-enforcement location and verifier-template storage format
open until the audit reports their actual score impact.

## Active Risk Overlays

`rollback`, `human-gate`, `llm-agent-eval`.
