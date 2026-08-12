# Pathway Operating Layer - Present State

Updated: 2026-08-12
Active work ID: none
Current outcome: the two Pathway proof-integrity outcomes stay closed. A large second wave of work is
still uncommitted in a mixed dirty worktree, and that worktree is what the green suite currently
measures.

Every number below was read from the running system on 2026-08-12, not carried forward from the
previous version of this file. The prior version was self-dated 2026-07-11 and had drifted 12 commits
behind. Its `514/514` suite count is superseded.

## Verified now

- HEAD is `fcdf0b4`, dated 2026-08-10, "fix(trust): give the two thin guard probes real timing
  headroom". Twelve commits landed in the last 30 days.
- The suite at HEAD passes `621/621 checks`.
- The suite against the current dirty worktree passes `768/768 checks`. The higher number belongs to
  uncommitted code, so do not quote it as the shipped count.
- Four files are modified and uncommitted: `scripts/operating-layer.py`,
  `scripts/tests/operating_layer_test.py`, `docs/pathway-proof-integrity.md`, and this file. The diff
  is about 4,756 added and 118 removed lines. The three code and doc files were last edited on
  2026-08-12 at 14:24, so this is recent in-flight work, not a 32-day-old leftover.
- Unpushed commit count is UNKNOWN, not zero. Branch `main` has no upstream configured, so the
  local-versus-remote question cannot be measured here.
- The central ledger holds 2,707 proof records, 298 work items, and 1,707 carry-forward rows.

## Closeout truth, unchanged history

- `W-20260706-pathway-operating-layer-raise-pathway-command-to-3402fb` closed with an active-proof
  audit score of `100/100`.
- `W-20260629-pathway-operating-layer-elevate-pathway-to-world-2819f3` closed after `7/7` required
  pathway proofs were ready.
- That closed selected-scope audit had zero document drift, `12/12` active proof integrity, and
  `11/11` itinerary coverage. Those are dated results from July, kept as history.

## Delivered surface

- `pathway-audit` reports score, dimensions, metric snapshot, document drift, refinements, a Markdown
  and HTML report, and a local audit signal.
- Proof scoring separates current active-outcome integrity from historical attestation-only records.
- The canonical pathway catalog, verifier templates, secret redaction, release-receipt validation, and
  audit payload lineage checks are covered by the suite.
- Closeout proof artifacts live under `.planning/full-cycle-pathway-marketplace/`.
- Since the last version of this file: `pathway --max` shipped as a rigor-only modifier with a guard
  test, the security pathway became read-only-then-fix, artifact names use the operator's local day
  instead of UTC, owner-family-nested projects resolve so a nested repo's proof can credit, and a
  proof that will not credit now emits a loud warning instead of failing quietly.

## Follow-up queue

1. **Closed.** `pathway-next` now routes a fully covered itinerary to an explicit ready-to-close
   recommendation. `ready_to_close` appears 11 times in the live CLI.
2. **Partly closed.** `work-close` returns `report` and `html` in its success response, but the
   success branch still omits the closed `work_id`. Only the not-closed branch carries it. Add
   `work_id` to the success return.
3. **Needs re-measuring, not just planning.** The old figure of `27` historical attestation-only proof
   records no longer matches the ledger. Five records now carry the type `attested` out of 2,707
   total. Re-derive the real migration backlog from the current ledger before scheduling that work.
4. **New defect, found 2026-08-12.** The anti-gaming canary cannot fail a Python verifier that names
   its own source file as the canary target. For every pathway except `release` and `observability`,
   `work-log` runs `run_generic_verifier_snapshot`, which captures the verifier's source bytes up
   front and feeds that snapshot to the interpreter. The canary then mutates the file on disk, but the
   snapshot is immune, so the mutant still exits 0 and the proof is stamped
   `canary_mutant_failed: False` and `trivial_verifier: True`. The trap is that
   `select_canary_target` still reports a valid-looking target of `verifier_named_changed_file`, so it
   reads like the canary worked. Calling `run_canary_mutant` directly on the same command returns
   `True`, which is how the contradiction surfaced. Found while proving the agent-assurance quality
   lane. The working shape is to make the verify command name the data artifact it reads, so the
   canary mutates the receipt instead of the verifier.
5. Decide the commit boundary for the uncommitted wave described above. It has been sitting dirty
   through at least one full day of edits.

## Guardrails

- Keep audit scoring read-only and local.
- Preserve the separation between active proof evidence and historical migration debt.
- Do not commit the mixed worktree without first isolating the intended diff and reviewing it. That
  rule held on 2026-07-11 and still holds, only now the diff is far larger.
- Stamp this file with its own date on every edit. A current-state doc with no date of its own may not
  assert present-tense status, and file modification time is never that date.
