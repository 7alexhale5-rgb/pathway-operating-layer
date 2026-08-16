# Pathway Operating Layer - Present State

Updated: 2026-08-16
Active work ID: none (the engine repo itself; the transfern envelope is tracked in the ledger)
Current outcome: the verifiable single-use waiver/approval authority is BUILT and committed.
Release production credit and production-secure N/A waivers are now reachable through
content-bound, single-use, Alex-issued tickets in `operator-intelligence/approvals.ndjson`.

Every number below was read from the running system on 2026-08-16.

## Verified now

- HEAD is `5e8b0dc` "fix(approval): close the adversarial review's findings on the ticket
  authority". `e82d9cc` built the authority; `73d5395` committed the previously-dirty
  2026-08-12/13 hardening wave as its own boundary, resolving follow-up 5 of the prior STATE.md.
- The suite passes `799/799 checks` at HEAD (768 pre-existing + 31 new: the authority's twelve
  acceptance criteria plus a regression per review finding).
- `PRODUCTION_SECURE_WAIVER_STATE` and `RELEASE_PRODUCTION_APPROVAL_STATE` now read
  `CONFIGURED_AND_VERIFIED` and remain kill switches. Spec + research dossier:
  `.planning/waiver-authority/`.
- A Fable adversarial critic returned REQUEST_CHANGES on `e82d9cc`. Every finding is closed in
  `5e8b0dc`, each with a regression verified to FAIL against `e82d9cc` (six named failures plus
  a missing predicate) and pass now. The critic was one model family: Codex and GLM passes were
  not authorized this session, so the second-family gap is real and stated.
- Findings closed: the redactor corrupted the ledger join for project slugs of ~21+ characters;
  a spent ticket locked its subject out permanently; corroboration was enforced in one caller
  only (now `proof_credits_pathway` everywhere); readers did not re-check the issued window;
  ledger writes were unlocked and could rewrite from a truncated read; `proof-add` could never
  credit release. Refuted: `--na --add` cannot burn a ticket.
- The authority is proved end to end on a real outcome, not only in tests. See below.

## Proved on a real outcome

`W-20260816-transfern-validate-transfern-live--5ff13d` closed the same day at **11 of 11**,
readiness `ready`, no warnings — the first production release credit on this machine.

- Release: proof `P-24b158b1f864`, `release_credit_scope=production`,
  `canary_mutant_failed=True` (a genuine trip, not an unavailable canary),
  `release_verifier_bound=True`, `release_approval_verified=True`, consumption `AC-bda0046984fc`.
- Observability: waived, not faked. The Tier-B runtime contract is frozen to a trading system's
  metrics and drill questions and cannot describe that project, while its real monitoring is
  live (health endpoint plus a launchd watcher, 6 of 6 by its own verifier, checked this
  session). The waiver reason records exactly that.
- Audit trail: four events in `operator-intelligence/approvals.ndjson`, two issued and two
  consumed, each bound to its consumer.

## Known constraints (unchanged by design)

- Observability Tier-B runtime credit stays disabled (`TRUSTED_VERIFIER_NOT_CONFIGURED`,
  empty trusted digest set). The waiver is the honest route for projects whose real monitoring
  does not match the tradebot runtime contract.
- External-send (`sent`) release receipts stay fail-closed; sends use approve-send.py.
- The authority is a forcing function and audit trail, not a cryptographic barrier — the same
  trust model as approve-send.py, stated in code and docs.

## Follow-up queue

1. **Partly closed (carried).** `work-close` success branch still omits the closed `work_id`.
2. **Needs re-measuring (carried).** Attestation-only proof migration backlog: re-derive from
   the current ledger before scheduling.
3. **Closed 2026-08-16.** The memory asserting a permanent 10-of-12 local ceiling was rewritten
   against the shipped authority, including the release-canary recipe that actually worked.
4. **Open, from the review.** Issuance records an issuer string but nothing authenticates it:
   an agent and the operator share this shell. The honest next step is a PreToolUse hook that
   denies `approval-issue` from agent-driven Bash, mirroring `external-send-guard.py`.
5. **Open, from the review.** A second model family never reviewed this code. Run Codex or GLM
   over `e82d9cc..5e8b0dc` when Alex authorizes an external critic send.

## Guardrails

- Keep audit scoring read-only and local.
- Never edit the two state constants to make a number go green; they flip only with the
  verification machinery that makes them true (done 2026-08-16, suite-gated).
- Stamp this file with its own date on every edit. A current-state doc with no date of its own
  may not assert present-tense status, and file modification time is never that date.
