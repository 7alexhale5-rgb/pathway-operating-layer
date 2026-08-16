# Contradictions — waiver/approval authority research

timestamp: 2026-08-16

## Found and resolved

1. Memory `feedback_release_and_observability_cannot_credit_on_this_machine`
   (verified 2026-08-13) says "stop chasing those two numbers" and "never edit
   those constants." The task directive (2026-08-16) says build the authority
   so they can credit. Resolution: no contradiction in substance — the memory
   forbids flipping constants WITHOUT the verification channel (gaming); the
   task builds the channel and flips the state as its honest completion. The
   memory must be rewritten after this ships, or it will mislead the next
   session (higher tier wins: running system > memory).
2. STATE.md (2026-08-12) said HEAD was fcdf0b4 with four dirty files; live git
   showed HEAD a3dd8ef with three dirty files (STATE.md itself had been
   committed). Resolution: trusted git; STATE.md was one commit behind on its
   own line item. Its substantive claims (wave content, suite counts) all
   re-verified true.
3. Memory `feedback_pathway_canary_verifier_pattern` says a `None` canary
   (commit distance) credits a proof. True for generic pathways, FALSE for
   release: proof_is_verified line 2737 requires `canary_mutant_failed is
   True` for release. Resolution: code wins; the transfern release verifier
   must genuinely trip the canary (name the receipt as mutable data).

## Open

None blocking the build.
