# pathway-operating-layer — agent context

Canonical source for the pathway operating layer. Symlinked into `~/.claude`
(see README). **Never `git init ~/.claude`** — it holds secrets. Edit files here;
the symlinks make changes live immediately.

## Where to go

This repo follows ICM (Jake Van Clief's folder method): this file routes, each room's
`CONTEXT.md` holds its contract.

| Task                                                     | Go to         | Read                                           | Skills |
| -------------------------------------------------------- | ------------- | ---------------------------------------------- | ------ |
| Change the CLI, its ledger writes or its own test suite  | `scripts/`    | [scripts/CONTEXT.md](scripts/CONTEXT.md)       | none   |
| Working research, proof-integrity or scanner-scope notes | `docs/`       | [docs/CONTEXT.md](docs/CONTEXT.md)             | none   |
| Look up a stable design doc or proof gate                | `references/` | [references/CONTEXT.md](references/CONTEXT.md) | none   |
| Run or extend the staleness/integrity test suite         | `tests/`      | [tests/CONTEXT.md](tests/CONTEXT.md)           | none   |

`contracts/`, `hooks/`, `security/`, `skills/`, `commands/` stay where their
registrations expect them (the approval-issue guard, the `/pathway` skill and slash
command, the observability contract) — `scripts/CONTEXT.md` points to each. Root files
stay put: `README.md`, `LICENSE`, `install.sh`.

## Rules

- After editing any file, run the suite: `python3 scripts/tests/operating_layer_test.py`. It must stay green before commit.
- Preserve the `scripts/` ↔ `scripts/tests/` relative layout — the suite resolves the CLI through it.
- Stdlib only in both the CLI and the tests. No third-party deps.
- The CLI writes only to the central operator-intelligence store and (via `ingest-review`) a project's `.planning/`. Never have it modify a target repo's source.
- Source-integrity guard: no duplicate module-level constant/def names. The suite enforces it; do not silence it.

## Verify

- `python3 scripts/operating-layer.py --help`
- `python3 scripts/tests/operating_layer_test.py` → `137/137 checks passed`

## Design

See `references/pathway-operating-layer.md`.

Per-pathway proof gates (concrete engineering acceptance criteria a critic can fail you on):
`references/system-design-proof-gates.md`. It also flags where `llm-agent-eval` proof must come
from elsewhere (agent-output quality is not covered by system-design theory).
