# Planning room: present state, per-feature pathway artifacts and handoffs

One job: hold the live state of the operating layer's own work and the per-feature pathway
artifacts that prove it. Paths relative to the repo root.

## Inputs

- `STATE.md` (and its rendered `STATE.html`): present state, active work ID, what is verified now.
- Per-feature folders and files named `YYYY-MM-DD-<slug>` (for example
  `2026-08-30-per-project-observability-contracts.md`, `2026-07-17-selected-work-pathway-next-scoring/`).
  They hold one artifact per pathway (`DATA.md`, `DOCS.md`, `GOVERN.md`, `IMPLEMENTATION.md`, …)
  with receipts, and a `research/` dossier where research ran.
- Feature folders without a date (for example `waiver-authority/`, `approval-issue-agent-guard/`).
- Dated handoffs: `HANDOFF-<TOPIC>-<YYYYMMDD>.md`.
- Missing input: a pathway marked proved with no artifact or receipt here is not proved.

## Process

1. Start or resume work by reading `STATE.md`, then compare its claims with current files and the
   suite (`python3 scripts/tests/operating_layer_test.py`).
2. New feature: create `YYYY-MM-DD-<slug>/` and write one artifact per itinerary pathway as the
   CLI's next action directs. Research dossiers go in `<feature>/research/`. When the
   itinerary's pathways or overlays derive focus tags, the card suggests them
   (`/research-stack --deep (suggested focus: ...)`); the operator confirms at research-stack's
   scope gate. Keep the `focus:` front matter: the research verifier then requires each tag's
   addendum section.
3. Proposal, not built: research-stack has no `--json` flag yet, so unresolved "Coverage gaps"
   do not flow to `rs-<tag>-<slug>` findings through `ingest-review` today.
4. When a phase ends, write a dated `HANDOFF-*.md` and update `STATE.md` (date, active work ID,
   verified numbers read from the running system).
5. Never edit a closed feature's receipts. A correction is a new dated artifact.

## Outputs

- Updated `STATE.md`; new feature folders, artifacts, receipts and handoffs.

## Human check

Alex reads `STATE.md` against `git log` and the latest suite run. Pass: every "verified now"
claim matches a receipt or a command result from that date. Fail: correct `STATE.md` before the
next work item starts.
