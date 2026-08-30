---
timestamp: 2026-08-30
work_id: W-20260830-pathway-operating-layer-per-project-observabilit-e65d28
pathway: security
verified: 2026-08-30
critics: codex (BLOCKED, 10 findings) + glm-us via OpenRouter (10 findings), adjudicated below
---

# Threat model — per-project observability contracts

## Scope and trust boundary

This repo is a local stdlib CLI, not a served app: no network listener, no
anon-read surface, no SSRF vector. The untrusted actor is a **receipt
author** — any process or project trying to earn observability credit it
did not honestly produce — plus, per critic finding T9, any **verifier
file** a receipt binds, since the engine executes it as a subprocess. The
trust plane for contract files is reviewed commits in Alex's repo (spec
decision 1). The security question: does contract-as-data open a gaming or
execution path that constant-as-code does not have?

Every "verified" note below came from a tool call in the authoring session
(2026-08-30, HEAD `0a89d9a`), including re-verification of critic-supplied
line citations before acceptance.

## Threats and mitigations

- **T1 — receipt picks its own (weaker) contract.** Mitigation: decision 5,
  resolution key from the work item via `resolve_project_dir`, never a
  receipt value. Verified: caller binding refuses receipt-supplied context
  (`:2231-2237`, bound at `:4505`/`:4877`). Hardening (critic-confirmed,
  `:7681-7690`): `work-log` today only WARNS on an unknown work ID and
  proceeds with the CLI `--project` (`:4429`); an observability proof under
  a per-project contract must hard-refuse a missing work item so the
  contract key can never come from attacker-influenced arguments.
- **T2 — a weak contract lowers the proof floor.** The receipt-level
  metric-set equality (`:2194`) with an empty contract set passes on an
  empty receipt list (verified; the artifact path is stricter — zero
  samples are rejected at `:2044-2046`). And a critic point survives
  adjudication: a nonempty one-metric contract still shrinks required
  evidence, because completeness is relative to contract-controlled sets.
  Controls: the loader rejects missing required keys (no `.get()`
  defaults), empty or mistyped enums, and low-quality members (globs,
  whitespace, length < 4); the engine keeps per-enum minimum cardinality
  floors; contract files get a dedicated 64KB byte cap; and the contract
  schema gate runs inside the canonical test suite so data files receive
  the automated validation code already gets. Residual, stated plainly:
  above those floors, a reviewed contract DOES control evidence depth —
  that is decision 1's trust plane, accepted.
- **T3 — trust minted by editing the contract file.** Equal-plane argument
  verified (the engine itself is a same-permission working-tree file), BUT
  both critics flag what it misses: the sha allowlist is a proof-strength
  control living in the same JSON as evidence semantics, and data files
  receive no automated CI scrutiny while code does. Control: the suite
  gate from T2 closes the automation gap. **Open decision for Alex at the
  Phase 1 gate** (locked decision 4 says the sha list lives in the
  contract file, so changing this needs his call): keep it there, or split
  trust into a sibling `<project>.trust.json` so one edit cannot both
  weaken semantics and bless the verifier attesting to them.
- **T4 — contract lookup identity and traversal.** Beyond separator/`..`/
  symlink refusal (reuse `:1133`/`:1137`/`:1822`), two critic-confirmed
  gaps: (a) `resolve_project_dir` (`:4373`) searches owner families, so
  `koho/foo` and `prettyfly/foo` share the basename `foo` — the contract
  key must be the canonical path relative to the projects root (owner
  family included), not a bare basename; (b) the `contracts/` DIRECTORY
  itself could be a symlink, so the loader must realpath the directory and
  assert containment inside the repo before reading any file.
- **T5 — oversized or hostile contract JSON.** Load through
  `_read_strict_json_object` (byte cap + strict parsing, `:1743-1747`)
  with the 64KB contract-specific cap from T2. Reuse, don't reimplement.
- **T6 — fail-open on missing or unreadable contract.** Missing contract =
  refusal with `observability_contract_not_registered` (gate G2), never a
  fallback to the tradebot schema or to "no validation". Verified: today's
  default is fail-closed (`:1616-1617`, refusal `:3279-3280`); extraction
  preserves that posture per project.
- **T7 — the unbound credit-scope helper (downgraded on adjudication).**
  Codex verified what my first draft missed: full validation with caller
  binding and artifact base already runs FIRST (`:2314`), and
  `observability_receipt_credit_scope` can only refuse, never grant, since
  outcome requires `scope and not errors` (`:2318-2323`). So this is not a
  side door; it is a correctness/DRY constraint: validate once, make
  credit-scope a pure function over the already-validated result instead
  of re-validating (and later re-loading a contract) inside the helper.
- **T8 — inline tradebot semantics beyond the constants block (new, both
  critics).** Three sites, all verified: alert `status == "FIRED"` /
  `safe_action == "HALT_ENTRIES_RECONCILE_ONLY"` (`:2088-2089`), the
  canary results map (`:2123-2127`), and — the largest — the drill
  correlation function, which indexes five specific tradebot question IDs
  and matches `OBSERVABILITY_DRILL_INCIDENT` fields directly
  (`:1958-1976`). Constraint: Phase 1 classifies each site as WHAT
  (extract to contract, with the proof-strength implication stated) or
  HOW MUCH (stays engine-side, generic envelope). For drill correlation
  the KISS resolution is a small engine-owned correlation envelope
  (answers must correlate to log records on contract-declared fields)
  rather than a general runbook DSL. Duplicated values (`FIRED` in both a
  constant and an inline check) move together or not at all.
- **T9 — the receipt-bound verifier executes before its digest is trusted
  (new, Codex).** Verified: when a runtime receipt is structurally valid,
  `run_observability_verifier_argv` executes the verifier file
  (`:4658-4682`) while the sha-allowlist check happens only later in
  `proof_is_verified` (`:3279-3280`). Today the allowlist is empty so
  every such execution is of an UNTRUSTED file. Constraint for Phase 2:
  once contracts exist, check the verifier file's sha256 against the
  resolved contract's allowlist BEFORE any subprocess execution, and
  refuse to execute unregistered verifiers at all.
- **T10 — contract bytes are not bound into the proof (new, Codex).**
  Snapshot checks cover receipts and artifacts, not the contract; stored
  proofs carry no contract digest. A contract edit after crediting would
  silently change what historical credit meant, and a verifier could
  mutate a reloaded contract mid-run (TOCTOU). Constraint: load the
  contract once into an immutable object, record its sha256 + schema
  version in the proof, and rehash after verifier execution.

## Repo exposure checks (this session)

- Secret scan across tracked `*.py`, `*.json`, `*.sh`, `*.md`, `*.ndjson`
  for AWS/OpenAI/GitHub token patterns: zero live credentials found (the
  one match is AWS's documented example key, used by the redaction-guard
  tests). Scope stated per critic correction: tracked files, three
  pattern families — a bounded check, not a universal absence claim.
- Anti-gaming invariants (sha256 maps, per-artifact canary, restoration
  hashes, verifier binding, snapshot stability) live in `proof_is_verified`
  (`:3282-3306`) and reference shape constants that stay engine-side; with
  the T2 floors and the T3 open decision resolved, spec decision 3 holds.

## Critic adjudication record

Codex (BLOCKED, 10) and GLM-US (10) reviewed this model, the spec, and the
research dossier with the same brief. Accepted and folded in: verifier
pre-trust execution (T9), contract-identity collision + directory realpath
(T4), contract-digest binding + TOCTOU (T10), cardinality/value floors +
missing-key rejection + 64KB cap + suite lint (T2), inline-semantics
inventory including drill correlation (T8), unknown-work-id hard refusal
(T1), T7 downgrade, gate-strength fixes to `verify_security.py`, wording
corrections (dossier "34"→36; secret-scan scope). Recorded as an open
decision, not unilaterally changed: trust-root placement (T3) — it
challenges locked spec decision 4. Rejected: GLM's YAGNI call to defer the
whole feature (contradicts the approved spec; gate G3 targets the real
specialist-fleet instrument built and drilled 2026-08-29) and GLM's
engine-side commit-registry cross-check for shas (recreates the code-edit
path decision 4 removes; the T3 open decision covers the concern).
Contract staleness (`last_reviewed`, warn-only) noted as optional hygiene
for the Phase 1 schema, not a gate.

## Verification of the gate

`verify_security.py` in this directory re-measures live: the caller-binding
refusal (T1) requiring all four context fields to mismatch-error
individually, the fail-closed default (T6/T9 posture) from the engine
constants, and the bounded secret scan; it then asserts the receipt agrees
with the measurement. This file plus that executed run is the
security-gate artifact.

## Constraints carried forward to Phase 0/1/2

1. Phase 0 goldens use FROZEN literal fixtures, not values derived from
   live constants, so a bad extraction cannot self-validate; adversarial
   cases include malformed contracts, identity collisions, and missing
   work items (Codex #10).
2. Contract loader: reject missing keys, empty/mistyped enums, low-quality
   members; engine-side cardinality floors; 64KB cap; schema gate wired
   into the canonical suite (T2).
3. Contract key = canonical path relative to the projects root, owner
   family included; realpath-contained contracts directory; separator/
   `..`/symlink refusal reused from the artifact pattern (T4).
4. Contracts load through `_read_strict_json_object` (T5).
5. Missing contract = `observability_contract_not_registered`, never any
   fallback (T6, G2).
6. Verifier sha checked against the contract allowlist BEFORE subprocess
   execution; unregistered verifiers never run (T9).
7. Contract sha256 + schema version recorded in the proof; contract loaded
   once, immutable, rehashed after verifier execution (T10).
8. `observability_receipt_credit_scope` becomes a pure function over the
   single validated result (T7).
9. Observability work-log hard-refuses unknown work IDs (T1).
10. Inline-semantics sites classified WHAT vs HOW MUCH at Phase 1; drill
    correlation gets a generic engine-owned envelope (T8).
11. Alex decides trust-root placement (in-contract vs sibling trust file)
    at the Phase 1 gate (T3 open decision).
