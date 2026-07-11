# Karpathy Spec — Intuitive Proactive Pathways

Date: 2026-07-05  
Project: `pathway-operating-layer`  
Active work ID: `W-20260629-pathway-operating-layer-elevate-pathway-to-world-2819f3`  
Mode: audit + spec  
Do not build yet.

## Goal

Make `/pathway` intuitive and proactive across projects by preserving understanding between pathways.

The user should not need to remember what research concluded, what design changed, or what security blocked. The pathway router should recall the previous pathway outputs, explain what changed, and make the next recommendation depend on that context.

## Core Problem

The current system has a strong proof ledger but an incomplete learning loop.

It records:

- pathway recommended,
- pathway evidence,
- verifier result,
- coverage state.

It does not yet reliably carry:

- pathway result in plain English,
- changed assumptions,
- more relevant concerns,
- less relevant or deferred concerns,
- what the next pathway must use,
- what should not be done yet.

That is why the research step could be logged, then the next step could still feel context-poor.

## Product Principle

Every pathway must leave a baton for the next pathway.

The baton is not a chat summary. It is a structured carry-forward object bound to the work ID and evidence artifact.

## Proposed Data Model

Add a carry-forward record per completed pathway.

```json
{
  "carry_forward_id": "CF-...",
  "work_id": "W-...",
  "project": "pathway-operating-layer",
  "pathway": "research",
  "source_artifact": ".planning/full-cycle-pathway-marketplace/research/DOSSIER.md",
  "summary": "Research says keep the proof spine, add outcome profiles and risk overlays, defer field until P0 safety is done.",
  "what_changed": [
    "Govern must pin the P0 proof/closeout safety slice, not a generic marketplace rebuild."
  ],
  "more_relevant": [
    "proof command drift",
    "empty-itinerary closeout",
    "trivial verifier acceptance",
    "live risk overlay for security",
    "tenant isolation proof"
  ],
  "less_relevant": [
    "adding many pathway nouns",
    "building a full /pathway go executor first",
    "external market research"
  ],
  "next_pathway_must_use": [
    "The govern artifact must state the first implementation metric using the research priorities."
  ],
  "do_not_do_yet": [
    "Do not implement field before P0 proof safety is stable."
  ],
  "open_decisions": [
    "Should field start as a pathway or risk overlay?",
    "Should trivial verifier rejection apply retroactively or only to new proofs?"
  ],
  "created_at": "2026-07-05T00:00:00Z"
}
```

## Minimum Shippable Slice

Ship continuity before marketplace expansion.

### Rung 1 — State And Carry-Forward Contract

Deliver:

- `.planning/STATE.md` present-state truth.
- Carry-forward schema documented.
- Evidence artifacts required to include a carry-forward section or sidecar JSON.

Acceptance:

- A new verifier can inspect a pathway evidence artifact and fail if it lacks carry-forward fields.
- `pathway-next` can identify the latest carry-forward for the active work item.

### Rung 2 — `pathway-next` Uses Prior Outputs

Deliver:

- `pathway-next --json` includes `latest_carry_forward`.
- The Markdown/HTML report includes "What previous work changed."
- The recommendation explains how the previous pathway output affects the next pathway.

Acceptance:

- In the current research-to-govern scenario, the report says govern must pin the P0 proof/closeout safety slice identified by research.
- The report explicitly marks `field` as deferred until proof safety is stable.

### Rung 3 — Proof Safety Fixes

Deliver:

- Generated proof handoffs use `--verify-cmd`, not `--verified-by`.
- New work-start requires tier or profile. No new empty-itinerary work items.
- Trivial verifier or failed canary cannot count as closeout-ready proof for new proofs.

Acceptance:

- Tests fail on old `--verified-by` generated command text.
- Tests fail if a new work item starts with empty itinerary.
- Tests fail if a trivial verifier proof makes a pathway closeout-ready.

### Rung 4 — Outcome Profiles And Risk Overlays

Deliver:

- Outcome profile classifier for common work shapes.
- Risk overlays for auth, tenant, RLS, PII, external user, client portal, production data, migrations, UI, LLM/agent behavior, customer packets, deploys, mocks/fixtures.

Acceptance:

- A `live` goal mentioning tenant/RLS/client portal forces security and data.
- A UI goal forces design proof requirements.
- A customer review goal forces field or field-pending status.

### Rung 5 — Field Pathway

Deliver:

- `field` pathway added only after Rungs 1-4 pass.
- Field pathway proof bundle includes human owner, exact ask, packet path, sent/not-sent status, feedback capture, decision classification, and adoption signal or blocker.

Acceptance:

- Koho Template Review-style work can show "client packet ready but not sent" without implying field proof.
- Excerpa-style review/correction loops can show customer/operator feedback as first-class proof.

## Verifier Design

The verifier for this spec must check behavior, not only file existence.

Required checks:

1. `pathway-next --json` exposes carry-forward context after at least one pathway proof.
2. Rendered pathway report includes:
   - previous pathway result,
   - what changed,
   - more relevant,
   - less relevant,
   - next must use,
   - source artifact.
3. Generated proof commands use `--verify-cmd`.
4. New work-start without tier/profile cannot create empty itinerary.
5. Risk overlays force security/data on risky live work.
6. Trivial verifier or failed canary proofs are visible as blockers for closeout readiness.

## Environment Audit

### CLAUDE.md

Repo-local `CLAUDE.md` is useful but thin. It documents edit location, stdlib-only rule, tests, and CLI write boundaries. It does not yet explain the pathway carry-forward contract because that contract does not exist.

Required update after implementation:

- Add "Pathway continuity contract."
- Add "Every evidence artifact must produce carry-forward."
- Add "Do not update docs without tests proving command/report behavior."

### Knowledge Base

Current repo-local `.planning` now has research evidence and present-state truth. This is the right place for project-specific spec and state.

Operator-facing audit artifacts belong in `memory-vault/operator-artifacts/`, with project-local spec as source of truth for implementation.

### Skills

Do not create a new skill for carry-forward.

Use existing skills:

- `$pathway` as the router.
- `$karpathy` for spec/verify/audit.
- `research-stack` for cited unknowns.
- `planning-stack` concepts for acceptance criteria.
- `review-stack` and Codex review for second-pass critique.

The carry-forward behavior belongs in the operating layer, not a new skill description that increases every-turn overhead.

### Rules And Enforcement

Current hard rails exist for secrets, destructive shell actions, validation-before-stop, commit gate, absolute paths, and Koho guardrails.

Missing enforcement is pathway-specific:

- no proof without real carry-forward,
- no new empty itinerary,
- no `--verified-by` generated proof command,
- no trivial verifier closeout,
- no risky live itinerary without security/data.

These should be enforced in tests and CLI behavior, not prose.

## Non-Goals

- Do not implement a general DAG engine.
- Do not add many pathway categories.
- Do not make the CLI run arbitrary build tools as a hidden executor before proof safety is fixed.
- Do not solve multi-user database storage in this slice.
- Do not rewrite the operating layer into multiple modules yet.

## First Build Slice

Implement the carry-forward contract and report surface first.

Why this first: it directly fixes the user-visible failure from the research step. It also makes every later hardening step easier because the system can explain what previous proof changed.

First slice acceptance:

- The current research dossier produces carry-forward.
- The next govern recommendation explicitly consumes that carry-forward.
- The rendered report explains the research delta.
- Tests prove the behavior with a fixture work item.

---

# Final-State Push Spec — World-Class Pathway Refinements

Date: 2026-07-06  
Mode: Karpathy `spec`  
Source audit: `/Users/alexhale/Projects/memory-vault/operator-artifacts/2026-07-06-pathway-command-hypercritical-audit.md`  
Routing note: two active `pathway-operating-layer` work items currently exist. This spec belongs to the world-class pathway operating-layer outcome, not the newer Hermes agent-card scanner task. Do not log proof against the scanner work item.

## Goal

Turn `/pathway` / `$pathway` from a strong proof ledger into a self-measuring full-cycle development operating system.

The outcome is not "add features." The outcome is:

> Raise the pathway command from 82/100 to 92+/100 by making every pathway repeatably provable, every audit measurable from the CLI, every field/research/release handoff structured, and every cross-environment config say the same thing.

## Governing Metric

Primary metric:

- `pathway-audit --project pathway-operating-layer --json` reports an overall score of `>= 92`.

Required supporting metrics:

- Global `proved_rate >= 0.50` or, before enough volume exists, the command reports a credible path to `0.50` by pathway with no hidden denominator.
- `research` pathway proof conversion improves from `0.076` to `>= 0.25`.
- `field` pathway proof conversion improves from `0.154` to `>= 0.30`.
- Every pathway has a verifier template family and at least one test proving the template rejects hollow proof.
- Cross-environment wording drift count is `0` for pathway order, core/extension language, proof syntax, and authority boundary.

## Product Decision

Keep the current pathway catalog. Do not add more nouns.

The highest leverage is to make each existing pathway stricter and easier to prove:

1. Add per-pathway verifier templates.
2. Generate the scorecard from the CLI as `pathway-audit`.
3. Standardize field receipts.
4. Harden research proof.
5. Normalize pathway ordering and wording across Claude, Codex, agents, Hermes, and README.
6. Stabilize pathway-trust timing.
7. Keep overlays typed so deferrals never become active risk.
8. Add a release state machine for preview, canary, production, rollback, and sent state.

## Non-Goals

- Do not add LangGraph, LlamaIndex, pgvector, hosted vector stores, or A2A to the core CLI.
- Do not make vault search authoritative.
- Do not add more first-class pathways.
- Do not turn `/pathway go` into an unrestricted executor.
- Do not auto-deploy, auto-send, auto-close, force-push, or mutate production state.
- Do not let implementation absorb design, quality, security, release, field, or docs proof.

## Eight Build Slices

Each slice must ship as a small end-to-end change with tests, a real artifact, and a verifier command. The slices are ordered by measured leverage.

### Slice 1 — Per-Pathway Verifier Templates

Decision:

Every pathway needs a durable proof shape so operators stop improvising `--verify-cmd`.

Deliver:

- A stdlib-only verifier-template registry in the operating layer.
- Templates for all 11 core pathways plus `field`.
- Template metadata: pathway, required artifact fields, required carry-forward fields, recommended verifier command shape, rejection checks, and example evidence.
- Absolute-path-first guidance for verifier scripts in `memory-vault/operator-artifacts/verifiers/`.

Acceptance:

- `pathway-next` card can name the recommended verifier template for the next pathway.
- `work-log` can report whether the artifact satisfies the pathway's template shape.
- Tests prove each template rejects at least one hollow proof.
- Generated proof handoffs never use `--verified-by` as the proving path.

Verifier:

- Run full test suite.
- Run a fixture for each pathway that attempts weak proof and confirms it stays unproved or flagged incomplete.
- Run a positive fixture for at least `govern`, `research`, `field`, `release`, and `quality`.

### Slice 2 — `pathway-audit`

Decision:

Manual scorecards drift. The CLI must grade its own command, catalog, cross-config alignment, and proof telemetry.

Deliver:

- New subcommand: `pathway-audit --project <project> --json`.
- Markdown/HTML report output in `memory-vault/operator-artifacts/`.
- Overall score and per-pathway score using the rubric from the 2026-07-06 audit.
- Drift checks across:
  - `commands/pathway.md`
  - `/Users/alexhale/.agents/skills/pathway/SKILL.md`
  - `/Users/alexhale/.claude/CLAUDE.md`
  - `/Users/alexhale/.codex/AGENTS.md`
  - `/Users/alexhale/Projects/agents/CLAUDE.md`
  - Hermes technical-operator profile docs
  - `README.md`

Acceptance:

- JSON includes `overall_score`, `pathway_scores`, `metric_snapshot`, `drift_findings`, `highest_value_refinements`, and `report/html` paths.
- The current audit can be reproduced without hand-written scoring.
- Score changes are explainable by changed rubric fields, not opaque magic.

Verifier:

- Fixture with intentionally drifted docs produces non-zero drift findings and lower score.
- Fixture with aligned docs produces no catalog/order drift.
- Report includes the eight highest-value fixes and measured proof-rate baseline.

### Slice 3 — Field Receipts

Decision:

`field` is where internal proof meets real operator/customer acceptance. It needs structured receipts, not prose.

Deliver:

- Field receipt schema:
  - reviewer
  - reviewer role
  - artifact shown
  - artifact SHA-256
  - reviewed_at
  - send_state: `not-ready`, `send-ready`, `sent`, `blocked`
  - feedback summary
  - what changed
  - unresolved blockers
  - next pathway impact
- Field carry-forward extraction.
- Field template/verifier.

Acceptance:

- Customer review, operator validation, review packet, client portal, approval, outreach, or send-state signals require `field`.
- A "send-ready" packet does not count as "sent."
- Field proof cannot pass without reviewer identity, artifact hash, feedback/blocker status, and next-pathway impact.

Verifier:

- Positive fixture: Koho-style review packet with reviewer and artifact hash passes.
- Negative fixture: internal note saying "client reviewed" without artifact hash fails.
- Negative fixture: `send-ready` does not count as `sent`.

### Slice 4 — Research Proof Hardening

Decision:

Research has the lowest proof conversion and the highest theater risk. It must prove what changed.

Deliver:

- Research proof schema:
  - question
  - claim table
  - source quality per claim
  - unknowns classified as blocker/warn/info
  - contradictions
  - implementation-ready priorities
  - next pathway deltas
  - do-not-do-yet list
- Research verifier template.
- Report section that shows how research changed the next recommendation.

Acceptance:

- A research artifact without source-backed claims cannot prove.
- A research artifact without "what changed" cannot prove.
- `pathway-next` explains the research delta before the next recommendation.

Verifier:

- Recreate the research-to-govern fixture.
- Confirm `latest_carry_forward` changes `govern` wording.
- Confirm an uncited research artifact is rejected or flagged incomplete.

### Slice 5 — Cross-Environment Wording Normalization

Decision:

Claude, Codex, agents, Hermes, README, and command docs must describe the same system.

Canonical wording:

- "11 core pathways plus first-class `field` extension."
- Canonical order: `govern, research, data, security, design, implementation, quality, field, observability, techdebt, release, docs`.
- Host-specific prefix: Claude uses `/pathway`; Codex uses `$pathway`; both route to the same operating-layer engine.
- Proof requires real artifact plus executed `--verify-cmd`; `--verified-by` is attestation only.
- RAG/search/vault notes are advisory; work items, proofs, controls, carry-forward, and pilot ledgers are authoritative.

Deliver:

- Normalize all relevant docs/configs.
- Add drift detector in `pathway-audit`.

Acceptance:

- `pathway-audit` reports zero wording/order/proof-syntax drift across configured surfaces.
- README no longer contradicts code order or core/extension language.

Verifier:

- Static check across configured files.
- Negative fixture with old ordering proves drift detector fires.

### Slice 6 — Pathway-Trust Timing Stabilization

Decision:

Trust status should represent functional failure, not local CPU timing noise.

Deliver:

- Split trust check result into:
  - `status`: functional pass/warn/fail.
  - `performance_status`: pass/warn/fail for elapsed budgets.
- Keep timing warnings visible without making functional trust nondeterministic unless the command times out or fails.
- Adjust tests accordingly.

Acceptance:

- Slow-but-successful trust checks do not randomly flip `pathway_trust.status` from pass to warn.
- Timing warnings still appear in trust reports.
- A timeout or non-zero exit still fails trust.

Verifier:

- Fixture simulates slow successful command and confirms functional status remains pass with performance warning.
- Fixture simulates timeout and confirms status fail.

### Slice 7 — Typed Overlay State

Decision:

The system must never infer active risk from deferred text like "do not add A2A yet."

Deliver:

- Carry-forward typed fields:
  - `active_risk_overlays`
  - `deferred_risk_overlays`
  - `resolved_risk_overlays`
  - `overlay_notes`
- Scorer only uses `active_risk_overlays` and current goal/findings as active gates.
- Reports show deferred overlays as constraints, not reasons to re-run pathways.

Acceptance:

- Deferral text mentioning tenant/RLS/A2A/prod does not trigger active overlays.
- Active typed overlays still trigger required pathways.
- A resolved overlay can dampen or remove the pathway pressure only when proof exists.

Verifier:

- Existing deferral-loop regression remains green.
- New typed overlay fixtures cover active, deferred, and resolved overlays.

### Slice 8 — Release State Machine

Decision:

Release must distinguish readiness from mutation. Preview, canary, production, rollback, and external send are separate states.

Deliver:

- Release receipt schema:
  - preview_status
  - canary_status
  - production_status
  - rollback_status
  - external_send_state
  - feature_flag_state
  - deploy_artifact
  - verification_artifact
  - rollback_artifact
  - human_approval
- Release verifier template.
- Explicit refusal to treat `send-ready` as `sent`.

Acceptance:

- Release proof can prove preview readiness without production mutation.
- Production mutation requires human gate and rollback proof.
- External send requires explicit send state.
- Release closeout cannot pass with rollback missing when `rollback` overlay is active.

Verifier:

- Positive fixture: preview-ready, no prod mutation, safe release proof.
- Positive fixture: prod deploy with rollback artifact and human approval.
- Negative fixture: prod deploy missing rollback fails.
- Negative fixture: send-ready claimed as sent fails.

## Implementation Order

1. `pathway-audit` skeleton and scorecard JSON.
2. Cross-environment drift detector.
3. Verifier-template registry.
4. Research and field templates first, because they have the worst proof conversion and highest theater risk.
5. Trust timing split.
6. Typed overlay state.
7. Release state machine.
8. Fill remaining pathway templates and scorecard refinements.

Reason for this order: the audit command gives a live measuring surface before the rest of the work changes behavior. Research and field come early because they are the measured weak points. Release comes later because it touches high-risk semantics and should be built after typed receipts are stable.

## Global Verifier For This Spec

The final verifier must prove:

1. `python3 scripts/tests/operating_layer_test.py` passes.
2. `pathway-audit --project /Users/alexhale/Projects/pathway-operating-layer --json` exits 0.
3. Audit JSON reports:
   - `overall_score >= 92`
   - zero cross-config drift for canonical pathway language
   - all pathways have verifier templates
   - research and field templates exist
   - release state machine exists
   - trust timing split exists
   - typed overlay fields exist
4. Negative fixtures prove hollow research, hollow field, fake release send, and deferred overlay text cannot pass as proof.
5. Generated work-log commands use `--verify-cmd` and never present `--verified-by` as proof.

## Carry-Forward Baton Required For This Spec

When this spec is proved, its evidence artifact must include:

### Summary

The pathway command was specified for the final world-class refinement push: verifier templates, pathway-audit, field receipts, research hardening, wording normalization, trust timing stabilization, typed overlays, and release state machine.

### What Changed

- The work is no longer "expand the marketplace"; it is "raise proof conversion and auditability."
- Research and field are prioritized because they have the weakest proof conversion.
- `pathway-audit` becomes the measuring surface for all further refinements.

### More Relevant

- Per-pathway verifier templates.
- Generated scorecard.
- Research and field proof schemas.
- Config drift detector.
- Typed overlay state.
- Release receipt state machine.

### Less Relevant

- New pathway categories.
- Hosted RAG or vector search.
- Broad executor autonomy.
- More prose-only command documentation.

### Next Pathway Must Use

- `govern` must pin `overall_score >= 92` and proof-rate improvement as the business metric.
- `implementation` must start with `pathway-audit` because it creates the measuring surface.
- `quality` must include negative fixtures for hollow proof and drift.

### Do Not Do Yet

- Do not implement remote-agent verifier submission.
- Do not auto-run release/deploy/send paths.
- Do not add new first-class pathways.
- Do not make RAG authoritative.

### Open Decisions

- Whether `pathway-audit` should fail non-zero below threshold or report score only.
- Whether verifier templates should be stored as Python functions, JSON schemas, or Markdown-plus-code contracts.
- Whether proof-rate targets should be global only or per-pathway-gated before autonomy changes.
