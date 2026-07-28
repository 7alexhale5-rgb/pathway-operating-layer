# Agent-Card Scanner Scope

The `agent-cards` command is a local readiness inventory. It must describe the
active Hermes agent population, not every nearby folder that happens to contain
a `README.md` or every legacy Codex automation.

## What The Alert Means

The controlled fixture currently reports an `alert` with three false blockers:
`tenants`, `mcp-servers`, and `legacy-job`. It also reports `atlas-ceo` as a
missing real profile. That is an accurate before-fix signal, not an indication
that the helper folders are unsafe agents.

The target is:

```text
agent_cards_scope_false_blockers = 0
selected_systems = ["atlas-ceo"]
missing_real_profile_systems = []
status = "pass"
```

The selected profile must remain incomplete in the generated readiness finding
until its own contract is complete. The correction narrows the population; it
does not weaken the readiness standard.

## Selection Rule

- Select a regular, manifest-backed Hermes profile under `hermes/profiles/`.
- Exclude generic helper folders such as `tenants` and `mcp-servers`.
- Exclude legacy Codex automations unless a later automation-specific scanner
  defines an explicit autonomous-agent signal.
- Exclude symlinked candidates and symlinked inclusion markers.

The authoritative fixture for this work is
`.planning/2026-07-06-agent-card-scanner-scope/agent-card-scope-fixture.json`.
It captures one real Hermes profile, the helper folders, one legacy automation,
and the symlink regression case.

## Verify The Change

Before implementation, reproduce the alert:

```bash
python3 .planning/2026-07-06-agent-card-scanner-scope/scanner-scope-observability.py --expect alert
```

After implementation, the same fixture must pass:

```bash
python3 .planning/2026-07-06-agent-card-scanner-scope/scanner-scope-observability.py --expect pass
python3 .planning/2026-07-06-agent-card-scanner-scope/verify-data.py
python3 .planning/2026-07-06-agent-card-scanner-scope/verify-security.py
python3 scripts/tests/operating_layer_test.py
```

The observability command writes the local JSON signal at
`.planning/2026-07-06-agent-card-scanner-scope/SCANNER_SCOPE_SIGNAL.json`. It
does not mutate a Hermes runtime profile, central ledger, Slack, cron, launchd,
or any external service.

## Operator Response

If the post-fix signal is an alert, inspect `false_blocker_systems` and
`missing_real_profile_systems`. Keep the affected profile below autonomous
operation until the scoped readiness finding and its underlying profile contract
are both correct. Do not silence the signal to make a work item look complete.
