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
