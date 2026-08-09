---
name: pathway
description: Ask a project what engineering pathway to run next, track the work against one shared ID, or start a measured multi-project pathway pilot. Wraps operating-layer pathway-next + the work envelope so you never type the CLI. Loop mode runs the whole determine → execute → prove → advance cycle continuously, with autonomy earned by the proof metric.
argument-hint: "<project> [ go | done | <goal> ] [--max] | pilot <projects> <goal>   —   usually just the project; add --max for the full hypercritical chain; I hand you the exact next command to paste"
---

# Pathway — next-best move for a project

The single front door to the operating-layer pathway router and its work envelope.
The user will never remember the CLI flags — you run them. Always keep output in
plain English (names of real things, no jargon, no status icons).

Script: `python3 ~/.claude/scripts/operating-layer.py`

## Parse `$ARGUMENTS`

- If the first token is `pilot` or `pathway-pilot` → **PILOT**.
- Canonical pathway catalog: `govern, research, data, security, design, implementation, quality, field, observability, techdebt, release, docs`.
- **First token = project** — a name resolvable under `~/Projects` (e.g. `consult-ops`,
  `koho`) or an absolute path.
- **Strip modifiers FIRST.** Pull any `--`-prefixed token out of the argument string and hold it
  aside BEFORE classifying the verb below. A modifier is never part of the intent text. Skipping
  this step is what turns `/pathway koho go --max` into a START that mints a work item whose goal
  is literally "go --max". Recognised modifiers: `--max` (see below), `--auto=<tier>` (LOOP only).
  An unrecognised `--flag` is an error: say so in one line and stop; never fall it through to START.
- **Remaining text = intent** (optional). Classify by **first-match-wins precedence**:
  - empty → **ASK** (just recommend, read-only).
  - exactly `go` / `run` / `execute` / `proceed` (one reserved verb, nothing after it once
    modifiers are stripped) →
    **EXECUTE** — run the currently-recommended pathway's full execution profile once, with the
    authority of the user pasting it now, then prove + log + hand back the next command. This is
    the keystone verb: almost every hand-off block tells the user to paste `/pathway <project> go`.
  - `done` / `close` / `finish` / `wrap` → **CLOSE**.
  - a pathway name (`govern research data security design implementation quality field
observability techdebt release docs`) followed by a file path, or "logged/finished `<pathway>`, proof
    `<path>`" → **LOG**.
  - `loop` (optionally `--auto=recommend|safe|build`) → **LOOP** (run EXECUTE continuously, one
    shared work ID, autonomy earned by the proof metric).
  - `pilot` / `pathway-pilot` → **PILOT** (measured real-project agentic dev-team rehearsal).
  - anything else — a goal sentence (≥2 words, not matched above) → **START** (open tracked work
    with that goal).

If the project token is missing, ask which project — nothing else.

## `--max` — the whole chain, hardest setting

One flag for "do this at the hardest setting." `--max` is a **rigor modifier only**. It never
changes which verb runs, never starts work on its own, and never grants authority. Strip it, run
the verb the remaining text selects, and raise rigor while doing it.

| You type                          | Verb that runs (unchanged by the flag) | What `--max` adds        |
| --------------------------------- | -------------------------------------- | ------------------------ |
| `/pathway <project> --max`        | ASK (read-only, same as bare)          | Effects 1 + 2 below      |
| `/pathway <project> go --max`     | one EXECUTE turn                       | Effects 1 + 2 below      |
| `/pathway <project> loop --max`   | LOOP                                   | Effects 1 + 2 below      |
| `/pathway <project> <goal> --max` | START                                  | tier `production-secure` |

**Effect 1 — arm every pathway the default tier drops.** The default tier is `live`, which does
**not** seed `security`, `research`, or `techdebt`. `--max` makes the coverage gate refuse to close
without them. How depends on whether the outcome exists yet:

- **New outcome (START):** pass `--tier production-secure` to `work-start`. Verified 2026-08-09
  against `compute_itinerary` / `merge_itinerary`: a `live` itinerary holding three proved pathways
  upgraded to `production-secure` keeps all three proofs and their run IDs and gains exactly
  `research`, `security`, `techdebt`.
- **Existing outcome:** add the missing pathways **by work ID**, one call each —
  `work-cover --work-id <id> --pathway <security|research|techdebt> --add`. Read `<id>` from
  `pathway-next --json`.
  **Never re-run `work-start` to retier an existing outcome.** `stable_work_id` hashes the current
  **day** alongside project and goal (`operating-layer.py:1231-1236`), so the identical goal
  produces a different ID on a different date and silently opens a SECOND outcome, orphaning every
  proof on the first. Verified 2026-08-09: the same project and goal hashed to
  `W-20260717-…-e7eb9c` on its creation date and `W-20260809-…-1fea88` today.

**Effect 2 — escalate the critic set, subject to the send rail.** The execution stacks name a Codex
critic only. Under `--max`, run the `karpathy verify` dual cascade: Codex **and**
`~/.claude/glm-routing/glm-review` on the same diff with the same brief, Opus adjudicating the
union on the real artifact. If a family is unavailable (not installed, rate-limited, or
guard-blocked on a client repo), run the other AND substitute an objective Fable critic
(`Agent(subagent_type="reviewer", model="fable")`) with an adversarial brief, then **say the
model-family gap out loud** — a Fable critic adjudicated by Opus is one family, not two. Never
silently drop a pass. Briefs must require DRY, KISS, YAGNI, SOLID, SINE, plus correctness, edge
cases, and security.
**This is an external send.** A second-family critic ships the diff to a hosted service, so it
obeys the same rail as everything else in LOOP: pause and ask before the first send of a session,
and never send from a guard-blocked client repo. `--max` does not pre-authorise it.

**Effect 3 — nothing else changes, including stickiness.** `--max` is **not persisted**: nothing in
the work item or `pathway-next` records that an outcome is running at max, and `production-secure`
cannot stand in for it because ordinary outcomes reach that tier too. So repeat the flag in the
hand-off block while a session is running at max, and know it is a within-session convention, not
an enforced one — a fresh session cannot recover it. The irreversible rails hold unchanged:
`/ship`, `work-close`, prod-flag flips, external sends, and force-push never auto-fire, with or
without this flag.

**Grammar.** Only a `--`-prefixed token **outside** the goal text counts as a modifier; a `--max`
appearing inside a quoted goal is goal text, not a flag. Repeating `--max` is idempotent. `--max`
composes with `--auto=` on LOOP. PILOT ignores it.

## The hand-off block — MANDATORY on every output

Every `/pathway` response — ASK, START, EXECUTE, LOG, CLOSE, and every LOOP turn — **ends with
exactly one fenced code block holding the single command the user pastes next.** Nothing comes
after it. This is the whole point of the skill: the user copies the next move, they never compose
it from memory. One block, one command, one paste — never a menu. If you would offer a choice,
pick the safest default, put only that in the block, and name the alternative in prose above it.

**Carry `--max` into the block, within the session.** If this session is running at max rigor,
every hand-off block must repeat the flag (`/pathway <project> go --max`); dropping it silently
downgrades the next turn's critic set. This is a convention, not a guarantee: max is not persisted
anywhere, so a fresh session cannot know, and the user must retype the flag to resume at max.

Shape (always this):

> ▶ **Next — copy-paste this:**
>
> ```
> /pathway <project> <verb>
> ```
>
> _(one plain-English line: what pasting it will do)_

What goes in the block, by situation:

| Situation                                          | Block holds                                                                           | One-liner says                                                                                                 |
| -------------------------------------------------- | ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Recommendation ready · work tracked · trust = pass | `/pathway <project> go`                                                               | "runs <pathway> end-to-end with full power, proves it on <real_artifact>, logs it, hands you the next command" |
| Project not tracked yet (`work_id` null)           | `/pathway <project> <your one-line goal>`                                             | "names the outcome and starts tracking — the one time you type a goal; I take it from there"                   |
| Trust = fail                                       | `/pathway <project> go`                                                               | "fixes trust first (that IS the next move), then resumes the recommended pathway"                              |
| Pilot cohort created                               | `/pathway <highest-risk-project> go`                                                  | "runs the first assigned pathway from the measured pilot cohort"                                               |
| Just finished + logged a pathway                   | `/pathway <project> go` — or `/pathway <project> done` if the outcome's gates cleared | "starts the next pathway" / "closes the outcome"                                                               |
| Closeout blocked                                   | the one fix command                                                                   | "clears <the one blocker> so the outcome can close"                                                            |

## ASK — "what should I do next?"

1. Run: `python3 ~/.claude/scripts/operating-layer.py pathway-next --project <project> [--work-id <selected-work-id>] --json`. Omit `--work-id` only when no outcome has been selected yet; once the JSON returns a work ID, pin every later determine call for that outcome to it.
2. From the JSON, tell the user, in plain English:
   - **Coverage first** (when `work_id` exists) — `itinerary_coverage`: "Pathway 3 of 7 proved ·
     remaining: security, observability, docs." This is the spine; the recommendation is the next step on it.
   - **The next move** — `recommended_pathway` + the `karpathy_card.one_percent_move`.
   - **Why** — the top ranked reason.
   - **What "done" looks like** — `karpathy_card.verifier_good` and the real artifact that proves it (`karpathy_card.real_artifact`).
   - **The skill to run** — `karpathy_card.skill`.
   - **Where the evidence came from** — `signal_sources` (operating-layer vs project-local). If both are 0, say plainly that the project isn't tracked yet and one good move is to start it.
3. End with the **hand-off block** (above) — `/pathway <project> go` when work is tracked, or
   `/pathway <project> <your goal>` when `work_id` is null. That single line is the user's whole
   next action; do not also list the LOG/CLOSE syntax — `go` and the next hand-off block carry it.
4. Do not modify anything in ASK mode. Open the HTML report only if the user asks to see it.

## EXECUTE — `go` (do the recommended thing now, full authority, no deviation)

The user pasted `/pathway <project> go`. Their paste **is** the authority for this one step — they
are present and explicitly triggering it — so run the recommended pathway now. Do not
re-recommend, do not present a menu.

1. **Determine** — `pathway-next --project <project> [--work-id <selected-work-id>] --json`. On a fresh invocation, the first result selects the work ID; pin every later determine call in this outcome to it. Read `recommended_pathway`,
   `karpathy_card` (skill / execution_stack / execution_tools / one_percent_move / verifier_good /
   real_artifact), `pathway_trust`, `confidence`, `work_id`. `go` re-derives the recommendation
   here, so it round-trips deterministically from a fresh session — no in-session state needed.
   If `work_id` is null, there is nothing to execute yet → emit the START hand-off block and stop.
2. **Trust gate** — if `pathway_trust.status` = `fail`, the real next move is "fix trust." Do that,
   not the recommended pathway, then re-determine.
3. **Honor the locked plan — no deviation.** If an approved plan/spec for this pathway already
   exists on disk (e.g. a `.planning/*SPEC*.md` for this work), resume at implementation; do NOT
   re-plan. Re-planning already-approved work is the deviation this verb forbids.
4. **Execute the profile** — walk the card's `execution_stack` (primary skill → supporting skills →
   second-model critic) with its `execution_tools`, via the Skill tool. Runs inside the usual hooks
   (`validate-before-stop` blocks a fake "done"), so proof can't be faked.
5. **Irreversible rails still hold** — `/ship`, `work-close`, prod-flag flips, external sends, and
   force-push NEVER auto-fire under `go`. Pause and ask for those, then continue.
6. **Prove + log** — when the work is genuinely done, LOG the real artifact against `work_id` (LOG
   mechanics below). No artifact, no log, no advance.
7. **Advance + report coverage** — recompute `pathway-metric`, re-run Determine, emit the next
   hand-off block. Lead the turn with coverage from the JSON's `itinerary_coverage`: "Pathway 3 of 7
   proved · remaining: security, observability, docs." When `open` is empty, the next move is
   `/pathway <project> done` (the outcome can now close — full coverage reached).

## START — "begin tracking this goal"

1. Resolve the absolute project path (under `~/Projects` or the path given).
2. **Pick the "done" tier** — how finished this outcome must be. The tier sizes the **itinerary**:
   the set of engineering pathways that MUST be covered before the outcome can close.
   - **demoable** — runs end-to-end, you can show it (govern · implementation · quality).
   - **live** — real users touch it (+ data · observability · release · docs). _Default._
   - **production-secure** — untrusted actors, compliance (+ research · security · techdebt).
     The goal's own words also auto-pull `design` (UI), `research`, or `data`. If the user didn't say,
     infer from the goal and state your pick in one line — don't interrogate.
3. Run: `python3 ~/.claude/scripts/operating-layer.py work-start --project <abs-path> --goal "<goal>" --tier <tier>`
4. Immediately run ASK with the `work-start` result's `--work-id` pinned. Show the **seeded itinerary** in plain English — "this outcome
   needs N pathways: govern, data, … — I walk them in order, and it can't close until each is proved
   on a real artifact or explicitly marked not-applicable with a reason."
5. Tell the user the work ID once; every pathway logs against it. End with the hand-off block.

## LOG — "I finished a pathway, here's the proof"

1. Get the active work ID: `python3 ~/.claude/scripts/operating-layer.py pathway-next --project <project> [--work-id <selected-work-id>] --json` → read `work_id`. Once known, keep passing it so a newer sibling outcome cannot replace it.
   - If there is no active work item, switch to START first (ask for the goal if none was given).
2. Proof needs BOTH — a **real file that exists** AND an executable verifier passed through
   `--verify-cmd`. `--verified-by` is attestation only; it never proves a pathway by itself.
   Never invent either — if the user didn't give an artifact or verifier, ask for it.
3. Run:
   ```bash
   python3 ~/.claude/scripts/operating-layer.py work-log \
     --work-id <work_id> --pathway <pathway> --kind verify \
     --gate <pathway>-gate --evidence <abs-evidence-path> --result pass \
     --proof-type artifact --verify-cmd "<command that re-checks the artifact>"
   ```
4. Re-run ASK so the user sees the new next-best pathway after this one closed out.

## CLOSE — "done with this outcome"

1. Get the active `work_id` (as in LOG).
2. Run: `python3 ~/.claude/scripts/operating-layer.py work-close --work-id <work_id> --json`
3. If `closed` is true → confirm in one line.
   If `closed` is false → read the status summary and tell the user, in plain English, exactly
   what's blocking closeout and the one thing to fix. Get it: `... work-status --work-id <work_id> --json`.
   **The coverage gate is usually the blocker:** `itinerary_coverage.open` lists pathways still owed
   proof. For each, either run it (`/pathway <project> go`) or, if it genuinely doesn't apply, mark it:
   `... work-cover --work-id <work_id> --pathway <name> --na --reason "<why it doesn't apply>"`.
   Nothing closes until every itinerary pathway is proved-with-artifact or N/A-with-reason — that is
   the guarantee that no necessary pathway was skipped.

## LOOP — "keep making the next-best move until this outcome is done"

The all-inclusive mode: the Karpathy method run continuously. One project, one shared work ID.
The user supplies the goal and the go-ahead; the loop does determine → execute → prove → advance,
turn after turn, until the outcome closes. ASK/START/LOG/CLOSE become the loop's internal states —
the user stops typing verbs.

On EXECUTE the loop runs the **culmination of the stack** for the chosen pathway — its full
`execution_stack` + `execution_tools` profile (the 11 core pathways plus `field` carry one, baked into the engine),
Karpathy-wrapped — not a single command.

**Autonomy is earned by the proof metric — never assumed.** Read `suggested_autonomy_tier` +
`autonomy_rationale` from `pathway-next` and apply it; never re-derive the rule (staleness
fail-closes to Tier 1 in code, so the field is always current).

- **Tier 1 · Recommend** (default; returned whenever `proved_rate < 0.50` OR trust ≠ `pass` OR
  confidence ≠ `high`) — stage the exact `card.skill` command, then STOP for the user's go.
- **Tier 2 · Execute-safe** (only when all three pass, fresh this turn) — auto-run only the local,
  reversible pathways `research, govern, data, security, quality, observability, docs`. Pause
  mid-pathway the instant a step would touch a real DB / prod surface, send code/data to an external
  service, or commit / deploy — those need an explicit grant.
- **Tier 3 · Execute-build** — only on an explicit per-session grant; also auto-runs `implementation,
techdebt, design`.

**Never auto, any tier:** `/ship`, `work-close`, prod-flag flips, external sends — pause and ask.
(The `docs` pathway is Tier-2 safe: its skill is `doc-coauthoring`, which authors without committing.)

**One iteration:**

1. **Determine** — `pathway-next --project <project> [--work-id <selected-work-id>] --json`. Omit the ID only on the first selection; pin the returned ID for the rest of the loop. Read `recommended_pathway`, the
   `karpathy_card` (decision / verifier_good / real_artifact / skill + `execution_stack` +
   `execution_tools` — the full best-execution profile), `confidence`, `suggested_autonomy_tier`
   (+ `autonomy_rationale`), and `work_id`. The engine already gated the tier — apply it, don't
   recompute. If `work_id` is null, run START first (ask for the goal if none was given).
2. **Trust gate** — read the trust status in the JSON. If `fail`, the move becomes "fix trust,"
   not the recommended pathway — surface that and stop.
3. **Execute** — run the pathway's **best-execution profile**, not just one skill: walk the card's
   `execution_stack` (primary skill → supporting skills → second-model critic) and pull in its
   `execution_tools` (the env / plugins / MCP / subagents for that pathway — e.g. Figma + pencil for
   design, supabase + context7 for data, firecrawl + perplexity for research). That is the Karpathy
   `verify` discipline applied every turn. By tier: stage the profile for the user's go (Tier 1), or
   run it via the Skill tool (Tier 2/3 when eligible). It runs inside the usual hooks —
   `validate-before-stop` blocks a fake "done," so the proof can't be faked.
4. **Prove** — when the work is really done, LOG the **real artifact** against the shared `work_id`.
   No artifact, no advance.
5. **Advance + measure** — recompute `pathway-metric` (so it is never stale), then re-run Determine.
   Report the turn in plain English: pick · why · what ran · proof · new proof rate.
6. **Loop or close** — repeat. CLOSE when the work item's gates clear.

**Stop the loop when:** the work item closes · trust fails and can't self-heal · the next pathway is
human-gated and the user isn't present to confirm · no pathway gains rank for 3 turns (anti-thrash) ·
a token budget is hit. If running unattended, self-pace with `ScheduleWakeup`; otherwise drive it
turn-by-turn with the user. Always name the current tier in the first line of each turn.

## PILOT — "test the full agentic dev-team loop on real projects"

Use this before broadening autonomy across projects. It is a measured rehearsal, not a build pass.

1. Parse projects as a comma-separated list after `pilot` / `pathway-pilot`.
2. Use the remaining text as the pilot goal. If the goal is missing, ask for the goal; do not invent one.
3. Run:
   ```bash
   python3 ~/.claude/scripts/operating-layer.py pathway-pilot \
     --projects <project-a,project-b> \
     --goal "<pilot goal>" \
     --json
   ```
4. Report the cohort ID, baseline metric, pilot report path, and each assignment's project,
   recommended pathway, lead role, critic role, proof gate, review gate, active overlays,
   and next command.
5. The command may open missing work envelopes, write pilot ledgers/reports, and snapshot metrics.
   It must not mutate project repos, deploy, send, close work, or mark proof/N/A.
6. End with one hand-off block for the safest first execution target, usually the highest-risk
   assignment's `/pathway <project> go`.

## Rules

- One shared work ID per outcome — every pathway logs against it. Never start a second ID for the same goal.
- **Coverage is the spine.** START seeds an itinerary (sized by the "done" tier); the router walks it
  foundation-first; the outcome **cannot close** until every itinerary pathway is proved-with-artifact
  or marked `na` with a reason (`work-cover`). This is enforced in the engine, not by memory — a pathway
  is never silently skipped or lost between turns. Re-running START never clobbers earned proof.
- Evidence is always a real artifact on disk. No artifact, no `--result pass`.
  What counts as proof is defined once, in ~/.claude/references/proof-standard.md —
  artifact + executed check + result read back. Don't restate it here.
- Never modify the target project's repo files; this tool only writes to the central operator-intelligence store.
- Plain English in chat; the CLI mechanics stay under the hood.
- The router is read-only advice. START / LOG / CLOSE are the only state changes, and only on explicit intent.
- LOOP autonomy is earned by the proof metric: default to Tier 1 (recommend) and stay there unless
  `pathway-next` returns `suggested_autonomy_tier == "execute-safe"`. The engine computes that field
  (proof rate ≥ 0.50 + trust pass + high confidence, fresh each turn); never re-derive it by hand.
- LOOP never auto-runs `/ship`, `work-close`, prod-flag flips, or external sends at any tier — pause and ask.
- One project per loop, one shared work ID. Recompute `pathway-metric` every turn so it is never stale.
- For real-work trials across projects, run `pathway-pilot --projects <a,b> --goal "<pilot goal>"`
  first. It assigns the pathway lead/critic/proof gate, records Alex's review gate, snapshots
  `pathway-metric`, and writes the measured pilot cohort without mutating project repos.
