# Agent Bash approval issuance guard

work_id: W-20260817-pathway-operating-layer-block-agent-driven-bash--2064b8
status: implemented; live proof pending
owner: Alex

## Goal

Agents must not issue Pathway approval tickets through Bash.

The guard covers Claude, Codex, GLM, and Kimi agent shells.
Alex can still issue a ticket in a normal Terminal.
Approval ticket rules and command shapes stay unchanged.

This guard is a forcing function and audit aid.
It is not proof of a human identity.

## Fixed decisions

- The tracked source is `hooks/approval-issue-guard.py`.
- The hook uses only Python's standard library.
- It does not import the Pathway engine.
- It does not read or write any approval ledger.
- It does not start another process.
- It has no override switch.
- It ignores `CLAUDE_HOOK_FORCE` and approval environment flags.
- Bad hook input fails open, matching current hook policy.
- A matched issuance command fails closed with exit code `2`.
- The denial tells Alex to use a normal Terminal.
- Safe commands return `0` without output.

No public Pathway command changes in this work.

## Hook input and output

The hook reads one PreToolUse JSON object from standard input.

It accepts either Bash command field:

- `tool_input.command`
- `tool_input.cmd`

Missing fields, unrelated tools, and invalid JSON return `0`.
The hook first makes a cheap approval candidate check.
It exits early when no approval command can exist.

The parser then joins shell quotes and checks command positions.
It exits when no final token equals `approval-issue`.
It must not block a safe text mention.

## Commands that must be blocked

The executable name must resolve to `operating-layer.py`.
The argument list must contain the exact `approval-issue` token.

The parser blocks these direct forms:

- `operating-layer.py` found through `PATH`.
- Relative and absolute script paths.
- The installed symlink and the repository script.
- Direct executable calls.
- Calls through `python` or `python3`.
- Python flags before the script, including `-B`.
- Leading environment assignments.
- `env` and `command` wrappers.
- Pass-through `exec`, `time`, `nohup`, and `nice` wrappers.
- Shell groups, conditions, and negation prefixes.
- Pathway options placed before the subcommand.
- `bash -c` and `bash -lc` nested commands.
- Equivalent `sh` and `zsh` nested commands.
- Commands joined by semicolons or newlines.
- Commands joined by `&&` or `||`.
- Quoted parts that join into `approval-issue`.
- Literal ANSI-C quotes, locale quotes, and line continuations.
- Release production approval tickets.
- Production-secure waiver tickets.

A broken shell parse gets one narrow fallback check.
That check only blocks runner-first command text.

## Commands that must stay allowed

- Every other operating-layer subcommand.
- `operating-layer.py --help`.
- The full Pathway test command.
- `rg` and `git grep` searches.
- `printf` text and documentation examples.
- Plain and quoted here-doc example bodies.
- Git commit text and diff output.
- Read-only approval ledger commands.
- Missing or unrelated PreToolUse data.
- Invalid JSON input.

## Runtime wiring

One tracked file serves every runtime.
`install.sh` creates both installed links.

| Runtime | Settings file | Installed hook |
|---|---|---|
| Claude | `~/.claude/settings.json` | `~/.claude/hooks/approval-issue-guard.py` |
| Codex | `~/.codex/hooks.json` | `~/.codex/hooks/approval-issue-guard.py` |
| GLM and Kimi | `~/.claude/glm-routing/claude-config/settings.json` | `~/.claude/hooks/approval-issue-guard.py` |

Each settings file adds one PreToolUse Bash hook.
Existing hook entries keep their current order.
The Codex hook is appended to its Bash list.
This keeps existing Codex trust indexes stable.

The build must not edit Codex trust hashes.
Alex trusts the new Codex hook through `/hooks`.

GLM and Kimi share the isolated Claude settings file.
That file contains only the needed Bash hook settings.

## Security boundary

The hook blocks clear agent Bash issuance attempts.
It does not create a cryptographic identity boundary.

These bypasses remain outside this work:

- Encoded or encrypted command text.
- A copied or renamed operating-layer script.
- Direct imports that call engine functions.
- Commands built after the hook runs.
- Other process tools that do not use Bash hooks.
- A hostile user who edits or removes hook settings.

The manual exception is not an agent override.
Alex reviews the full command first.
Alex then types that command in Terminal or iTerm.

## Test-first build

Tests land before the hook source.
The first focused run must fail for missing behavior.
The smallest guard then makes those tests pass.
Refactoring starts only after a green focused run.

The test set covers every blocked and allowed case above.
It also checks both Bash input field names.
Every denial must mention Alex's normal Terminal path.
Every allowed case must be silent.

Installer tests use temporary home folders.
They check both links resolve to the tracked source.
They must not alter live home settings.

Settings tests check these facts:

- All three files contain valid JSON.
- Each Bash matcher contains one exact guard entry.
- The Codex guard stays last in its Bash list.
- Existing settings remain byte-for-byte unchanged elsewhere.

The full suite must exceed the `799/799` baseline.
The local hook must stay below 50ms at p95.

The completion verifier records the live approvals ledger before running.
It records its SHA-256 and line count afterward.
Both values must stay unchanged.
No test may issue a real approval ticket.

## Live proof

Live probes wait until Alex trusts the Codex hook.
Each probe starts in a fresh agent session.

The blocked probe is harmless:

```bash
operating-layer.py approval-issue --help
```

The allowed probe is also harmless:

```bash
operating-layer.py pathway-next --help
```

The GLM probe runs under its normal `bypassPermissions` mode.
That probe also proves Kimi's shared settings path.

## Rollback

Remove the guard entry from all three settings files.
Remove both installed links.
Keep the tracked source and test history.

Rollback does not change approval records.
It also does not change ticket rules.

## Completion checks

- The focused guard tests pass.
- The full Pathway suite passes.
- All settings JSON parses.
- Both links resolve to one tracked source.
- All fresh-session probes match this contract.
- The live approval ledger is unchanged.
- The proof guide states this boundary.
- The shipped waiver authority spec stays unchanged.

## Carry-forward

summary: One tracked hook blocks known direct agent Bash approval issuance forms.

what_changed:

- Claude, Codex, GLM, and Kimi now share one guard source.
- The installer owns both live symlinks.
- The suite covers direct calls, wrappers, chains, nested shells, and safe text.

more_relevant:

- Fresh-session hook loading and Codex trust now decide live readiness.
- The approvals ledger hash remains the safety check for every probe.

less_relevant:

- Ticket digest, expiry, replay, and consumption rules did not change.
- The closed transfern outcome does not need new work.

next_pathway_must_use:

- Quality must keep the full suite and ledger-invariance proof together.
- Field must use fresh Claude, Codex, GLM, and Kimi sessions.

do_not_do_yet:

- Do not run a real approval issue command.
- Do not trust the Codex hook for Alex.
- Do not dispatch external critics before Alex approves their exact inputs.

open_decisions:

- Alex must trust the new Codex hook entry.
- Alex must authorize the Codex and GLM critic passes.

active_risk_overlays:

- `llm-agent-eval`
- `human-gate`
