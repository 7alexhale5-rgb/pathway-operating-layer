# Preview Release State Rehearsal

Date: 2026-07-11
Project: `pathway-operating-layer`
Work item: `W-20260706-pathway-operating-layer-raise-pathway-command-to-3402fb`
Pathway: release
Status: pass

## Decision

Release state is now explicit local data, not inferred from prose. A preview-ready
receipt is useful proof, but it is not a production mutation, a canary, a rollback,
or an external send.

## Receipt Contract

The validator requires distinct fields for preview, canary, production, rollback,
external send, and feature-flag state, plus deploy, verification, rollback artifacts,
and human approval. Production requires human approval, all artifact references, and
a rehearsed or executed rollback. `send-ready` cannot be claimed as `sent`.

## Rehearsed State

`PREVIEW_RELEASE_RECEIPT.json` is deliberately bounded to:

- preview: `ready`
- production: `not-deployed`
- external send: `not-sent`
- canary: `not-run`
- rollback: `ready`
- feature flag: `disabled`

No deployment command, feature-flag mutation, external send, or rollback action was
performed. The receipt is only a reversible local release-planning artifact.

## Verification

```bash
cd /Users/alexhale/Projects/pathway-operating-layer && python3 .planning/full-cycle-pathway-marketplace/release/verify-release-receipt.py && python3 scripts/tests/operating_layer_test.py && git diff --check
```

## What Changed

Release proof can now distinguish preview readiness from production deployment and
external sends, with rollback and human approval requirements enforced for production.

## More Relevant

Observability and quality can rely on typed release state instead of interpreting
“send-ready” or “preview” as evidence of a live mutation.

## Less Relevant

No actual release, canary, production deployment, rollback, feature-flag change, or
external send occurred.

## Next Pathway Must Use

Observability should consume the preview receipt as a local state signal and keep its
own evidence distinct from release state.

## Do Not Do Yet

Do not deploy, change flags, send externally, or mark production as deployed without
explicit human approval and a real rollback artifact.

## Open Decisions

Future work can add a receipt CLI and host-specific deploy adapters once a real
deployment target is in scope.

## Active Risk Overlays

`rollback`, `human-gate`, `llm-agent-eval`.
