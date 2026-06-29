# pathway-operating-layer

Operator intelligence for engineering pathways. Ranks the next-best pathway for a
project (foundation-first), tracks the work against one shared ID, and feeds
review-stack findings back into the recommendation loop. The loop learns: closed
outcomes reweight future rankings and calibrate the tier→pathway map, recommendation
confidence is grounded in live evidence, and execution autonomy is earned by a proof
metric — the engine emits a `suggested_autonomy_tier` rather than assuming it.

The canonical source lives **here**; the files are symlinked into `~/.claude` so
Claude Code loads the slash command and the script resolves at its expected
absolute path. This repo exists so the work is version-controlled and `rm`-safe —
`~/.claude` is not git and holds secrets, so it is never `git init`ed.

## Layout

| Repo path | Symlinked to | Role |
| --- | --- | --- |
| `scripts/operating-layer.py` | `~/.claude/scripts/operating-layer.py` | CLI (28 subcommands) |
| `scripts/tests/operating_layer_test.py` | `~/.claude/scripts/tests/...` | Self-test suite (stdlib only) |
| `commands/pathway.md` | `~/.claude/commands/pathway.md` | `/pathway` front door |
| `references/pathway-operating-layer.md` | `~/.claude/references/...` | Design reference |

## Install (fresh machine)

```bash
git clone <remote> ~/Projects/pathway-operating-layer
~/Projects/pathway-operating-layer/install.sh   # idempotent; refuses to clobber real files
```

## Test

```bash
python3 ~/Projects/pathway-operating-layer/scripts/tests/operating_layer_test.py
```

303/303 checks pass. Includes an AST guard that fails the build on any duplicate
module-level constant/def name (the shadowing class a second-model review caught
that unit tests missed).

## Subcommands

28 in total. The pathway loop: `pathway-next` (recommend + `suggested_autonomy_tier`),
`pathway-trust`, `pathway-metric`, `pathway-run`, and `tier-calibrate` (measured
tier→pathway defaults from closed-outcome history — advisory, never auto-applied).
The work envelope: `work-start`, `work-log`, `work-close`, `work-cover`,
`work-status`, `work-daily`, `proof-add`, `proof-report`. Plus the operating-layer
scans (`intel`, `tools`, `portfolio`, `boundary`, `ingest-review`, …) and `all`.
Prefer the `/pathway` slash command over the raw CLI — it drives the work envelope so
no flags are memorized.

## Gotcha

The test resolves the CLI via `Path(__file__).resolve()` (follows symlinks) + the
relative `../operating-layer.py`, so the `scripts/tests/` ↔ `scripts/` layout must
be preserved for the symlinked install to exercise the repo copies.
