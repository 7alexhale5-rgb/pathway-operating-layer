# Research dossier — waiver/approval authority

timestamp: 2026-08-16
method: direct code read of scripts/operating-layer.py (dirty worktree, suite
768/768 green this session) + live ledger probes. Every claim below was read
from the running system today, not carried forward.

## Verified code facts (blocker-class)

- `PRODUCTION_SECURE_WAIVER_STATE` line 587 = `VERIFIABLE_WAIVER_NOT_CONFIGURED`;
  `production_secure_waiver_locked()` line 590 locks on tier
  `production-secure`, profile `production-secure-launch`, or a
  `production-mutation` overlay.
- `RELEASE_PRODUCTION_APPROVAL_STATE` line 984 = `VERIFIABLE_APPROVAL_NOT_CONFIGURED`.
  `validate_release_receipt` (line 987) errors unconditionally on
  `production_status == "deployed"` and on `external_send_state == "sent"`.
- `proof_is_verified` (line 2705): release branch (2733) requires the state
  constant to read `CONFIGURED_AND_VERIFIED`, then `canary_mutant_failed is
  True` (the canary MUST actually trip for release — commit-distance `None`
  does not credit release), snapshot stable, credit scope `production`,
  receipt errors empty, all four artifact digests, verifier bound.
- Release credit scope (line 1059): production only; `_release_envelope_errors`
  (1092) additionally binds work_id / recommendation_id / target_project +
  fresh issued_at/expires_at (≤24h window, ≤300s future skew) on the envelope.
- Verifier binding (1185): stdout must emit RELEASE_DECISION / RELEASE_GATE /
  PATHWAY_RESULT / PRODUCTION_STATUS / CANARY_STATUS / ROLLBACK_STATUS +
  exact `RELEASE_RECEIPT_SHA256`, no duplicates.
- work-log proof record assembly at ~4032; release fields copied from
  `release_receipt_from_evidence` (1134); loud non-credit findings at 4117+.
- work-cover --na rejection for production-secure at 6331; the successful `na`
  write path at 6406 sets only status+reason. Reopen at status time: line 5766
  reopens EVERY production-secure `na` row unconditionally.
- Store: `Paths` class line 2561; ledgers under
  `operator-intelligence/` (`work-items.ndjson`, `proofs.ndjson`);
  `read_ndjson`/`write_ndjson`/`upsert_proof` helpers; NDJSON read cap
  64MB (front-truncation hazard documented at the constant).
- Observability Tier-B runtime receipt contract (1211-1342) is a frozen
  tradebot-specific contract (metric names, drill questions);
  `OBSERVABILITY_RUNTIME_VERIFIER_TRUST_STATE` stays
  `TRUSTED_VERIFIER_NOT_CONFIGURED` — out of scope for this build; the waiver
  path is the correct route for transfern observability.

## Design source to mirror

- `~/.claude/scripts/approve-send.py`: canonical-JSON SHA-256 digest
  (sort_keys, compact separators), single ticket, 900s TTL, append-only log of
  issue+use, explicit "forcing function and audit trail, not a cryptographic
  barrier" framing. Same framing applies here.

## Live envelope state (probed this session)

- `W-20260816-transfern-validate-transfern-live--5ff13d`: tier `live`, profile
  `production-secure-launch`, overlays production-mutation + rollback +
  ui-proof → waiver-locked. Coverage 9/11; open = observability, release; both
  logged_unverified. Project `/Users/alexhale/Projects/transfern`.
- `~/Projects/transfern/docs/release-rollback-rehearsal.json`: production
  receipt shape complete (deployed, rollback rehearsed, canary passed, four
  artifact filenames present) but MISSING envelope binding fields (work_id,
  recommendation_id, target_project, issued_at, expires_at) — must be extended
  at proof time. Companion .md runbook exists.

## Unknowns (classified)

- warn: existing suite tests may assert the exact production-approval error
  text — locate and update alongside the code.
- info: `proved_pathways_from_proofs` call sites beyond work_status_summary —
  corroboration join must cover the coverage paths that have `paths` access.
