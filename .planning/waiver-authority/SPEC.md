# Verifiable single-use waiver/approval authority

timestamp: 2026-08-16
status: in-build (this session)
research: research/DOSSIER.md (same date)
work ledger for: CARL GLOBAL_RULE_5

## Goal (the decision this drives)

Release and observability obligations on production-secure outcomes are currently
non-creditable and non-waivable by design, because no verifiable human approval
channel exists. This build creates that channel, mirroring
`~/.claude/scripts/approve-send.py`: a SHA-256 content-bound ticket, single use,
15-minute expiry, append-only ledger, issued by Alex per waiver/approval. It is a
forcing function and an audit trail, not a cryptographic barrier — issuing stays a
separate, deliberate, recorded act bound to reviewed content.

## Design

- Ledger: `operator-intelligence/approvals.ndjson` (append-only; `issued` and
  `consumed` events). Durable consumption state lives here; no ticket files.
- Ticket digest: SHA-256 over canonical JSON (`sort_keys`, compact separators) of
  the subject. Any edit to any bound field invalidates the ticket.
- Kinds:
  - `release-production-approval` — subject binds kind, work_id, project, stage
    (`production`), and `release_receipt_sha256` (digest of the reviewed JSON
    companion at issue time).
  - `production-secure-waiver` — subject binds kind, work_id, project, pathway,
    and the exact reason text.
- Issue: `operating-layer.py approval-issue --kind ... --work-id ... [--pathway
  --reason | --release-receipt] --reason ...`. Resolves project from the work
  item. Appends `issued` with digest, issued_at, expires_at (+900s), reason.
- Consume: exactly once. Release consumption happens inside work-log release
  proof processing (consumed_by = proof_id). Waiver consumption happens inside
  work-cover --na (consumed_by = `work-cover:<work_id>:<pathway>`). A consumed,
  expired, or subject-mismatched ticket fails closed with the current rejection.
- Wiring (a) release: `validate_release_receipt` drops its unconditional
  production error in favor of an approval context; work-log looks up and
  consumes the ticket matching the receipt digest, stamps
  `release_approval_verified/digest/consumed_id` on the proof;
  `proof_is_verified` release branch requires those fields;
  `RELEASE_PRODUCTION_APPROVAL_STATE` -> `CONFIGURED_AND_VERIFIED`. External
  `sent` receipts stay fail-closed (out of scope; sends use approve-send.py).
- Wiring (b) waiver: work-cover --na on a production-secure item requires an
  active matching ticket; marks the entry `na` with `waiver_digest` +
  `waiver_consumed_id`; `PRODUCTION_SECURE_WAIVER_STATE` ->
  `CONFIGURED_AND_VERIFIED`.
- Status-time corroboration: work_status_summary re-joins claims against the
  approvals ledger. A release proof whose claimed approval is not corroborated
  (issued subject match + consumed-by-this-proof) does not credit; a
  production-secure `na` row without a corroborated waiver reopens (existing
  reopen behavior preserved for un-waivered rows).

## Acceptance criteria (checkable before build; each becomes a suite test)

1. Digest is stable under key reordering; any field edit changes it.
2. approval-issue writes an `issued` event with a 900-second validity window.
3. work-cover --na on production-secure without a ticket: still fails closed.
4. work-cover --na with an active matching ticket: entry `na` + waiver fields;
   ledger gains a `consumed` event.
5. Replay of a consumed ticket: fails closed.
6. Expired ticket (>15 min): fails closed.
7. Reason/subject mismatch: fails closed.
8. Status reopen keeps a corroborated waived `na` row; reopens an un-waivered
   production-secure `na` row (existing behavior) and a tampered one.
9. Release receipt production-deployed without approval: not creditable.
10. Release with a matching ticket: proof stamps approval fields; a proof
    missing them never verifies; a proof claiming an uncorroborated approval
    does not credit at status time.
11. Suite stays green: all 768 existing checks plus the new ones.
12. Docs describe the authority (pathway-proof-integrity.md).

## Then: settle transfern W-20260816-transfern-validate-transfern-live--5ff13d

- Release: extend the receipt JSON with envelope binding (work_id,
  recommendation_id, target_project, issued_at/expires_at, release_decision),
  verifier emits the seven bound markers incl. RELEASE_RECEIPT_SHA256; canary
  must actually trip (verifier names the receipt as data). Ticket issued under
  Alex's written directive in this session's task; every issue/use logged.
- Observability: waiver ticket (real monitoring live: /api/health + launchd
  watcher + scripts/verify_observability.py; the Tier-B tradebot runtime
  contract does not describe this project).
- Then work-close. Report coverage 11/11 and the audit trail.

## Constraints

- Stdlib only; no duplicate module-level names; suite green before commit.
- Engine writes only to the operator-intelligence store.
- Second-family critics (Codex/GLM) not authorized: local Fable critic instead,
  model-family gap stated out loud.
