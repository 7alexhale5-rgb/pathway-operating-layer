# Design — waiver/approval authority

Decision: no UI surface; the design object here is the CLI and ledger
ergonomics. approval-issue mirrors approve-send.py's operator experience:
print the digest prefix, the expiry in minutes, the single-use notice, and the
exact next command, so Alex can review and act in one glance.

Constraint: plain-English output discipline applies — the refusal finding for
an un-ticketed N/A must name the one command that fixes it, not just the
policy; error text never quotes internal state constants at the operator.

Risk: a confusing two-kind interface (release approval vs waiver) leading to
wrong-kind tickets; mitigated by kind-specific required flags (release
requires --release-receipt, waiver requires --pathway and --reason) with
argparse-level enforcement.

Verification: CLI help text reviewed in the critic pass; tests exercise both
kinds end-to-end including the wrong-flag refusal paths.
