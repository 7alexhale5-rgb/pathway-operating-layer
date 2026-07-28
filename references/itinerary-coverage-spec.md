# Pathway Itinerary — coverage by construction (design reference)

Date: 2026-06-29 · TECH · Decisions locked: engine-enforced + tiered-by-done-level.
Files: scripts/operating-layer.py (engine) + commands/pathway.md (skill prose).

GOAL: the router becomes a supervisor that guarantees every necessary engineering
pathway runs before an outcome can close — nothing skipped. Today a never-run
pathway is never flagged, so work-close can't see it's missing. Fix it in the
engine, not in prose.

MODEL: START seeds an itinerary (required pathway set) onto the work item, sized by
the target "done" tier. Each `go` runs the next OPEN-REQUIRED pathway, proves it,
logs it, and may APPEND a revealed pathway. `done` is HARD-REFUSED until every
itinerary pathway is proved (real artifact) or na (explicit reason).

TIER -> REQUIRED PATHWAYS (cumulative supersets):
  Demoable          : govern, implementation, quality
  Live              : + data, observability, release, docs
  Production-secure : + research, security, techdebt
Keyword-gated adds (any tier):
  design   <- ui|ux|screen|component|page|frontend|layout|form|dashboard|design
  research <- new|evaluate|spike|investigate|unknown|should we   (Demoable/Live)
  data     <- schema|migration|db|table|supabase|postgres        (Demoable)
Canonical order: govern, research, data, security, design, implementation,
  quality, observability, techdebt, release, docs.

ENGINE TOUCHPOINTS (surgical, one gate site):
  1. PATHWAY_TIERS + PATHWAY_KEYWORD_GATES constants beside PATHWAY_DOCTRINE.
  2. compute_itinerary(tier, goal) -> ordered [{pathway, status:"required"}].
  3. work-start: add --tier (default live); store tier + itinerary on the item.
  4. work-log: on a pathway proof, flip that itinerary entry -> proved.
  5. work-cover (new): --pathway X --na --reason "..." ; --add X.
  6. work_status_summary (line ~2196): itinerary_open=[required]; ready = ... and
     not itinerary_open; return tier, itinerary, coverage. work-close inherits it.
  7. pathway-next: when a work item exists, recommended_pathway = first
     OPEN-REQUIRED itinerary pathway; include itinerary + coverage in JSON.

SKILL PROSE (commands/pathway.md):
  START accepts/asks the tier, shows + stores the itinerary. go/ASK/EXECUTE lead
  with coverage ("Pathway 3 of 7 - remaining: security, observability, docs").
  CLOSE explains the coverage refusal in plain English.

VERIFIER (prove on a real throwaway work item):
  1. work-start --tier production-secure seeds full set; --tier demoable seeds
     exactly govern/implementation/quality.
  2. work-close REFUSED with the exact list of un-proved pathways.
  3. work-log a pathway -> status flips to proved; coverage advances; pathway-next
     recommends the next OPEN-REQUIRED, not a global max.
  4. work-cover --na with reason -> no longer blocks; reason recorded.
  5. all proved-or-na -> work-close SUCCEEDS.
  6. net new concepts <= 3; gate in exactly one function.

OUT OF SCOPE (anti-overengineering): no DAG engine, no new autonomy tiers, no
auto-NA, no per-pathway sub-itineraries.
