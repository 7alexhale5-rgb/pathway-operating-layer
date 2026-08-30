---
timestamp: 2026-08-30
work_id: W-20260830-pathway-operating-layer-per-project-observabilit-e65d28
tier: production-secure
approved: Alex started the outcome via /pathway START 2026-08-30 10:16 EDT
---

# SPEC — per-project observability contracts

## Goal (the decision this drives)

The observability credit branch is the only pathway whose evidence schema is
hardwired to one project: every enum in `OBSERVABILITY_*`
(operating-layer.py:1486-1663) describes the tradebot, and receipt validation
requires metric-name-set EQUALITY with that schema (:2049, :2194) and
tradebot-only events (:1872). Result, verified live 2026-08-29/30: an honest
receipt from any other project cannot credit, and two outcomes closed with
waivers instead. This work makes the contract per-project data instead of
engine constants, so any project can earn observability credit honestly, the
way the release branch already works generically.

## Locked design decisions

1. **Contracts are versioned data in this repo**: `contracts/observability/
<project>.json`. Same trust plane as the constants they replace (reviewed
   commits in Alex's repo). No contract file, no credit: the shipped default
   stays fail-closed, preserving the doctrine that observability credit is
   opt-in and deliberate per project.
2. **The tradebot loses nothing.** Its schema is EXTRACTED verbatim into
   `contracts/observability/rainman-thorp.json`; validation verdicts must be
   byte-identical before and after (characterization gate below).
3. **Anti-gaming invariants are contract-independent.** The 7-field receipt
   shape (metric, log, trace, alert, runbook_drill, canary, verifier), per-
   artifact sha256 + canary + restoration-hash matching, verifier binding,
   snapshot stability, and the trusted-verifier sha allowlist survive in EVERY
   contract. A contract defines WHAT the evidence describes, never HOW MUCH
   proof is required.
4. **Trusted-verifier registration moves into the contract file** (a sha256
   list per project) replacing the empty global frozenset and the global trust
   state. Registering a verifier = a reviewed commit, not a code edit.
5. **Resolution key is the work item's project** (same resolution
   `resolve_project_dir` already performs), never a receipt-supplied value: a
   receipt must not be able to pick its own (weaker) contract.

## Gate metric (falsifiable, stated before build)

Three conditions, all required:

- G1: characterization suite green — synthetic tradebot receipts (valid,
  wrong-metric-set, wrong-event, missing-artifact) produce IDENTICAL
  error lists before and after extraction.
- G2: a non-tradebot project with NO contract still gets a refusal, with a new
  `observability_contract_not_registered` reason instead of tradebot-enum
  errors.
- G3: on the agents project, with a registered contract + trusted verifier
  sha, an honest runtime receipt for the specialist-fleet instrument
  (subagent-perf-watch, built and drilled 2026-08-29) yields
  `proof_is_verified` True with `observability_credit_scope` runtime,
  canary True; and a receipt violating that contract is refused.

## Phases (each ships end-to-end against its gate)

### Phase 0 — characterization harness (throwaway-first)

Pin current behavior before touching it: `tests/test_observability_contracts.py`
with synthetic tradebot receipts hitting `validate_observability_runtime_receipt`
and `_validate_observability_json_artifact`; record verdict/error-list goldens.
Gate: suite runs green against the UNMODIFIED engine.

### Phase 1 — extract to data

Move the tradebot enums into `contracts/observability/rainman-thorp.json`; a
loader replaces constant references; global trust state becomes derived (a
project with a contract carrying >=1 trusted sha is CONFIGURED_AND_VERIFIED
for that project only). Gate: G1 (characterization identical) + full existing
test suite green.

### Phase 2 — resolve by project, fail closed without a contract

Contract lookup keyed on the proof's resolved project; missing contract =
refusal with `observability_contract_not_registered`. Gate: G2.

### Phase 3 — register the agents contract and credit a real proof

Author `contracts/observability/agents.json` (specialist-fleet schema: pass
rate/streak metric, perf-ledger log, trap-transcript trace, inbox-alert
artifact, watch runbook drill) + trusted sha of its runtime verifier. Gate: G3
end-to-end, logged as this outcome's own observability proof.

### Phase 4 — docs + memory

Update the canary-verifier memory (the "unreachable by design" paragraph
becomes "per-project contracts"), engine README, and the BACKLOG entries in
agents that reference the pinned contract. Gate: docs pathway proof.

## Out of scope (YAGNI)

Release branch changes; loosening any proof requirement; auto-generating
contracts; migrating the two waived outcomes retroactively (their waivers are
honest history); the PFOS control surface (its evidence becomes creditable
AFTER this ships, via its own contract).

## Verifier criteria

Every gate is an executed command; critics at max (Codex + GLM-US) on the
extraction diff before Phase 3; the canary-verifier proof recipe applies to
every pathway log on this outcome.
