# Govern Proof - Pathway Command 92+ Push

Date: 2026-07-06
Project: `pathway-operating-layer`
Work ID: `W-20260706-pathway-operating-layer-raise-pathway-command-to-3402fb`
Pathway: `govern`
Recommendation ID: `REC-pathway-operating-layer-govern-1326`
Status: pass

## Decision

Raise the pathway command from a hand-audited 82/100 class system to a self-audited 92+/100 operating layer by shipping the smallest measurable sequence that improves proof quality, field/research continuity, release safety, and cross-environment consistency.

This is not a marketplace expansion. The governed outcome is a measurable auditability and proof-integrity upgrade.

## Governing Metric

Primary success metric:

- `pathway-audit --project /Users/alexhale/Projects/pathway-operating-layer --json` reports `overall_score >= 92`.

Supporting metrics:

- Research proof conversion reaches `>= 0.25` from the observed `0.076` baseline.
- Field proof conversion reaches `>= 0.30` from the observed `0.154` baseline.
- Cross-environment wording/order/proof-syntax drift count is `0`.
- Every pathway has a verifier-template family and at least one hollow-proof rejection test.
- Generated proof commands use executed `--verify-cmd`, not attestation-only wording as proof.

## Acceptance Gate

This outcome is not eligible for closeout until all of the following are true:

- `python3 /Users/alexhale/Projects/pathway-operating-layer/scripts/tests/operating_layer_test.py` exits 0.
- `python3 /Users/alexhale/.claude/scripts/operating-layer.py pathway-audit --project /Users/alexhale/Projects/pathway-operating-layer --json` exits 0.
- The audit JSON reports `overall_score >= 92`.
- The audit JSON reports zero canonical pathway drift across Claude, Codex, agents, Hermes, command docs, and README surfaces.
- The audit JSON proves verifier templates exist for `govern`, `research`, `data`, `security`, `design`, `implementation`, `quality`, `field`, `observability`, `techdebt`, `release`, and `docs`.
- Negative fixtures reject hollow research proof, hollow field proof, fake release send proof, and deferred overlay text treated as active risk.

## First Implementation Slice

Start with `pathway-audit`, not verifier templates.

Reason: the audit command becomes the measuring surface for every later refinement. Without it, "92+" remains another hand-written assessment and the work can drift into broad command documentation.

Slice 1 must deliver:

- `pathway-audit --project <project> --json`.
- Markdown and HTML audit report output.
- `overall_score`, `pathway_scores`, `metric_snapshot`, `drift_findings`, `highest_value_refinements`, `report`, and `html` in JSON.
- Drift checks for pathway order, core/field language, proof syntax, and authority boundary across configured surfaces.
- Tests proving a deliberately drifted fixture lowers the score and an aligned fixture reports zero drift.

## Scope Boundaries

In scope:

- CLI audit surface.
- Cross-environment normalization checks.
- Per-pathway verifier templates.
- Field receipt schema.
- Research proof schema.
- Trust timing split.
- Typed overlay state.
- Release receipt state machine.
- Tests and generated operator reports.

Out of scope:

- Hosted RAG, vector stores, LangGraph, LlamaIndex, pgvector, or A2A in the core CLI.
- New first-class pathway nouns beyond the already accepted `field` extension.
- Auto-deploys, external sends, force-pushes, production flag flips, or auto-closeout.
- Treating vault/RAG/search as authority for proof state.

## Risk And Gate Policy

Active gates:

- `rollback`: release proof must distinguish preview, canary, production, rollback, feature flag, and external send state.
- `human-gate`: field proof must distinguish `send-ready`, `sent`, `blocked`, and `not-ready`.
- `llm-agent-eval`: pathway command behavior affects agentic development loops, so quality/security/observability proof must include negative fixtures and traceability checks.

Do not mark any of these not applicable without a structured reason and real evidence.

## Verifier Good

A valid govern proof for this outcome must show:

- One measurable target: `overall_score >= 92`.
- One first implementation slice: `pathway-audit`.
- The reason `pathway-audit` comes before broad implementation.
- Closeout acceptance criteria with executed verifier commands.
- Explicit non-goals that prevent unsafe autonomy creep.
- A carry-forward baton for the next pathway.

## Summary

The pathway command refinement is now governed as a score-moving proof-integrity outcome: ship `pathway-audit` first, use it to measure progress toward `overall_score >= 92`, then use the audit surface to guide verifier templates, field receipts, research hardening, trust timing, typed overlays, and release receipts.

## What Changed

- The outcome is pinned to `overall_score >= 92`, not a vague "world-class pathway marketplace" label.
- `pathway-audit` is the first implementation slice because it creates the measuring surface for all later work.
- Research and field proof conversion are explicit supporting metrics.
- The active work must remain on `W-20260706-pathway-operating-layer-raise-pathway-command-to-3402fb`, not the older agent-card-scanner item.

## More Relevant

- `pathway-audit` command shape and JSON contract.
- Cross-environment drift detection.
- Per-pathway verifier-template registry.
- Hollow-proof rejection tests.
- Research proof schema with cited claims and deltas.
- Field receipt schema with reviewer, artifact hash, send state, and feedback.
- Release receipt state machine.
- Trust timing split and typed overlay state.

## Less Relevant

- Adding more pathway names.
- Building unrestricted `/pathway go` execution.
- Hosted RAG or vector search.
- Remote A2A verifier submission.
- Prose-only command documentation.

## Next Pathway Must Use

- `research` must use this govern metric to confirm whether the existing dossiers are enough for `pathway-audit` implementation or whether any current unknown blocks the audit schema.
- `implementation` must start with `pathway-audit`, not template hardening, unless research finds a blocking schema flaw.
- `quality` must verify hollow-proof rejection and drift fixtures, not just happy-path command output.
- `release` must prove preview/canary/production/rollback/send states separately before any release claim.

## Do Not Do Yet

- Do not implement remote-agent handoff or A2A proof submission.
- Do not add new first-class pathways.
- Do not make RAG authoritative.
- Do not auto-run deploy, send, force-push, production flag, or closeout actions.
- Do not log proof against `W-20260706-pathway-operating-layer-fix-agent-card-scanner-s-c64f27`.

## Open Decisions

- Should `pathway-audit` exit non-zero below 92, or report the score while allowing CI to decide thresholds?
- Should verifier templates be Python functions, JSON-like schema dictionaries, Markdown contracts, or a minimal hybrid?
- Should proof-rate targets be global only, or should low-conversion pathways gate autonomy independently?
- Should explicit work selection be added to `$pathway` UX so multiple active work items cannot hijack `go`?

## Active Risk Overlays

- rollback
- human-gate
- llm-agent-eval
