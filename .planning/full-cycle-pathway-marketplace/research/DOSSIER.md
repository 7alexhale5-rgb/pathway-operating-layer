# Research Dossier — Full-Cycle Pathway Marketplace Redesign

Date: 2026-07-05  
Project: `/Users/alexhale/Projects/pathway-operating-layer`  
Work item: `W-20260629-pathway-operating-layer-elevate-pathway-to-world-2819f3`  
Recommended pathway: `research`  
Question: What must be known for certain before the full-cycle pathway marketplace redesign can be trusted?

## Research Plan

Depth: local deep dossier.  
Reason for local-only research: the high-impact claims concern the live local engine, its command docs, and Koho field artifacts. External search would add noise without improving the implementation decision.

Inputs:

- Live engine source and parser surface.
- Command docs and README.
- Existing pathway references.
- Koho operating snapshot, verification matrix, Template Review ledger, Excerpa review workflow, ConsultOps design system, and recurring security verdict.
- Swarm audit artifact created on 2026-07-05.

## Executive Finding

The redesign should not become a large catalog of new pathway nouns. The evidence supports a smaller architectural move: keep the proof spine, introduce outcome profiles, force risk overlays, and add one first-class `field` pathway for real operator/customer validation.

## Stabilized Claims

| Claim | Confidence | Source |
|---|---|---|
| The current engine has the correct proof spine: work items, itinerary coverage, proof records, and executed verifier receipts. | High | `operating-layer.py:122`, `operating-layer.py:798`, `README.md:174` |
| The current tier map is too weak for Koho-class live work because `live` does not require security. | High | `operating-layer.py:142`, `README.md:167`, audit artifact P0 table |
| Generated next commands still use stale `--verified-by` proof wording even though the parser marks it attestation-only. | High | `operating-layer.py:4364`, `operating-layer.py:4476`, `operating-layer.py:6108`, `commands/pathway.md:126` |
| A work item can still be started without a tier and therefore without a coverage itinerary. | High | `operating-layer.py:3057` |
| The CLI parser does not expose true `go` or `loop` subcommands even though command docs describe `go` as executor behavior. | High | `commands/pathway.md:78`, `operating-layer.py:6082` |
| The current `proof_is_verified` function does not reject trivial verifier or failed canary flags; it only checks executed plus exit 0. | High | `operating-layer.py:798`, `operating-layer.py:1045` |
| Koho work proves that "live and tested" is insufficient unless a real operator/customer completes or reviews the workflow. | High | `PATHWAY.md:7`, `VERIFICATION-MATRIX.md:3`, `template-review LEDGER.md:3`, `koho-review-workflow-design.md:53` |
| Rendered UI proof must be stronger than static design-token proof for client-facing UI and dense operational surfaces. | High | `consult-ops/DESIGN.md:134`, Template Review UI ledger screenshot/proof sequence |
| Tenant isolation must be explicit; anon-closed is not enough when authenticated users can read broadly. | High | `security-recurring-findings-verdict.md:5` |

## Design Decision

Implement outcome profiles first, pathway additions second.

The evidence argues for this hierarchy:

1. Outcome profile: what kind of work is this?
2. Risk overlays: what surfaces does this touch?
3. Required itinerary: which pathways must be proved or explicitly marked not applicable?
4. Proof bundles: what evidence makes the pathway impossible to fake?
5. Closeout policy: what shortcuts are rejected?

This avoids turning the marketplace into a long menu while still covering the full development cycle.

## Recommended Taxonomy

Keep the existing eleven pathways, but change how they are used:

- `govern`: outcome contract, profile, tier, metric, stop conditions, human gates, external gates.
- `research`: unknowns register and source-backed assumptions.
- `data`: lineage, measured/zero/unavailable state, migration drift, RLS implications, real-row proof.
- `security`: threat model, tenant isolation, authz, secrets, PII, supply chain, production mutation controls.
- `design`: workflow/persona design, design-system discipline, rendered UI proof, a11y, keyboard, responsiveness.
- `implementation`: smallest runnable slice tied to the governed outcome.
- `quality`: regression tests, e2e proof, second-pass critique, eval/golden corpus where agentic behavior exists.
- `observability`: signals, traces, costs, logs, alerts, and runbook readiness.
- `release`: canary, smoke, rollback, deploy identity, external-send state.
- `docs`: ADR, runbook, current-state handoff.
- `techdebt`: conditional simplification/operability debt, not a default ritual.

Add one pathway:

- `field`: real operator/customer validation, review packets, human decisions, adoption blockers, and feedback capture.

## Outcome Profiles

| Profile | Required composition |
|---|---|
| `tiny-bugfix` | govern-light, implementation, quality |
| `standard-bugfix` | govern, affected risk overlays, implementation, quality, docs if state changed |
| `demoable-ui` | govern, design, implementation, quality, field if human review is involved |
| `data-integration` | govern, research if unknown, data, security, implementation, quality, observability, release, docs |
| `live-internal` | govern, data, security when risk signals appear, design if UI, implementation, quality, observability, release, docs |
| `production-secure-launch` | govern, research, data, security, design if UI, implementation, quality, observability, release, docs, field |
| `agent-connector` | govern, research, data, security, implementation, quality/evals, observability, release/canary, field if human workflow exists |
| `client-feedback-surface` | govern, data, security, design, implementation, quality, observability, release, docs, field |

## Forced Risk Overlays

| Signal | Required behavior |
|---|---|
| auth, tenant, RLS, PII, external user, client portal, production data | Force production-secure security/data gates. |
| schema, migration, Supabase, DB write, backfill | Require migration proof, rollback proof, real-row verifier, production mutation approval. |
| UI, dashboard, review, portal, table, navigation, mobile | Require rendered UI proof bundle under design. |
| LLM, agent, prompt, extractor, OCR, eval, confidence | Require eval/golden set under quality and traces/cost under observability. |
| send, Slack, email, client packet, Josh, Jim, Marc, customer | Require human gate and field pathway. |
| deploy, release, prod, worker, cron, integration | Require release, rollback, canary or smoke, observability. |
| fake, fixture, mock, prototype | Require explicit non-production label or block release. |

## Proof Bundles

### Security

Minimum evidence for risky live work:

- Threat model or trust boundary.
- Route/RPC/cron/service-role inventory.
- Anon access proof.
- Authenticated row-scope proof.
- Tenant/role/field masking proof where applicable.
- Secret scan over code and generated artifacts.
- PII classification and retention/deletion path where applicable.
- Supply-chain receipt.
- Incident-response pointer for live surfaces.

### Design

Minimum evidence for UI-impacting work:

- Changed route/component list.
- Desktop, tablet, and mobile screenshots.
- Light/dark proof when supported.
- Axe/Lighthouse serious and critical pass.
- Keyboard navigation proof.
- Responsive proof for dense tables and dashboards.
- Workflow/IA proof for navigation changes.

### Data

Minimum evidence for data or claim-bearing work:

- Source-of-truth pointer.
- Measured/zero/unavailable classification.
- Real-row or cell-level parity check.
- Migration drift check.
- Canonical-data invariant.
- Local-output hygiene for client data.

### Release

Minimum evidence for live rollout:

- CI or substitute gate.
- Preview/canary smoke.
- Production alias/deployment identity when live.
- Rollback target and rehearsal.
- DB, worker, and feature rollback class.
- Explicit external-send state: not-sent, send-ready, sent, or blocked.

### Field

Minimum evidence for operator/customer validation:

- Human owner and exact ask.
- Packet path.
- Sent/not-sent status.
- Review questions.
- Feedback capture location.
- Decision classification.
- Adoption signal or explicit blocker.

## Unknowns

| Unknown | Class | Why |
|---|---|---|
| Whether `field` should be in `PATHWAY_ORDER` immediately or implemented first as a risk overlay | Warn | First-class pathway is supported by evidence, but adding it changes ranking, docs, tests, and existing state assumptions. |
| Whether the active work item should be upgraded from `live` to `production-secure` | Warn | The current active work item is closeout-ready for live, but the new goal is broader. Implementation should avoid silently rewriting historical coverage. |
| Whether `go` should become a real CLI subcommand or remain a Codex/Claude command wrapper | Warn | User experience argues for real `go`; small CLI design argues against embedding tool execution too deeply in a stdlib script. |
| Whether trivial verifier flags should fail all closeouts or only high-tier closeouts first | Blocker for implementation spec | The audit says reject them. The migration path needs a compatibility decision because historical proofs may carry this flag. |
| Whether high-risk N/A requires a named reviewer, a second verifier, or both | Blocker for implementation spec | Current N/A is reason-only. The exact approval receipt shape must be specified before code changes. |

## Implementation-Ready Priorities

1. Fix proof language drift by replacing generated proof commands and command docs with `--verify-cmd`.
2. Require tier or profile for new work starts; no empty-itinerary closeouts.
3. Reject trivial verifier and failed canary/mutant receipts in closeout readiness.
4. Force security/data production-secure behavior for auth, PII, tenant, RLS, external-user, and production-data signals.
5. Add tenant-isolation sub-gates to security/data proof.
6. Add outcome profiles and profile-to-itinerary routing.
7. Add `field` pathway after P0 closeout/proof safety is stable.
8. Add rendered UI proof bundle as a design pathway requirement for UI-impacting work.
9. Add high-risk N/A reviewer policy.
10. Expand proof report fields for auditability.

## Simplicity Filter

The simplest useful next implementation is not a full rewrite. It is a small safety slice:

- Update generated proof commands to `--verify-cmd`.
- Make tier/profile mandatory for newly started work.
- Add risk keyword gates that force security for live risky work.
- Add tests for those three behaviors.

This gets the pathway layer materially safer without committing to the full `field` pathway and profile taxonomy in the same patch.

