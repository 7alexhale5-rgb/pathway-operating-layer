# Agent-Card Scanner Scope Implementation Receipt

Status: pass
Work item: W-20260706-pathway-operating-layer-fix-agent-card-scanner-s-c64f27
Pathway: implementation

## Slice

`scan_agents` now treats regular `manifest.json` directories under
`projects/agents/hermes/profiles/` as the complete agent-card population. It
does not scan broad helper folders, Mission Control folders, or legacy Codex
automations. A profile directory or manifest symlink remains excluded.

The scanner reads profile documents through the existing contract path, so
incomplete manifest-backed profiles still create a readiness finding. The
selection change limits false blockers; it does not grant autonomy or alter a
profile's readiness score.

## Measured Result

The controlled `agent-cards` fixture now reports:

```json
{
  "status": "pass",
  "agent_cards_scope_false_blockers": 0,
  "selected_systems": ["atlas-ceo"],
  "missing_real_profile_systems": []
}
```

The symlink boundary verifier also confirms that an external manifest cannot
be selected or emitted.

## Proof

```bash
cd /Users/alexhale/Projects/pathway-operating-layer && python3 .planning/2026-07-06-agent-card-scanner-scope/verify-implementation.py && git diff --check
```

## Summary

Status pass: the local scanner now inventories only active, manifest-backed
Hermes profile directories, eliminating the observed helper and legacy false
blockers.

## What Changed

Replaced broad top-level folder discovery with explicit Hermes profile manifest
discovery, updated scanner fixtures, and proved the same alert baseline now
passes with zero false blockers.

## More Relevant

Quality must retain the implementation verifier, full suite, data contract, and
symlink proof so future scanner edits cannot reintroduce helper or legacy rows.

## Less Relevant

No runtime profile, Slack, cron, launchd, external API, deployment, or central
ledger mutation is part of this local implementation slice.

## Next Pathway Must Use

Use the `verify-implementation.py` command and inspect the JSON signal for one
selected real profile, no missing profiles, and a zero false-blocker count.

## Do Not Do Yet

Do not expand this scanner to legacy automation readiness, push, deploy, mutate
Hermes runtime, alter external systems, or close the work item before quality
proof is logged.

## Open Decisions

Whether an automation-specific scanner should later define its own explicit
marker and independent readiness population.

## Active Risk Overlays

`llm-agent-eval`.
