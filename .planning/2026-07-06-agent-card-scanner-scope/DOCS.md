# Agent-Card Scanner Scope Documentation Receipt

Status: pass
Work item: W-20260706-pathway-operating-layer-fix-agent-card-scanner-s-c64f27
Pathway: docs

## Published Operator Surface

`docs/agent-card-scanner-scope.md` explains the current alert, the intended
manifest-backed profile selection rule, and the exact before/after commands.
The README links to it from the documented Karpathy-method references.

## Accuracy Check

The runbook distinguishes the current fixture baseline (`--expect alert`) from
the required post-implementation condition (`--expect pass`). It preserves the
real profile's incomplete readiness result and states the local-only boundary.

Verification command:

```bash
cd /Users/alexhale/Projects/pathway-operating-layer && python3 .planning/2026-07-06-agent-card-scanner-scope/verify-docs.py && git diff --check
```

## Summary

Status pass: the scanner-scope correction now has a durable, linked operator
runbook that explains the alert and the exact proof for the eventual pass.

## What Changed

Added the scanner-scope runbook, a README link, and a verifier for the required
selection, safety, and before/after proof instructions.

## More Relevant

Implementation must make the runbook's `--expect pass` command succeed without
removing the real incomplete Hermes profile from the readiness finding.

## Less Relevant

This docs slice does not change scanner behavior, Hermes runtime state, any
external service, or the central operator ledger.

## Next Pathway Must Use

Use the runbook's post-implementation command sequence as the implementation
and quality verification baseline.

## Do Not Do Yet

Do not silence the alert, push, deploy, alter runtime profiles, mutate Slack,
cron, launchd, or close the work item.

## Open Decisions

Whether to promote this local runbook into a broader automation-readiness guide
after a separate automation-specific scanner exists.

## Active Risk Overlays

`llm-agent-eval`.
