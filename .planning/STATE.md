---
timestamp: 2026-10-20
verified: 2026-10-20
---

# Pathway Operating Layer - Present State

Sources (all run 2026-10-20): `git log origin/main`; `git diff origin/main HEAD` in the main
checkout; `gh pr list` and `gh pr view 4`; `readlink` on the installed links; `grep` on
`~/.claude/settings.json` and `~/.codex/hooks.json`; the guard fed two JSON probes;
`wc -l` on the approvals ledger; `python3 ~/.claude/scripts/truth.py pathway-operating-layer`.

The 2026-08-17 version of this file (work ID `W-20260817-...-2064b8`, "1088/1088 checks",
"17.303ms p95", "ledger stayed at four lines") described a state that no longer exists. It is
in git history at `4c4dd9a`.

## Where the work lives

- **`origin/main` is idle.** Head is `4c4dd9a` (2026-10-04, PR #3). PRs #1 to #3 are merged:
  research-stack focus tags, a PR test workflow, and a research-focus call-site fix.
- **The live recovery work is on a branch, not on main.** PR #4, "Recover Pathway proof
  integrity with explicit approval hold", branch `codex/pathway-phase1-recovery`, is OPEN and a
  DRAFT, 27 commits ahead of `origin/main`, last updated 2026-10-20 16:36Z. Its own text says
  it stays a draft because fresh human authentication and the guard latency gate are incomplete.
  Its latest checks, read today: `test (3.9)` CANCELLED, `test (3.12)` FAILURE.
- The main checkout `~/Projects/pathway-operating-layer` is on that branch. The installed links
  `~/.claude/scripts/operating-layer.py` and `~/.claude/hooks/approval-issue-guard.py` resolve
  into that checkout, so the running system uses the branch's code, not `origin/main`'s. The
  branch's guard differs from main's (`git diff`: 60 lines added, 27 removed).

## Verified now

- `approval-issue-guard.py` is wired once in `~/.claude/settings.json` and once in
  `~/.codex/hooks.json`. It is not named in `~/.codex/config.toml`.
- Probe through the installed guard: a Bash command calling `operating-layer.py approval-issue`
  exits 2 (denied); `echo hi` exits 0.
- On `origin/main`, `PRODUCTION_SECURE_WAIVER_STATE` and `RELEASE_PRODUCTION_APPROVAL_STATE`
  read `CONFIGURED_AND_VERIFIED`, and `OBSERVABILITY_RUNTIME_VERIFIER_TRUST_STATE` reads
  `TRUSTED_VERIFIER_NOT_CONFIGURED`. On the branch it is no longer a literal: it reads
  `CONFIGURED_AND_VERIFIED` when the trusted-verifier digest set is non-empty and the contract
  has no errors, else `TRUSTED_VERIFIER_NOT_CONFIGURED` (`operating-layer.py` near line 2230).
  Its runtime value was not evaluated today.
- The approvals ledger `operator-intelligence/approvals.ndjson` holds 41 lines; the last event
  is a `consumed` on 2026-08-30 (`AC-d3f1a0a47c71`, kind `release-production-approval`).
- The branch's own suite count is not re-measured. A run of the suite against `origin/main` in
  a clean worktree timed out inside `pathway-trust` at 120 seconds, so it gave no number.
  `CLAUDE.md` on `origin/main` states 1192 checks and on the branch 1389; both are carried
  forward, unverified.

## Carried forward, unverified

- The branch description's claims (production refuses protected approval issuance until an
  independently authenticating authority exists; 1432 passed and 4 failed before the final
  receipt repair; guard p95 108.286ms against a 50ms limit under load). They are the PR author's
  statements from its body, not measured today.
- The 2026-08-17 follow-up queue: `work-close` omitting the closed `work_id`, the
  attestation-only proof migration backlog, and a second-model-family review of the authority
  code. No commit message on either ref says these were closed.

## Guardrails

- Keep audit scoring read-only and local.
- Never edit the two state constants to make a number go green.
- Stamp this file with its own date on every edit.
