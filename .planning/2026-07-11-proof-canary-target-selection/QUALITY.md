# Proof Canary Target Selection Quality Record

Date: 2026-07-11
Pathway work: W-20260711-pathway-operating-layer-harden-proof-canary-muta-c7a065
Pathway: quality

## Independent Check

The quality verifier creates a fresh temporary git checkout and drives the public `proof-add` CLI. It proves that an explicit target outside the checkout and an unchanged in-repository target both remain unavailable. Neither target is mutated or persisted, and neither produces a false trivial-verifier result.

The repository suite adds the same assertions alongside the named-target, opaque-command, explicit-target, symlink, subdirectory, and byte-restoration cases. This is a separate negative test from the implementation fixture: it exercises the rejection boundary rather than the three successful selection shapes.

## Acceptance Criteria

- A direct verifier reference may mutate only its changed repository-relative file.
- An opaque verifier records an unavailable target and remains nontrivial.
- An explicit target outside the checkout records no target, leaks no absolute path, and never changes the external file.
- An explicit unchanged target records no target and never falls back to another changed file.
- The complete operating-layer test suite passes.

## Verification

```text
/bin/bash /Users/alexhale/Projects/pathway-operating-layer/.planning/2026-07-11-proof-canary-target-selection/verify-quality.sh
```

## Summary

Quality independently validates the target-rejection boundary, preventing explicit input from reintroducing an unrelated or unsafe mutation.

## What Changed

- Added regression coverage for outside and unchanged explicit target inputs.
- Added a CLI-level quality receipt that contains only safe unavailable-target outcomes.
- Re-ran the complete suite alongside the isolated negative fixture.

## More Relevant

- The release record can rely on the strict target boundary and the full suite result when deciding whether to make a focused local commit.
- The observability report can classify future unavailable receipts without target-path disclosure.

## Less Relevant

- External alerting, hosted CI, and automatic commit or deployment remain outside this local quality pass.

## Next Pathway Must Use

- Close only after confirming the updated release and documentation records remain accurate for the implemented local selector.

## Do Not Do Yet

- Do not deploy, push, synchronize runtime, change cron or launchd, send external messages, or alter legacy records.
- Do not relax the outside, symlink, or unchanged-target rejection rules.

## Open Decisions

- Whether future `proof-report` output should surface only the source and reason counts, rather than individual target paths.

## Active Risk Overlays

- rollback
