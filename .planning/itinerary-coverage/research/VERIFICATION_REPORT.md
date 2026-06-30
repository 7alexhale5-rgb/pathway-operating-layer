# Research Dossier — Pathway Itinerary Coverage

**Date:** 2026-06-29 · **Feature:** itinerary-coverage · **Type:** internal tooling (no external dependencies)

## Question this work depends on
"Does the operating-layer engine already track a required-pathway set per outcome, or only single-next-step + blockers — and where is the closeout gate?"

## Findings (grounded in source, cited — all info-level, zero external unknowns)

| Claim | Evidence | Confidence |
|---|---|---|
| 11 pathways defined with `foundation` flags; research + govern are foundation gates | `scripts/operating-layer.py:121-221` (`PATHWAY_DOCTRINE`) | certain |
| Per-pathway best-execution profiles exist for `go` | `scripts/operating-layer.py:223-227` (`PATHWAY_EXECUTION`) | certain |
| Work items stored in `work-items.ndjson`; upsert merges by `work_id` | `scripts/operating-layer.py:568, 718-730` | certain |
| Closeout readiness gates on open controls + missing evidence + stale — **no required-set notion** | `scripts/operating-layer.py:2196-2226` (`ready = bool(item and runs and not open_controls and not missing_evidence and not stale)`) | certain |
| A never-run pathway is never a control, so it is invisible to `work-close` | absence: no `itinerary`/`required_pathway`/`coverage` symbols in engine (grep) | certain |

## Unknowns classified
- **blocker:** none.
- **warn:** none — change is additive; one gate site (`work_status_summary`).
- **info:** exact arg-parser wiring for new `--tier` / `work-cover` — resolved at edit time by reading each `add_parser` block.

## Conclusion
No external research required (no new domain, library, or market question). The design is fully determined by the existing engine, read directly. Proceed to SPEC. The coverage gate is enforceable by extending exactly one function (`work_status_summary`) plus storing an `itinerary` at `work-start`.
