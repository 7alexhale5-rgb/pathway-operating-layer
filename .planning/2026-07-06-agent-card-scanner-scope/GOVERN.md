# Agent-Card Scanner Scope Govern Receipt

Status: pass
Work item: W-20260706-pathway-operating-layer-fix-agent-card-scanner-s-c64f27
Pathway: govern

## Decision

The agent-card scanner should score real agent or automation candidates only. It
must keep blocking incomplete real agent cards, but it must not treat active
Hermes profile readiness as blocked because of broad helper folders or legacy
automation folders that are not the active Hermes profile fleet.

## Metric

Primary metric: `agent_cards_scope_false_blockers`

Target: `0`

Definition: when scanning the fixture that reproduces the Hermes failure mode,
the `agent-cards-incomplete-readiness` finding must contain no evidence for:

- `projects/agents/tenants`
- `projects/agents/mcp-servers`
- legacy Codex automations under `codex/automations/*`

while still containing evidence for a deliberately incomplete real agent
candidate.

## Acceptance Criteria

- Preserve the warning for a real incomplete agent candidate.
- Exclude non-agent helper folders such as `tenants` and `mcp-servers` from
  agent-card readiness findings unless they carry an explicit agent marker.
- Exclude legacy Codex automations from this readiness blocker unless they carry
  an explicit autonomous-agent marker.
- Keep generated `agent-capability-cards.json` useful for actual agent surfaces.
- Use stdlib-only code and keep the existing CLI/test layout intact.

## Cost And Risk Note

Risk: over-filtering could hide a real automation that should remain below
autonomous operation. The implementation must therefore use explicit inclusion
signals, not broad path suppression alone, and the test must prove a real
incomplete agent still blocks.

Cost: small local CLI/test change. No external sends, production mutation,
runtime profile push, Slack rename, or cron mutation.

## Verification Command

```bash
python3 /Users/alexhale/Projects/pathway-operating-layer/.planning/2026-07-06-agent-card-scanner-scope/verify-govern.py
```

## Carry Forward

summary: The scanner-scope fix is governed by one metric: broad helper folders and legacy Codex automations must produce zero false blockers for active Hermes readiness, while real incomplete agent candidates still block.

what_changed: Pinned the decision, metric, acceptance criteria, and risk note before implementation.

more_relevant: Implement explicit inclusion signals for agent-card candidates and prove the scanner still flags a deliberately incomplete real agent.

less_relevant: Adding metadata to every legacy automation or editing Hermes profile cards is not the right fix for this outcome.

next_pathway_must_use: The next implementation must add a scanner-scope regression fixture that includes `agents/tenants`, `agents/mcp-servers`, legacy `codex/automations/*`, and one real incomplete agent candidate.

do_not_do_yet: Do not edit central operator-intelligence ledgers by hand, do not mutate Hermes runtime profiles, and do not weaken readiness scoring for real agent candidates.

open_decisions: Whether legacy Codex automations should get their own separate scanner later, outside active Hermes profile readiness.

active_risk_overlays: `llm-agent-eval`.
