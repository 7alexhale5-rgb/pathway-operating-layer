# Pathway Operating Layer — reference

The operating layer turns review/audit findings into a single daily question: **"what's the
next-best engineering pathway for this project, and is it getting acted on?"** It is driven by
`~/.claude/scripts/operating-layer.py` and fronted by the `/pathway` slash command.

## The daily flow

1. **Ask** — `/pathway <project>` → the next-best pathway + the one move to make. Read-only.
2. **Start** — `/pathway <project> "<goal>"` → opens a tracked outcome (one shared **work ID**).
3. **Log** — `/pathway <project> <pathway> <evidence-file>` → records that pathway done, with proof.
4. **Close** — `/pathway <project> done` → closes the outcome (blocks if controls/evidence/staleness unresolved).

You never type the CLI; `/pathway` (`~/.claude/commands/pathway.md`) drives it. The CLI is below for reference.

## Commands (`operating-layer.py`)

| Command | What it does |
|---|---|
| `pathway-next --project <p>` | Scores all 11 pathways for the project, applies foundation-first order, recommends the next move + Karpathy card. Logs the recommendation for the metric. |
| `ingest-review --project <p> --input <review.json>` | Persists a review-stack `--json` finding pool to `<p>/.planning/review/latest-findings.json` (overwrite), pathway-tagged. `--input -`/omit reads stdin. |
| `work-start --project <p> --goal "<g>"` | Opens a tracked outcome; returns the shared work ID. |
| `work-log --work-id <id> --pathway <p> --kind <k> --evidence <file>` | Logs a pathway run + measurement against the shared ID. Evidence must be a real file. |
| `work-close --work-id <id>` | Closes the outcome; refuses if open controls / missing evidence / stale measurements. |
| `work-status --work-id <id>` / `work-daily` | Status of one outcome / the daily dashboard. |
| `pathway-metric [--window-days N] [--gate-target R]` | Computes the recommendation-action rate (see Metric). |

## How findings reach the router

- **review-stack** runs the 11 pathway guards (`security-guard.py`, `migration-guard.py`, `govern.py`, …)
  and, at completion (SKILL.md Step 7.5), pipes its `--json` pool through `ingest-review`.
- The router reads `<project>/.planning/review/latest-findings.json` plus any finding-shaped
  `.planning/**/*.{json,ndjson,jsonl}`, and the operating layer's own env-scoped findings.
- Each finding routes to a pathway by guard-id prefix — `sec-`→security, `mig-`→data, `gov-`→govern,
  `rel-`→release, `impl-`→implementation, `q-`→quality, `obs-`→observability, `td-`→techdebt,
  `ff-`/`rs-`→research — else by keyword.

## Ranking doctrine

- **Foundation-first:** with nothing logged, `research` (100) then `govern` (80) lead — never plan from
  vague context, pin the metric before building.
- **Live fires escalate:** error-severity findings are weighted so a cluster (3+) out-ranks the
  foundation gates. One P0 stays below; a pile of P0s overrides "do research first."
- **Freshness gate:** a `latest-findings.json` older than `REVIEW_STALE_DAYS` (14) is not ingested;
  the router emits a `local:stale-review` finding telling you to re-run review-stack.

## The metric (govern decision, 2026-06-27)

**Recommendation-action rate** — of `pathway-next` recommendations, the fraction that get a matching
`work-log` (same project + pathway) within 1 day. **Gate: ≥ 0.50.** Below that, the router is a
dashboard, not an operating layer. Compute it: `operating-layer.py pathway-metric`.

## Data store

Central, never in project repos (except the review findings file the router reads):
`~/Projects/memory-vault/operator-intelligence/` — `work-items.ndjson`, `pathway-runs.ndjson`,
`pathway-measurements.ndjson`, `controls.ndjson`, `pathway-recommendations.ndjson`, `pathway-metric.json`.

## Catalog and risk overlays

Core catalog: `research, govern, data, security, release, implementation, quality,
observability, techdebt, design, docs` — plus `field` as the customer/operator validation
extension, used when human review, client UI, review packets, external approval, or
send-state gates exist.

Risk overlays: `tenant-authz`, `privacy-evidence`, `production-mutation`, `rollback`,
`supply-chain`, `incident-response`, `ui-proof`, `llm-agent-eval`, `human-gate`. These
inject mandatory gates. Do not mark one N/A without a structured reason and real evidence —
an overlay dismissed on assertion is an overlay that was never applied.

## The two hard rules

**Proof.** A real artifact, an executed `--verify-cmd`, and the result read back. Defined
once in [proof-standard.md](proof-standard.md) — do not restate it anywhere.

**Carry-forward.** Every completed pathway must leave context: what changed, what became
more or less relevant, what the next pathway must use, what not to do yet, open decisions,
and active risk overlays. `pathway-carry-forward.ndjson` is authoritative continuity memory
— RAG, grep, vault notes and old artifacts are advisory only.

## pathway-next and pathway-pilot

`pathway-next` must explain coverage, prior carry-forward, outcome profile, risk overlays,
proof requirements, and the one next command — not merely name a pathway.

`pathway-pilot` is the measured multi-project agentic-dev-team rehearsal: it records cohort
assignments, lead/critic/proof gates, review gates, baseline metrics, and a Markdown/HTML
operator report **without mutating project repos**.

## When NOT to use it

Pathway is stateful and per-project. Config work, one-off fixes and single-session tasks do
not belong in the ledger; putting them there dilutes the signal it exists to carry.

---

_Consolidated 2026-08-04. This doctrine was maintained in THREE places — this file plus the
always-on `~/.claude/CLAUDE.md` and `~/CLAUDE.md` — with the description, runtime paths,
pathway-pilot and carry-forward authority stated in more than one. `~/.claude/CLAUDE.md`
asserted that `~/CLAUDE.md` held "the fuller copy, kept there so it is not maintained
twice", which was measurably false. Both always-on files now point here. If you are about
to restate any of this in a CLAUDE.md, don't — edit this file instead._
