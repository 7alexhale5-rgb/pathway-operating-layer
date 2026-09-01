---
timestamp: 2026-08-30
work_id: W-20260830-pathway-operating-layer-per-project-observabilit-e65d28
---

# Work ledger — per-project observability contracts

Goal: tradebot-pinned observability enums become per-project contract files;
any project can earn observability credit honestly. Spec:
`.planning/2026-08-30-per-project-observability-contracts.md` (locked).

Done against the shared work ID:

- govern — spec approved (prior session)
- research — dossier + verified claims; 36 constants + 3 inline sites
- security — threat model T1-T10, Codex + GLM-US adjudicated, 11 constraints
- Phase 0 — characterization harness, 5 golden scenarios, quality partial
- Phase 1 — the Rainman/Thorp contract was extracted mechanically from the
  `9ecedb6` engine constants; the loader and fail-closed schema gate are wired
  into the canonical suite; trust state is derived from the extracted verifier
  digest; G1 is complete locally with 5/5 frozen scenarios, 24/24 fidelity
  matches, and 1313/1313 canonical checks. The durable receipt and executable
  verifier live under `quality/receipt-phase1-g1.json` and
  `quality/verify_phase1_fidelity.py`.
- data proof `P-dc83fe5ed5ea` / run
  `R-W-20260830-pathway-operating-layer-per-project-observabilit-e65d28-data-006`
  is the current registered proof. It binds the corrected 1313/1313 receipt to
  the final strict verifier with `template_check.valid=true`, a complete JSON
  carry-forward baton, and `canary_mutant_failed=true`. Proofs
  `P-b9e7466dbdcd` / data-004 and `P-99265a126957` / data-005 remain audit
  history; data-005 predates the final canonical-count correction and does not
  supersede data-006.
- Phase 2 — project resolution and G2 are complete locally. The engine derives
  the contract key only from the work item's canonical path relative to
  `projects_root` (including owner family), refuses missing, mismatched,
  traversing, dotted-name-colliding, or symlink-directed identities, and never
  reads a receipt-supplied contract selector. Unknown observability work IDs
  now hard-refuse before run/proof construction. Runtime validation consumes
  one immutable resolved contract state; verifier source trust is checked
  before any subprocess; the proof records contract key/path/schema/pre+post
  SHA; and the post-run rehash plus historical bound-contract check reject
  TOCTOU. Credit-scope classification is pure over the already validated
  result. Reviewer follow-up closed four additional edges: the live
  `/Projects/tradebot` identity maps through an engine-owned, namespace-reserved
  `tradebot -> rainman-thorp` compatibility alias (the distinct native
  `rainman-thorp` project is refused); contract semantics and SHA now come from
  one captured byte snapshot; verifier bytes are rechecked against both receipt
  and allowlist immediately before every subprocess and recorded/rehashed in
  the proof; and all mutable contract fixtures use an injected temp root under
  the suite's atexit-cleaned test tree. G2 and adversarial checks include
  no-side-effect sentinels, dotted-name E2E resolution, and historical contract
  invalidation and full-ledger no-write checks for unknown work IDs.
  Verification: frozen Phase 1 characterization 5/5 exact; Phase 1 AST
  fidelity 24/24; canonical suite 1343/1343. The corrected diff passed
  independent re-review with no remaining P0, P1, or P2 finding.

Next: Phase 3 (agents contract, G3 = observability proof), then Phase 4 (docs).
The extracted Phase 1 contract and the separate approval-authority repair are
already preserved in distinct commits. Phase 2 lands in the same local commit
as this ledger update.

Decision at G1: Phase 1 preserves `trusted_verifier_sha256` in the contract
verbatim because extraction fidelity is the goal. Moving the trust root is a
separate architectural change and is not bundled into this extraction.

Constraints (binding, from security pathway): frozen fixtures; loader
rejects missing/empty/mistyped/low-quality keys; cardinality floors; 64KB
cap; contract key = canonical path incl. owner family; realpath containment;
`observability_contract_not_registered` refusal; verifier sha checked BEFORE
execution (Phase 2); contract sha in proof (Phase 2); credit-scope becomes
pure; drill correlation → generic envelope (Phase 3); suite + goldens green
at every phase.

Session convention: --max (dual critics Codex + glm-us on the extraction
diff; glm CN lane content-blocked for this repo, use glm-us directly).
Commit boundary: the recovered approval-authority repair is separate from
Phase 1. Do not mix its hook, engine, test, security-helper, or documentation
hunks into the extraction commit. Its OS-owned installation remains a
human-run ceremony and has not been executed by an agent.
