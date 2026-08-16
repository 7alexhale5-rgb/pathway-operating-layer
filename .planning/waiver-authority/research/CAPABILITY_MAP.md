# Capability map — waiver/approval authority build

timestamp: 2026-08-16

## What the engine can already do (verified in code this session)

- Validate typed release receipts and bind production claims to work/project
  context with freshness windows (`validate_release_receipt`,
  `_release_envelope_errors`, `release_receipt_from_evidence`).
- Bind a release verifier's stdout markers to the exact receipt digest
  (`release_verifier_binding`).
- Run anti-gaming canaries and require a tripped canary for release credit
  (`proof_is_verified` release branch).
- Refuse free-text N/A on production-secure outcomes (`run_work_cover` +
  `production_secure_waiver_locked`), and reopen production-secure N/A rows at
  status time (work_status_summary line 5766).
- Append-only NDJSON ledgers in the operator-intelligence store with
  read/write/upsert helpers (`Paths`, `read_ndjson`, `write_ndjson`).

## What it cannot do yet (the gap this build closes)

- No approval/waiver ticket concept: no issuance, no consumption, no ledger.
- Release production credit is a dead end (`VERIFIABLE_APPROVAL_NOT_CONFIGURED`
  is terminal); production-secure N/A is a dead end
  (`VERIFIABLE_WAIVER_NOT_CONFIGURED` is terminal).
- No cross-ledger corroboration of a human decision at status time.

## Adjacent capability reused, not rebuilt

- `~/.claude/scripts/approve-send.py` is the proven pattern: canonical-JSON
  SHA-256 content binding, 900s TTL, single use, append-only audit log. This
  build ports the pattern into the engine's ledger model; it does not call or
  modify approve-send.py.

## Tools, fallbacks, and cost

- Tools used for this research: Read/Grep over the repo, Bash execution of the
  suite and the live CLI (work-status probes), direct Read of approve-send.py
  and the transfern receipt. No external services, no subagents, no network.
- Fallbacks / degraded modes: if the live CLI probe had failed, the fallback
  was reading the ndjson ledgers directly under
  memory-vault/operator-intelligence/ (same trust tier, more parsing). If the
  suite had been red, the build would halt (repo rule) — no degraded build
  mode exists by policy.
- Cost: zero external spend; one full suite run (~1 minute local CPU) per
  edit cycle is the only recurring cost. No API calls, no per-prompt quota.

## Out of scope

- Observability Tier-B trusted-verifier configuration (tradebot-specific
  runtime contract) stays unconfigured.
- External-send (`sent`) receipts stay fail-closed; sends are approve-send.py
  territory.
