# Implementation — waiver/approval authority

Decision: implement inside operating-layer.py as an approval-issue subcommand
plus small pure helpers, deployed instantly through the existing symlink; no
second script, no new dependencies (stdlib only).

Constraint: no duplicate module-level names (the suite enforces it);
validate_release_receipt and proof_is_verified stay pure — approval context is
passed downward from callers that hold `paths`, and the ledger join lives in
work_status_summary and work-cover where I/O already happens.

Risk: threading an approval context through release_receipt_from_evidence
touches a hot path used by tests and work-log; mitigated by a fail-closed
default (no context means today's behavior) so every existing call site keeps
its semantics until explicitly wired.

Verification: the full suite after every edit cycle; new tests for the issue,
consume, refuse, and corroborate paths; a clean diff reviewed by the critic
pass before commit.
