---
timestamp: 2026-09-01
work_id: W-20260830-pathway-operating-layer-per-project-observabilit-e65d28
phase: 3
gate: G3
---

# Agents specialist-fleet observability contract proof

## Summary

The Agents contract resolves from the Agents project identity and validates a
fresh, focused local runtime receipt for the specialist performance signal. The
verifier reads the real Agents ledger and instrument, runs a three-failure drill
through a temporary ledger, executes byte-identical watcher and report scripts in
an isolated temporary repo, and proves all seven receipt artifacts with Pathway's
mutation and restoration canaries.

This is a focused contract gate, not a production-monitoring claim. The watcher
is manually runnable but is not installed in either live Hermes cron store. The
receipt therefore uses `environment_class=test`, keeps `NO_PROMOTE`, and records
`MANUAL_NOT_SCHEDULED` in the alert and runbook evidence.

## What Changed

- Registered `contracts/observability/agents.json` with the specialist pass-rate,
  fail-streak, ledger, trap-transcript, alert, and runbook vocabulary.
- Replaced the remaining Tradebot question-ID and timestamp joins with a generic
  contract-driven drill correlation envelope and project-declared timestamp
  order.
- Bound the trusted focused verifier digest and all seven companion artifacts.

## Signal

The runtime signal is the real `_meta/subagent-performance.ndjson` ledger. At the
captured observation it had 22 evaluations, 18 passes, and no active fail streak.
A fresh read-only synthetic copy appended three failures for
`pathway-g3-drill`; the real report engine returned exit 3 and `FIRE-REVIEW`.
The real watcher bytes then returned exit 3 and wrote the alert into the isolated
temporary ops-lead inbox; no Agents checkout path was written.

## Verification

- Valid receipt: contract resolution `agents -> agents.json`, receipt validation
  has no errors, executed verifier exits 0, `proof_is_verified=True`, scope is
  `runtime`, and all seven mutation canaries fail and restore as expected.
- Violating receipt: changing the specialist failure mode to an undeclared value
  is refused before credit.
- The Agents checkout is read-only during this gate. Temporary drill data lives
  outside the repo and is deleted by the verifier.

## More Relevant

- PFOS can use the same contract mechanism later under its own active work item
  and its own project contract.
- The current Agents source verifier digest is recorded as provenance; the
  receipt-bound verifier is the dedicated seven-artifact verifier in this folder.

## Less Relevant

- The old Agents hiring-machine waiver remains honest history and is not changed.
- Automatic scheduling is outside this G3 focused contract proof.

## Next Pathway Must Use

- Phase 4 documentation must describe per-project contracts and preserve the
  focused-test versus scheduled-production distinction.
- The central outcome's own observability credit remains open because its work
  item resolves the `pathway-operating-layer` project, not the Agents contract.

## Do Not Do Yet

- Do not claim the Agents watcher is scheduled or production monitoring.
- Do not retroactively replace the closed Agents waiver with this focused proof.
- Do not reuse the Agents contract for PFOS.

## Open Decisions

- A future fresh Agents-scoped outcome may log this contract shape after live
  scheduling is deliberately approved and wired.

## Active Risk Overlays

- rollback
