# The Karpathy Method — Spec → Verify → Environment

A generic, tool-agnostic distillation of the three-layer agentic method Andrej Karpathy
described (AISN, 2026): **Spec → Verifier → Environment**. It is the discipline
`pathway-operating-layer` embodies, written here so anyone can apply it without this
project's machinery.

> **The one rule:** you can outsource your thinking, but not your understanding. Every
> layer below centres on the goal only you can supply. Don't let the tooling hide the goal.

Use all three for a fresh build (spec → build → verify), with the environment audit as a
periodic tune-up. They are not a one-time checklist — they are how each unit of work is run.

---

## Layer 1 — Spec: deliver your understanding

The agent can write the code. It cannot decide what the code is *for*. That decision is
the spec, and it is the part you own.

- **Goal before task.** Don't start from the task statement ("add an endpoint"). Pin the
  *decision the work drives* ("we need X so that Y can happen"). If the work is non-trivial
  or ambiguous, interview yourself — or have the agent interview you — until the goal is
  explicit. A task you can't tie to a decision is a task you can't prioritize or verify.
- **Smallest scope that ships one thing end-to-end.** Not a partial integration, not a
  status update — a runnable slice. Bias to many small, compartmentalized specs over one
  big waterfall. The failure modes of the first slice shape the design of the next.
- **Falsifiable acceptance gates.** Write down what "good" looks like as checkable
  conditions *before* building. "Tests pass" is not a gate; "p95 latency under 200ms on the
  staging dataset" is. If you can't state the number that would prove it, you don't yet have
  a spec — you have a wish.
- **Keep it surgical.** Prefer deletion before abstraction; surgical diffs over rewrites.
  Don't add for hypothetical future use. The smallest correct change is the most verifiable
  one.

### The Karpathy ladder (how to pace a multi-phase plan)

When a plan has several phases, pace it like a ladder, not a calendar:

1. **Each phase ships one thing end-to-end against a measured number** — not a status
   update, not a partial wire-up. The thing must be runnable; the number must be
   falsifiable.
2. **Each phase has a hard test gate before the next starts.** The gate is a measurement
   (an eval pass-rate, a latency floor, an error count), not a checklist item.
3. **Phases never collapse.** A six-phase plan stays six phases. Clearing a gate faster is
   velocity, not a licence to merge phases or skip one.
4. **Throwaway version first.** Build the dumbest end-to-end version before adding
   abstractions. v1's failure modes are the design input for v2.
5. **Stop at the threshold.** When the measured number clears the gate, lock the phase and
   move on. Don't over-fit; don't keep optimizing past the gate.

Write the spec down (a short planning doc), and **do not build yet.** The spec is a
separate act from the implementation.

---

## Layer 2 — Verify: the only real lever

This is where quality is actually won or lost. An agent will happily produce
plausible-looking, wrong work; the verifier is what catches it. Most teams under-invest
here because verification is less visible than features.

- **Criteria up front.** Restate the acceptance conditions from the spec as the literal
  pass/fail you'll check against. For prompt or model changes, capture them as a fixed
  evaluation set (a golden set) you can re-run, so a regression is a failed assertion, not a
  vibe.
- **An independent second-model critic on the diff.** Have a *different* model family review
  the actual diff against the same brief — not the model that wrote it grading its own
  homework. A genuinely independent reviewer catches bugs the author's model is blind to;
  where two independent reviewers agree, your confidence is high. The brief should demand the
  basics — duplication, unjustified complexity, speculative generality, separation of
  responsibilities, plus correctness, edge cases, and security — and flag any violation
  before shipping. You (the human) adjudicate the union of findings: fix the confirmed ones,
  dismiss false positives with a one-line reason. The critic is an input, not a gate; you own
  the fix.
- **Prove it on the real artifact.** The single highest-leverage rule: validate against the
  thing the user actually touches — a served page, a row in the database, a deployed asset, a
  measured delta — **not** a unit return or a function's in-memory output. A unit test that
  passes while the feature is broken in production is the failure mode this rule exists to
  prevent. If you claim "done," there must be evidence from the real artifact.

The reason `pathway-operating-layer` re-executes a verifier and hashes the artifact rather
than accepting a free-text "I ran the tests" is exactly this layer: a claim is not a
verification. Design your own process so that proof is something re-runnable, not something
asserted.

---

## Layer 3 — Environment: the workshop

The agent works inside an environment — the repo's context, its captured knowledge, and its
guardrails. A messy workshop produces messy work no matter how good the spec. Audit it
periodically.

1. **Is the repo's context document structured?** A good project context file
   (`CLAUDE.md` / `AGENTS.md` / a README for agents) carries four things: (a) how the repo
   works, (b) which tools/skills exist and when to reach for each, (c) where things live — a
   knowledge map, and (d) the key working rules. If an agent has to rediscover the layout
   every session, the context doc is failing.
2. **Is durable knowledge being captured, in the right place?** Decisions, cross-session
   state, and deep research should land somewhere findable and re-readable — not evaporate at
   the end of a session. Read the knowledge base first; write back to it when you learn
   something that the next person (or the next session) will need.
3. **Is anything done repeatedly that should be a reusable skill/script?** Recurring work
   wants to be encoded once. But every reusable abstraction has a carrying cost (it's one more
   thing to know about), so prefer adding a *mode* to something that exists over creating a new
   thing. Encode patterns; don't proliferate.
4. **Are critical rules enforced by hooks, not prose?** Bucket actions into ALWAYS /
   ASK-FIRST / NEVER. For each critical NEVER — committing a secret, force-pushing,
   dropping a table, declaring "done" without evidence — check whether a *mechanical* guard
   enforces it (a pre-commit hook, a pre-tool check, a CI gate). Prose in a context file is a
   suggestion; a hook is a wall. If a critical NEVER has no hook, add one. Soft, behavioral
   rules can stay as prose.

---

## Why this works

The method front-loads the two things agents are worst at — knowing the goal and knowing
when they're wrong — and pushes them onto the human and onto mechanical verification, where
they belong. The agent does the typing. You keep the understanding, design the verification,
and maintain the workshop. That division is the whole point.
