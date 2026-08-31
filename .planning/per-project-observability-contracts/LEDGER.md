---
timestamp: 2026-08-30
work_id: W-20260830-pathway-operating-layer-per-project-observabilit-e65d28
---

# Work ledger — per-project observability contracts

Goal: tradebot-pinned observability enums become per-project contract files;
any project can earn observability credit honestly. Spec:
`.planning/2026-08-30-per-project-observability-contracts.md` (locked).

Done (all canary-verified against the shared work ID):

- govern — spec approved (prior session)
- research — dossier + verified claims; 36 constants + 3 inline sites
- security — threat model T1-T10, Codex + GLM-US adjudicated, 11 constraints
- Phase 0 — characterization harness, 5 golden scenarios, quality partial
- Phase 1 — the Rainman/Thorp contract was extracted mechanically from the
  `9ecedb6` engine constants; the loader and fail-closed schema gate are wired
  into the canonical suite; trust state is derived from the extracted verifier
  digest; G1 is complete locally with 5/5 frozen scenarios, 24/24 fidelity
  matches, and 1295/1295 canonical checks. The durable receipt and executable
  verifier live under `quality/receipt-phase1-g1.json` and
  `quality/verify_phase1_g1.py`.

Next: register the executed G1 proof against the shared work ID and preserve
the extraction as its own commit. Then Phase 2 (resolve by project, G2), Phase
3 (agents contract, G3 = observability proof), and Phase 4 (docs).

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
