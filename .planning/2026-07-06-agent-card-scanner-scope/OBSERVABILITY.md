# Agent-Card Scanner Scope Observability

Status: pass
Work item: W-20260706-pathway-operating-layer-fix-agent-card-scanner-s-c64f27
Pathway: observability

## Signal

`scanner-scope-observability.py` runs the real local `agent-cards` command
against the governed fixture and writes `SCANNER_SCOPE_SIGNAL.json`. The signal
contains the selected system names, missing real profile names, and the primary
metric `agent_cards_scope_false_blockers`.

## Baseline Alert

Before the scanner-scope implementation, the signal reports `alert` with three
false blockers: `tenants`, `mcp-servers`, and `legacy-job`. It also reports the
real `atlas-ceo` profile as missing. This is expected evidence of the failure,
not a passing product result.

The implementation must rerun the same script with `--expect pass`; success is
one selected `atlas-ceo` record, zero false blockers, and no missing real
profiles. The signal is local and writes no central ledger or external system.

## Runbook Delta

1. Run `scanner-scope-observability.py --expect alert` to reproduce the
   pre-fix baseline.
2. Implement the manifest-backed candidate selection from the data contract.
3. Run `scanner-scope-observability.py --expect pass` and preserve its JSON
   output as the implementation and quality proof input.
4. If the metric rises above zero or the profile disappears, treat the scanner
   correction as regressed and keep the agent readiness warning scoped.

Verification command:

```bash
cd /Users/alexhale/Projects/pathway-operating-layer && python3 .planning/2026-07-06-agent-card-scanner-scope/verify-observability.py && git diff --check
```

## Summary

Status pass: a local structured signal now exposes the scanner's real
pre-fix false blockers and missing Hermes profile on every fixture run.

## What Changed

Added a repeatable alerting baseline, JSON signal, and runbook for converting
the same fixture to a passing post-implementation proof.

## More Relevant

Implementation must turn this exact signal from `alert` to `pass` without
removing the real incomplete profile from the readiness finding.

## Less Relevant

No hosted telemetry, pager, runtime profile mutation, external API, or deploy
is needed for this bounded local scanner correction.

## Next Pathway Must Use

Use the same signal with `--expect pass` after manifest-backed profile selection
is implemented, together with the data and security fixtures.

## Do Not Do Yet

Do not silence the alert, edit central ledgers by hand, add external monitoring,
push, deploy, mutate Hermes runtime, or close the work item.

## Open Decisions

Whether this local signal should later be folded into the operating-layer
dashboard once the scanner has a stable automation-specific population.

## Active Risk Overlays

`llm-agent-eval`.
