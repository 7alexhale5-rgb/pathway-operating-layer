# Pathway Operating Layer - Present State

Updated: 2026-08-17
Active work ID: `W-20260817-pathway-operating-layer-block-agent-driven-bash--2064b8`
Current outcome: the approval authority is shipped. Its agent Bash issuance guard is built,
wired, and statically verified. Codex trust and fresh-session probes still need Alex.

Guard numbers below were read from the running system on 2026-08-17.
Authority history was last proved on 2026-08-16.

## Verified now

- The clean build baseline is `3c7fd07`. The current guard diff passes `1088/1088 checks`.
  `e82d9cc` built the authority, and `5e8b0dc` closed its first review findings.
- One tracked guard now serves Claude, Codex, GLM, and Kimi. Both installed links resolve to
  that source. All three settings files parse and name the guard once in their Bash matcher.
- The guard's direct fixtures deny issuance with exit `2`. Safe Pathway commands exit `0`.
  Its latest local 120-run timing was 17.303ms p95.
- The live approvals ledger stayed at four lines with SHA-256
  `31f4b8cd3432e711746faa0a4065bd6ebfac1f108d55c4ea2c2649e7d7ec7dd7`.
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
- The Bash guard blocks known direct forms. Encoded commands, renamed copies, direct imports,
  and other process tools stay outside its mechanical boundary.

## Follow-up queue

1. **Partly closed (carried).** `work-close` success branch still omits the closed `work_id`.
2. **Needs re-measuring (carried).** Attestation-only proof migration backlog: re-derive from
   the current ledger before scheduling.
3. **Closed 2026-08-16.** The memory asserting a permanent 10-of-12 local ceiling was rewritten
   against the shipped authority, including the release-canary recipe that actually worked.
4. **Implemented, live proof pending.** The PreToolUse guard denies known direct
   `approval-issue` Bash forms. Alex still needs to trust the new Codex hook. Fresh Claude,
   Codex, GLM, and Kimi sessions must then run the harmless blocked and allowed probes.
5. **Open, from the review.** A second model family never reviewed this code. Run Codex or GLM
   over `e82d9cc..5e8b0dc` when Alex authorizes an external critic send.

## Guardrails

- Keep audit scoring read-only and local.
- Never edit the two state constants to make a number go green; they flip only with the
  verification machinery that makes them true (done 2026-08-16, suite-gated).
- Stamp this file with its own date on every edit. A current-state doc with no date of its own
  may not assert present-tense status, and file modification time is never that date.
