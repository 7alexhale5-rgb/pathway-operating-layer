# Approval issuance guard verification

work_id: W-20260817-pathway-operating-layer-block-agent-driven-bash--2064b8
verified: 2026-08-17
status: build proof passed; human trust and live sessions pending

## Result

The tracked guard is built and installed.
It covers Claude, Codex, GLM, and Kimi settings.
Known direct Bash issuance forms return exit code `2`.
Safe commands return `0` without output.

The build does not change approval ticket rules.
No live approval was issued during this work.

## Test-first record

The first guard run had 59 expected failures.
It had 844 passing checks before the source existed.

The verifier test also failed first.
It had 12 expected failures and two passes.
The verifier file did not exist yet.

Deep review found more direct shell forms.
Each fix began with a focused failing run.

| Focus | Before fix | After fix |
|---|---:|---:|
| Wrapper, quote, and help review | 52 failures, 168 passes | green |
| Option abbreviation and line joins | 6 failures, 175 passes | green |
| Control flow, `env -P`, and here-docs | 22 failures, 243 passes | green |
| Final focused guard and verifier set | n/a | 283 passes |

The final full suite passed `1088/1088` checks.
The old baseline was `799/799` checks.

## Repeatable proof

Run this command from the repository root:

```bash
python3 scripts/verify-approval-issue-guard.py --runs 120
```

Latest result:

| Check | Result |
|---|---|
| Settings files | 3 passed |
| Installed links | 2 passed |
| Blocked fixtures | 15 passed |
| Allowed fixtures | 12 passed |
| Hook p95 | 17.303ms |
| Maximum p95 | 50ms |
| Ledger lines | 4 |
| Ledger SHA-256 | `31f4b8cd3432e711746faa0a4065bd6ebfac1f108d55c4ea2c2649e7d7ec7dd7` |
| Ledger changed | no |

The verifier runs only synthetic hook input.
It never invokes the approval CLI.
It tests source and both installed links.
It refuses a slow hook or ledger mutation.

## Runtime wiring

| Surface | Result | Pending step |
|---|---|---|
| Claude | linked and registered | fresh-session probe |
| Codex | linked and appended last | Alex trusts it through `/hooks` |
| GLM | shared settings registered | fresh `bypassPermissions` probe |
| Kimi | shared settings registered | fresh shared-settings probe |

No Codex trust hash was written.
Existing Codex hook indexes kept their order.
Every settings file remains valid JSON.

## Review record

Three independent review passes checked this change.
They covered security, code, tests, speed, and plan fit.

Valid findings became regression tests.
Fixes cover wrapper nesting, options, shell joins, and safe text.
The final security pass ran 39 probes.
All 39 probes passed.

The implementation guard reported a clean change radius.
The security guard found old fake key fixtures.
Git history proves those fixtures predate this work.
The quality guard noted old project-wide policy gaps.
Those gaps do not come from this change.

This is a Python command guard, not a web app.
Browser audit tools do not apply.

## Honest boundary

This guard is a strong forcing function.
It is not human identity proof.

Encoded commands remain outside scope.
Renamed script copies remain outside scope.
Direct engine imports remain outside scope.
Other process tools may not use Bash hooks.

Alex keeps the manual Terminal path.
Agents receive no override flag.

## Pending human proof

Alex must trust the new Codex hook.
Fresh sessions must then run two harmless probes.

Blocked probe:

```bash
operating-layer.py approval-issue --help
```

Allowed probe:

```bash
operating-layer.py pathway-next --help
```

Codex and GLM critics also need Alex's approval.
The Pathway work item stays open until those checks finish.

## Rollback

Remove the three settings entries.
Remove the two installed links.
Keep the tracked source for recovery.
Do not change the approvals ledger.
