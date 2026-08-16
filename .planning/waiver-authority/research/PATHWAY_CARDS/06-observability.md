# Observability — waiver/approval authority

Decision: the Tier-B trusted-verifier channel stays unconfigured; the waiver
becomes the honest route for projects (like transfern) whose real monitoring
exists but does not match the frozen tradebot runtime contract.

Constraint: a waiver never manufactures observability credit — it marks the
obligation not-applicable with a verified, single-use, reason-bound human
decision, and the reason text is part of the ticket digest so it cannot be
edited after review.

Risk: waivers becoming the default path of least resistance for every
observability obligation; mitigated by per-ticket issuance (no standing
authority), the append-only audit log, and status-time corroboration that
reopens any waived row whose ledger evidence is missing.

Verification: tests assert a corroborated waived row survives status
recomputation, an un-waivered row still reopens, and a tampered waiver_digest
reopens; the transfern waiver reason names the live monitoring evidence.
