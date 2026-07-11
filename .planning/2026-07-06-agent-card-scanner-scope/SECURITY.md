# Agent-Card Scanner Security Review

Status: pass
Work item: W-20260706-pathway-operating-layer-fix-agent-card-scanner-s-c64f27
Pathway: security

## Threat Surface

`agent-cards` reads local candidate directories below the configured projects and
Codex roots, then writes derived capability cards under its configured output
root. Before this review, a direct directory symlink below `projects/agents`
could be treated as a candidate, and a symlinked profile marker could qualify a
directory. Either case could make a read-only scanner inspect a path outside its
configured inventory boundary.

## Decision

Reject symlinked candidate directories and symlinked inclusion-marker files
before the scanner reads contract text. Real directories with regular profile
documents remain eligible. This is a local filesystem boundary only: it does
not add network access, credential handling, runtime mutation, or output beyond
the existing configured output root.

## Proof

`verify-security.py` builds an isolated scanner fixture with one real incomplete
agent, one symlinked external candidate, and one candidate qualified only by a
symlinked marker. It proves that only the real candidate is scanned and that the
external marker is absent from emitted cards.

Verification command:

```bash
cd /Users/alexhale/Projects/pathway-operating-layer && python3 -m py_compile scripts/operating-layer.py && python3 .planning/2026-07-06-agent-card-scanner-scope/verify-security.py && python3 scripts/tests/operating_layer_test.py && git diff --check
```

## Summary

Status pass: the agent-card scanner now stays within configured local inventory
roots when candidate directories or profile markers are symlinks.

## What Changed

Added a symlink boundary guard in `scan_agents`, a focused regression test, and
an isolated end-to-end verifier that proves no external candidate is scanned.

## More Relevant

The implementation pathway must retain this boundary while adding explicit
candidate signals for Hermes agent directories and while excluding helper and
legacy automation folders.

## Less Relevant

No network, API-key, external-send, runtime-profile, Slack, cron, launchd, or
deployment control is in scope for this local scanner correction.

## Next Pathway Must Use

Use the isolated symlink fixture as a non-regression condition alongside the
release gate for zero helper/legacy false blockers and preserved real-agent
findings.

## Do Not Do Yet

Do not follow the historical generic `git restore` rollback command in
`RELEASE.md` while this shared worktree is dirty. Do not push, deploy, sync a
runtime profile, mutate Slack, cron, or launchd, or close the work item.

## Open Decisions

Whether a separate Codex-automation readiness scanner should exist after this
Hermes-oriented scope correction, rather than treating every legacy automation
folder as an agent candidate.

## Active Risk Overlays

`llm-agent-eval`.
