# Govern — waiver/approval authority

Decision: create a verifiable human-approval channel so release and observability
obligations stop being terminal dead ends, without weakening the anti-gaming
posture. The falsifiable gate number is suite checks: all 768 existing checks
plus every new acceptance-criteria test must pass before commit.

Constraint: issuing stays a deliberate human act; the engine only verifies and
consumes. Alex issues per waiver/approval; every issue and use is logged
append-only for audit.

Risk: the authority becomes a rubber stamp if consumption is not content-bound;
mitigated by SHA-256 subject digests and single-use durable consumption.

Verification: acceptance criteria 1-12 in SPEC.md, each mapped to a suite test;
status-time corroboration re-joins every claim against the approvals ledger.
