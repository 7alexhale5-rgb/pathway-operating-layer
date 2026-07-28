# Agent-Card Scanner Scope Release Receipt

Status: pass
Work item: W-20260706-pathway-operating-layer-fix-agent-card-scanner-s-c64f27
Pathway: release

## Release Decision

Ship this as a local operating-layer scanner correction, not as a production
deployment. The change may edit only the local scanner logic, focused tests, and
project-local planning evidence. It must not mutate Hermes runtime profiles,
Slack surfaces, cron jobs, launchd services, central ledgers by hand, or any
external system.

## Rollout Shape

The rollout is a controlled local canary:

1. Add a scanner-scope regression fixture covering `agents/tenants`,
   `agents/mcp-servers`, legacy `codex/automations/*`, and one deliberately
   incomplete real agent candidate.
2. Update the scanner so readiness findings use explicit inclusion signals for
   real agent or autonomous automation candidates.
3. Run the focused scanner test first, then the full operating-layer suite.
4. Generate before/after evidence for the `agent-cards` output and confirm
   `agent_cards_scope_false_blockers` is `0`.
5. Leave any push, PR, deploy, or runtime synchronization for a separate human
   approval step.

## Rollback Plan

Before commit, rollback is:

```bash
git restore -- scripts/operating-layer.py scripts/tests/operating_layer_test.py
```

After commit, rollback is:

```bash
git revert <scanner-scope-commit-sha>
```

Rollback must also remove any generated scanner evidence for the failed attempt
from project-local `.planning/` only. Do not hand-edit
`/Users/alexhale/Projects/memory-vault/operator-intelligence/*.ndjson`.

## Release Gates

- `python3 scripts/tests/operating_layer_test.py` passes.
- The proof command guards the current first dirty diff line in `README.md`
  because Pathway's canary mutates the first changed line in the repo before it
  reaches untracked planning artifacts.
- A focused scanner-scope fixture proves false blockers are zero for
  `agents/tenants`, `agents/mcp-servers`, and legacy `codex/automations/*`.
- The same fixture proves a real incomplete agent candidate still produces an
  incomplete-readiness warning.
- The implementation remains stdlib-only and keeps current CLI layout.
- No runtime profile push, Slack send, cron mutation, launchd mutation, deploy,
  or external API call is required.

## Stop Conditions

Stop and do not ship the scanner change if:

- The fix suppresses a real incomplete agent candidate.
- The full operating-layer suite fails.
- The implementation needs path-specific allowlists instead of explicit agent
  candidate signals.
- The fix requires external state or production mutation to prove.
- The generated cards become less useful for actual agent surfaces.

## Verification Command

```bash
cd /Users/alexhale/Projects/pathway-operating-layer && grep -Fx '# 6. Start a measured real-project pilot cohort' README.md && python3 scripts/tests/operating_layer_test.py && python3 .planning/2026-07-06-agent-card-scanner-scope/verify-release.py
```

## Carry Forward

summary: Release is bounded to a local, reversible scanner correction with no deployment, runtime profile mutation, Slack send, cron mutation, launchd mutation, or external API call.

what_changed: Defined the rollout canary, release gates, stop conditions, and rollback commands before implementation.

more_relevant: Implementation must prove both halves of the release gate: zero false blockers for helper/legacy folders and preserved blocking for a real incomplete agent candidate. Proof logging must also guard the current first dirty diff line until the repo is clean, because Pathway's canary targets it.

less_relevant: Shipping, pushing, PR creation, runtime sync, or live Hermes dashboard changes are not part of this release pathway.

next_pathway_must_use: The next scanner implementation must use the release gates in this file as acceptance criteria and keep rollback one command away until the full suite passes.

do_not_do_yet: Do not push, deploy, mutate Slack, mutate Hermes runtime, edit launchd/cron, or close the work item.

open_decisions: Whether legacy Codex automations should get a separate automation-readiness scanner after this Hermes false-blocker fix.

active_risk_overlays: `llm-agent-eval`.
