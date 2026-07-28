# Governance Decision - Proof Canary Target Selection

Date: 2026-07-11
Pathway work: W-20260711-pathway-operating-layer-harden-proof-canary-muta-c7a065
Pathway: govern

## Decision

Replace the first-dirty-line fallback with relevance-aware target selection. An automatic canary may mutate only a changed, regular file inside the verification checkout when the verifier command explicitly names that file. If no relevant changed target can be established, the canary returns `None`; it must not mark an otherwise executed verifier trivial merely because unrelated workspace changes exist.

Add an optional explicit canary target for opaque verifier commands. It must resolve inside the verification checkout, be a regular non-symlink file, and contain a mutable changed line. An explicit target that cannot meet those conditions returns `None`, never mutates another file as a fallback.

## Metric And Acceptance Criteria

Primary metric: `unrelated_dirty_false_demotions`.

Acceptance target: `0` false demotions in the deterministic dirty-worktree fixture. An honest verifier that names its changed source must record `canary_mutant_failed: true`; the same verifier with only unrelated dirty files must record `None`, retain `trivial_verifier: false`, and remain eligible as an executed proof. A no-op verifier that ignores an explicitly relevant target must still record `canary_mutant_failed: false` and remain trivial.

## Cost And Risk

The safer default can reduce automatic mutation coverage for opaque shell scripts. That is intentional: inconclusive evidence is safer than mutating an unrelated file and reporting a false verifier failure. The explicit target restores a strict mutation check when the caller can name the source under test.

The implementation must preserve byte-for-byte restoration, refuse symlinks and paths outside the checkout, keep the existing time budget, and avoid any network or production behavior.

## Rollback

The change is contained to canary target selection and its tests. Reverting that selector restores the current first-dirty-line behavior without changing proof records, work-item coverage, or external services.

## Verifier

```text
/bin/bash /Users/alexhale/Projects/pathway-operating-layer/.planning/2026-07-11-proof-canary-target-selection/verify-govern.sh
```

## Summary

Proof canaries will distinguish an inconclusive dirty worktree from a verifier that ignored a relevant mutation, eliminating false trivial-verifier demotions while preserving strict checks for named targets.

## What Changed

- Recorded the relevance-aware selection rule and the optional explicit-target policy before implementation.
- Pinned a zero-tolerance metric for false demotions in the deterministic dirty-worktree fixture.
- Preserved the no-op, symlink, timeout, and byte-restoration safety expectations.

## More Relevant

- Implementation must retain `False` only for a relevant target that the verifier ignores, and use `None` when relevance cannot be established.
- Quality must cover the dirty-worktree, relevant-target, no-op, symlink, and restoration cases together.

## Less Relevant

- Creating a clean checkout is no longer the only way to prevent unrelated dirty files from blocking a valid proof.
- Broad worktree cleanliness is not evidence that a verifier exercised the artifact under review.

## Next Pathway Must Use

- Read this decision before changing `run_canary_mutant` or proof-record construction; preserve the distinction between `False` and `None`.

## Do Not Do Yet

- Do not weaken the trivial-command denylist, disable the mutation check globally, mutate an unverified target, or change any production or external integration.

## Open Decisions

- Confirm the final CLI spelling and receipt field for an explicit canary target while keeping existing proof-log calls backward compatible.

## Active Risk Overlays

- rollback
