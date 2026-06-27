---
name: pathway
description: Ask a project what engineering pathway to run next, and track the work against one shared ID. Wraps operating-layer pathway-next + the work envelope so you never type the CLI.
argument-hint: "<project> [goal | \"done\" | <pathway> <evidence-file>]"
---

# Pathway — next-best move for a project

The single front door to the operating-layer pathway router and its work envelope.
The user will never remember the CLI flags — you run them. Always keep output in
plain English (names of real things, no jargon, no status icons).

Script: `python3 ~/.claude/scripts/operating-layer.py`

## Parse `$ARGUMENTS`

- **First token = project** — a name resolvable under `~/Projects` (e.g. `consult-ops`,
  `koho`) or an absolute path.
- **Remaining text = intent** (optional). Classify it:
  - empty → **ASK** (just recommend, read-only).
  - looks like a goal sentence → **START** (open tracked work with that goal).
  - `done` / `close` / `finish` / `wrap` → **CLOSE**.
  - starts with a pathway name (`research govern data security release implementation
    quality observability techdebt design docs`) followed by a file path, or says
    "logged/finished `<pathway>`, proof `<path>`" → **LOG**.

If the project token is missing, ask which project — nothing else.

## ASK — "what should I do next?"

1. Run: `python3 ~/.claude/scripts/operating-layer.py pathway-next --project <project> --json`
2. From the JSON, tell the user, in plain English:
   - **The next move** — `recommended_pathway` + the `karpathy_card.one_percent_move` (lead with this).
   - **Why** — the top ranked reason.
   - **What "done" looks like** — `karpathy_card.verifier_good` and the real artifact that proves it (`karpathy_card.real_artifact`).
   - **The skill to run** — `karpathy_card.skill`.
   - **Where the evidence came from** — `signal_sources` (operating-layer vs project-local). If both are 0, say plainly that the project isn't tracked yet and one good move is to start it.
3. If `work_id` is null, end with one line: *to track this, run `/pathway <project> <your goal>`*.
   If `work_id` exists, end with one line: *when you finish, run `/pathway <project> <pathway> <file>` to log it, or `/pathway <project> done` to close.*
4. Do not modify anything in ASK mode. Open the HTML report only if the user asks to see it.

## START — "begin tracking this goal"

1. Resolve the absolute project path (under `~/Projects` or the path given).
2. Run: `python3 ~/.claude/scripts/operating-layer.py work-start --project <abs-path> --goal "<goal>"`
3. Then immediately run ASK (pathway-next) so the recommendation shows the new shared work ID and the next move.
4. Tell the user the work ID once, in plain English, and that every pathway from here logs against it.

## LOG — "I finished a pathway, here's the proof"

1. Get the active work ID: `python3 ~/.claude/scripts/operating-layer.py pathway-next --project <project> --json` → read `work_id`.
   - If there is no active work item, switch to START first (ask for the goal if none was given).
2. The evidence must be a **real file that exists** (a deployed asset, test file, migration,
   served HTML, report). If the user didn't give one, ask for it — never invent evidence.
3. Run:
   ```bash
   python3 ~/.claude/scripts/operating-layer.py work-log \
     --work-id <work_id> --pathway <pathway> --kind verify \
     --gate <pathway>-gate --evidence <abs-evidence-path> --result pass
   ```
4. Re-run ASK so the user sees the new next-best pathway after this one closed out.

## CLOSE — "done with this outcome"

1. Get the active `work_id` (as in LOG).
2. Run: `python3 ~/.claude/scripts/operating-layer.py work-close --work-id <work_id> --json`
3. If `closed` is true → confirm in one line.
   If `closed` is false → read the status summary and tell the user, in plain English, exactly
   what's blocking closeout (open controls, missing evidence, stale measurements) and the one
   thing to fix. Get it: `python3 ~/.claude/scripts/operating-layer.py work-status --work-id <work_id> --json`.

## Rules

- One shared work ID per outcome — every pathway logs against it. Never start a second ID for the same goal.
- Evidence is always a real artifact on disk. No artifact, no `--result pass`.
- Never modify the target project's repo files; this tool only writes to the central operator-intelligence store.
- Plain English in chat; the CLI mechanics stay under the hood.
- The router is read-only advice. START / LOG / CLOSE are the only state changes, and only on explicit intent.
