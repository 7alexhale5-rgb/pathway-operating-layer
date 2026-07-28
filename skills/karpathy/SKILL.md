---
name: karpathy
description: Apply Andrej Karpathy's three-layer agentic method — Spec → Verify → Environment. Use when starting non-trivial work to pin the goal before building, design verification up front, and keep the workspace aligned. Modes — spec | verify | audit. The one rule: outsource the typing, not the understanding.
---

# The Karpathy Method

Three layers from Karpathy's agentic-engineering talk, made into a working discipline. Parse the
argument as `spec | verify | audit`. If none is given, run them in order for a fresh build
(spec → build → verify), with `audit` as a periodic tune-up.

> **The one thing:** you can outsource your thinking, but not your understanding. Every layer
> centres on the goal only the human can supply. Don't let the machinery hide the goal.

---

## Layer 1 — `spec` (deliver your understanding)

Uncover the **goal** — the decision the work drives, not the task statement — then scope small and
verify the key decisions before any code.

1. **Goal before task.** If the ask is non-trivial or ambiguous, interview the human to pin the
   decision this work drives. Start from the goal, never from the task statement.
2. **Smallest scope that ships one thing end-to-end** against a *falsifiable* acceptance gate — a
   number or a checkable condition, not "it works." Write the gate down before building.
3. **The Karpathy ladder:** each phase ships one runnable thing against one measured number; no
   phase collapses into another; build the throwaway v1 first (its failure modes shape v2); stop at
   the threshold — don't over-fit past the gate.
4. **Name the forks.** When there are two valid interpretations, surface them and let the human
   decide; don't pick silently. Keep the diff surgical — every line traces to the goal.

Output a short spec (goal · acceptance gate · the one fork). Do **not** build yet.

## Layer 2 — `verify` (the only real lever)

Verification is what makes agentic output trustworthy. Most failures are verification failures.

1. **Criteria up front.** State precisely what "good" looks like as checkable conditions *before*
   building — captured as a test or a golden set, not discovered after.
2. **Independent second-model critic.** Run the diff past a *different* model family with the same
   brief. Two independent critics catch a bug one misses; where they agree, confidence is high.
   The author adjudicates the union of findings on the real artifact — fix the confirmed ones
   test-first, dismiss false positives with a one-line reason, and never silently drop a critic.
   The brief must require DRY, KISS, YAGNI, SOLID, and strict-necessity checks plus correctness,
   edge cases, and security.
3. **Prove it on the real artifact.** A served page, a DB row, a measured delta, a re-executed
   command exiting 0 — never a unit return that merely *claims* success. If the proof can be faked
   by typing a string, it is theater; make the verifier executable.

## Layer 3 — `audit` (the environment / workshop)

A periodic check that the workspace keeps the agent aligned.

1. **Context doc.** Is the repo's agent-facing doc structured as: how the repo works · which tools
   to use when · where things live · the key rules?
2. **Knowledge base.** Is durable knowledge landing somewhere it will be found next time, not lost
   in a transcript?
3. **Skills.** Anything done repeatedly that should become a reusable skill? (Every new skill costs
   context on every turn — prefer modes/args over proliferation.)
4. **Rules → enforcement.** Bucket actions ALWAYS / ASK-FIRST / NEVER. For each critical NEVER,
   prefer a tool-level guard (a hook that blocks it) over a prose rule a model can forget.

---

This skill is platform-neutral — it names a method, not a toolchain. It pairs naturally with
[pathway-operating-layer](https://github.com/7alexhale5-rgb/pathway-operating-layer), which makes
the same Spec → Verify → Build loop executable: foundation-first recommendations, an enforced
coverage guarantee, real re-executed proof, and independent evaluation of its own picks.
