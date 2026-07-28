# Proof Canary Target Selection

Status: local implementation and quality verification complete; no focused release commit requested.

## The Answer

An automatic proof canary is safe to run in a dirty checkout only when the verifier itself directly names a changed, regular file inside that checkout. It must never select the first changed file merely because it is dirty. When the verifier does not establish a relevant target, the result is inconclusive, not trivial:

```json
{
  "canary_target": null,
  "canary_target_source": "unavailable",
  "canary_target_reason": "no_relevant_changed_file",
  "canary_mutant_failed": null
}
```

`false` is reserved for a relevant mutation that the verifier ignores. It is not a substitute for “no target was safely available.”

## Current State

The local operating-layer working tree now supports relevance-aware selection and `--canary-target`. The deterministic quality fixture has passed; no focused release commit has been requested. Existing proof receipts remain legacy records until new executions emit the target-provenance fields.

## Future Contract

The implementation adds these fields to executed proof receipts without changing proof IDs or artifact hashes:

| Field | Allowed Values | Meaning |
| --- | --- | --- |
| `canary_target` | repository-relative path or `null` | The selected regular changed file, never an absolute path. |
| `canary_target_source` | `explicit`, `verifier_reference`, `unavailable` | How the target was selected. |
| `canary_target_reason` | stable reason string | Why the selection succeeded or was unavailable. |
| `canary_mutant_failed` | `true`, `false`, `null` | The verifier caught a relevant mutation, ignored one, or no mutation ran. |

The planned `--canary-target` argument accepts a relative or absolute input but normalizes only a repository-relative path into the receipt. It rejects paths outside the checkout, symlinks, directories, unreadable or binary files, and files without a mutable changed line. Automatic selection may use `verifier_reference` only when the verifier command directly names a changed file.

Existing receipts without the three target-provenance fields remain legacy records. Readers must not invent a target, source, or reason for them.

## Privacy Boundary

Canary provenance fields must not contain the raw `--canary-target` input, an absolute target path, the parser's shell-token stream, or an unrelated changed-file inventory. The local observability report also omits verifier commands and target paths.

Existing proof receipts keep their separate verifier receipt fields, including the verifier command, for the existing proof audit trail. This target-selection change must not copy that command into canary provenance or observability output.

## Release And Rollback

The selector remains local-only: no deployment, remote flag, Hermes runtime synchronization, PFOS mutation, Slack send, cron change, or launchd change is needed.

Because the source checkout is already dirty, release the selector only in an isolated commit. Before commit, stage only the selector and focused-test hunks, save the staged binary patch, and reverse that patch if the canary fails. After commit, use `git revert <proof-canary-target-selection-commit-sha>`. Do not use a broad `git restore` on shared dirty files.

Before that commit, the deterministic dirty-worktree fixture must show all five release conditions:

1. A named relevant file returns `true` after mutation.
2. Unrelated dirt returns the unavailable `null` shape and remains nontrivial.
3. An explicit relevant target ignored by a no-op verifier returns `false` and remains trivial.
4. All persisted target values are repository-relative and provenance fields do not contain raw command or path input.
5. The full test suite passes and the local report recognizes the new receipt shapes without emitting commands or target paths.

## Verification

```text
/bin/bash /Users/alexhale/Projects/pathway-operating-layer/.planning/2026-07-11-proof-canary-target-selection/verify-docs.sh
```

## Summary

This document distinguishes the unimplemented legacy selector from the approved relevance-aware target contract, so a dirty checkout cannot be mistaken for proof that a verifier exercised the right file.

## What Changed

- Documented the unavailable-target result as distinct from a verifier that ignores a relevant mutation.
- Recorded the future receipt schema, privacy boundary, and compatibility treatment for legacy proofs.
- Bound release and rollback to an isolated local commit that preserves unrelated dirty worktree changes.

## More Relevant

- Implementation must add the selector and receipt fields exactly as described here.
- Quality must prove all five release conditions in the deterministic fixture.

## Less Relevant

- A hosted CI trust root, remote feature flag, scheduled report, and runtime synchronization are outside this target contract.

## Next Pathway Must Use

- A future focused commit must use the documented isolated rollback plan before it is treated as a released selector.

## Do Not Do Yet

- Do not release the selector or alter legacy proof records.
- Do not broaden a rollback to unrelated dirty source changes.

## Open Decisions

- Whether the final implementation should expose `canary_target_reason` values in `proof-report` after the receipt schema lands.

## Active Risk Overlays

- rollback
