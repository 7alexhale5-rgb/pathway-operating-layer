# Docs — waiver/approval authority

Decision: docs/pathway-proof-integrity.md gains an authority section replacing
the "until a waiver authority exists" language: ticket kinds, subject binding,
TTL, single-use consumption, ledger location, and the corroboration join, in
the same voice as the existing receipt sections.

Constraint: the doc states what the code enforces, nothing aspirational; every
sentence must be checkable against a suite test or a code line, matching the
document-is-a-claim doctrine.

Risk: stale downstream references — the hard-block memory
(feedback_release_and_observability_cannot_credit_on_this_machine) and the
skill's coverage expectations ("max 10 of 12 locally") become wrong the moment
this ships; both are queued for rewrite in the same session so no future
session inherits a false ceiling.

Verification: after the build, grep docs and memory for the old terminal-state
strings and the 10-of-12 ceiling; each hit is either updated or explicitly
marked historical.
