# Stable design docs and proof gates

## Inputs

- `pathway-operating-layer.md` (the design), `system-design-proof-gates.md`
  (per-pathway proof gates a critic can fail you on — also flags where
  `llm-agent-eval` proof must come from elsewhere), `world-class-data-boundary.md`,
  `world-class-govern-ledger.md`, `itinerary-coverage-spec.md`.

## Process

1. Read before arguing with the CLI's behavior — these are the one home for each
   design fact (`~/.claude/references/shared-standards.md` convention: one home per
   fact, everything else links to it).
2. Update in place when a design decision changes; do not duplicate the fact into
   `docs/` or a room `CONTEXT.md`.

## Outputs

- Current, dated-if-needed design references, linked from `scripts/CONTEXT.md` and
  `CLAUDE.md`.

## Human check

Alex approves a references change the same way he approves a design decision — read
and confirm before it governs the CLI's next edit.
