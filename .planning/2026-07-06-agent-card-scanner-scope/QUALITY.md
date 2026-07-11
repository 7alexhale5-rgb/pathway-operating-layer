# Agent-Card Scanner Scope Quality Receipt

Status: pass
Work item: W-20260706-pathway-operating-layer-fix-agent-card-scanner-s-c64f27
Pathway: quality

## Regression Gate

The main operating-layer test suite now contains a direct scanner-scope test
with `tenants`, `mcp-servers`, one legacy Codex automation, and one
manifest-backed `atlas-ceo` profile. It requires the card set and readiness
finding evidence to contain only `atlas-ceo`.

The quality verifier also reruns the implementation signal, data contract,
security boundary fixture, documentation verifier, focused main-suite scanner
regression, and whitespace check. Together these catch the original broad-folder
false blocker, an absent real profile, a reintroduced legacy automation, and a
symlink escape.

The broader shared suite currently has order-dependent failures in unrelated
compare and work-close tests. Those failures remain visible for their owning
work; this focused scanner proof does not treat them as passing results.

Verification command:

```bash
cd /Users/alexhale/Projects/pathway-operating-layer && python3 .planning/2026-07-06-agent-card-scanner-scope/verify-quality.py
```

## Summary

Status pass: the scanner-scope correction has a main-suite regression test and
an end-to-end local quality gate covering selection, readiness evidence, data,
security, observability, documentation, and formatting.

## What Changed

Added the direct helper/legacy exclusion regression test and a quality verifier
that reruns every local proof needed for the scanner correction.

## More Relevant

The work item can close only if this quality command continues to pass and the
shared ledger verifies the evidence.

## Less Relevant

No runtime synchronization, deployment, external send, or hosted quality
service is required for this local scanner change.

## Next Pathway Must Use

Use this quality gate as the closeout verifier and retain the zero-false-blocker
signal in the proof record.

## Do Not Do Yet

Do not expand into legacy automation scanning, push, deploy, mutate Hermes
runtime, change Slack, cron, launchd, or close the work item without the ledger
close command.

## Open Decisions

Whether a later automation scanner should have its own test corpus and quality
gate instead of sharing Hermes profile readiness checks.

## Active Risk Overlays

`llm-agent-eval`.
