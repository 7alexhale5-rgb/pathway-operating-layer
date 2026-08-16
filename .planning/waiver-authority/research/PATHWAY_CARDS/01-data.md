# Data — waiver/approval authority

Decision: store approvals as append-only ndjson events (`approvals.ndjson`) in
the operator-intelligence store, matching every other engine ledger. The
consumed event is the durable consumption state; nothing is ever deleted.

Constraint: the engine writes only to the central store, never a project repo.
The 64MB NDJSON read cap applies; front-truncation silently drops the newest
records, so the ledger stays small (two events per ticket) and the existing
loud stderr warning covers overflow.

Risk: a schema drift between issued and consumed events could break the
corroboration join; mitigated by one subject-digest key shared by both event
kinds and tests that round-trip issue-consume-corroborate.

Verification: suite tests assert event shape, digest stability under key
reordering, and the join from proof and itinerary rows back to ledger events.
