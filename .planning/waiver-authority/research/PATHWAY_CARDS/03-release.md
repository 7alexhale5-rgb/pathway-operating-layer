# Release — waiver/approval authority

Decision: production release credit becomes reachable through a single-use
approval ticket bound to the exact reviewed receipt digest, replacing the
terminal VERIFIABLE_APPROVAL_NOT_CONFIGURED error.

Constraint: everything else about release credit stays as hard as the wave
made it — envelope binding to work/recommendation/project, fresh
issued_at/expires_at, four artifact digests, stdout verifier binding with
RELEASE_RECEIPT_SHA256, snapshot stability, and a canary that must actually
trip (canary_mutant_failed is True; commit distance does not credit release).

Risk: approving a receipt then editing it; mitigated because the ticket binds
the receipt's SHA-256 at issue time — any byte change orphans the ticket.

Verification: a full production-receipt fixture with an issued ticket credits;
the same fixture without a ticket, with a consumed ticket, or with a mutated
receipt refuses.
