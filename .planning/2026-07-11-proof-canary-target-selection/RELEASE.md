# Proof Canary Target Selection Release Rehearsal

Status: pass - local rehearsal only; no selector activation has occurred.
Date: 2026-07-11
Pathway work: W-20260711-pathway-operating-layer-harden-proof-canary-muta-c7a065
Pathway: release

## Release Decision

Do not activate or deploy anything in this step. The relevance-aware selector is not implemented yet, and the operating layer has no runtime feature flag for it. The release control is a small, isolated implementation commit after the implementation and quality evidence exist. It affects only the local operating-layer CLI, which is already referenced by the local `~/.claude/scripts/operating-layer.py` symlink.

No Hermes runtime profile, PFOS record, Slack surface, cron job, launchd service, remote API, or production system is part of this release.

## Rollout Shape

The future local canary is the deterministic dirty-worktree fixture. After implementation, it must demonstrate all of the following before the commit is treated as released:

1. A verifier explicitly naming the changed `value.txt` selects that file and returns `canary_mutant_failed: true` after mutation.
2. The same checkout with only unrelated dirty `unrelated.yml` returns `canary_mutant_failed: null`, `canary_target_source: unavailable`, and `trivial_verifier: false`.
3. An explicit relevant target with a verifier that ignores it returns `canary_mutant_failed: false` and remains trivial.
4. The receipt persists only a repository-relative target, stable source and reason values, and never the raw verifier token stream or an absolute path.
5. `python3 scripts/tests/operating_layer_test.py` passes, and the local proof-canary report records the new receipt shapes without copying commands or target paths.

The current observability report is intentionally still `alert` because it contains 157 legacy ignored mutations without target provenance. That history is a release signal to retain, not a reason to relabel old records.

## Rollback Plan

The repository is already dirty, so do not use a broad `git restore` on shared source files. Before commit, stage only the selector and focused-test hunks, save that staged patch, and reverse that patch if the rehearsal fails:

```bash
git diff --cached --binary -- scripts/operating-layer.py scripts/tests/operating_layer_test.py > /tmp/proof-canary-target-selection.patch
git apply --reverse /tmp/proof-canary-target-selection.patch
```

After a focused commit, rollback is:

```bash
git revert <proof-canary-target-selection-commit-sha>
```

After either rollback, rerun the full test suite and regenerate the local proof-canary report. Never hand-edit central operator-intelligence JSONL files to make the report look healthy.

## Stop Conditions

Do not release the implementation if any of these occurs:

- An unrelated dirty file still produces `canary_mutant_failed: false` for an honest verifier.
- A selected target is absolute, a symlink, outside the checkout, binary, unreadable, or not a changed mutable line.
- The regression test cannot prove byte-for-byte restoration after the canary runs.
- The proof receipt or observability report contains a raw command, target path, or unrelated changed-file inventory.
- The focused change cannot be isolated from existing dirty worktree edits.
- The full local test suite fails.

## Verification Command

```text
/bin/bash /Users/alexhale/Projects/pathway-operating-layer/.planning/2026-07-11-proof-canary-target-selection/verify-release.sh
```

## Summary

Release is constrained to a future local, reversible selector commit. This rehearsal activates no behavior and preserves the legacy alert until provenance-backed receipts exist.

## What Changed

- Defined a deterministic local canary and the exact receipt outcomes it must prove before release.
- Chose an isolated-commit rollback path that preserves unrelated dirty worktree changes.
- Recorded explicit stop conditions for selector safety, privacy, restoration, and test coverage.

## More Relevant

- Implementation must add the relevance-aware selector and receipt provenance fields without changing the local-only release boundary.
- Quality must run the dirty-worktree, explicit-target, unavailable-target, no-op, symlink, and restoration cases as the release canary.

## Less Relevant

- Remote rollout, hosted telemetry, runtime synchronization, and a scheduled report are outside this slice.
- Legacy ignored outcomes stay visible but are not retroactively assigned target provenance.

## Next Pathway Must Use

- Preserve the no-raw-command and no-canary-target-path observability boundary, then prove the five rollout conditions before a focused selector commit.

## Do Not Do Yet

- Do not deploy, push, synchronize Hermes runtime, change launchd or cron, send external messages, or close the work item.
- Do not use a broad `git restore` against dirty shared files.

## Open Decisions

- Whether an explicit `--canary-target` needs a release-note entry once implementation fixes its final CLI spelling.

## Active Risk Overlays

- rollback
