# pathway-operating-layer: workspace context

## Purpose and boundary

This system-map organizes the work named in [the project map](CLAUDE.md).
It connects the existing rooms below; source and tooling paths stay where they are.

- [Working research and design notes](docs/CONTEXT.md)
- [Stable design docs and proof gates](references/CONTEXT.md)
- [The CLI and its own tests](scripts/CONTEXT.md)
- [Top-level integrity tests](tests/CONTEXT.md)
- [Present state, feature artifacts and handoffs](.planning/CONTEXT.md)

## Start or resume work

Read the project map, then the contract for the task. Check its Inputs before writing.
Use its Process, output path and Human check; stop if a required input is absent.
Resume the existing named task or record rather than starting a duplicate.

## Stable rules and changing work

The map and room contracts define routing and review rules. Working artifacts stay
in each room’s Outputs locations. Preserve existing source, records and tooling paths.
New filing does not authorize moves, publication or changes to approved decisions.

## Status and first check

Read [.planning/STATE.md](.planning/STATE.md), then compare its claims with current files and tests.
A file existing is not approval or proof of current operation.

From this checkout, run `python3 ~/.claude/scripts/icm-check.py "$PWD"`.
Use this worktree’s project path when checking a client branch.
Record the command and result in the task receipt; keep failed work open.
