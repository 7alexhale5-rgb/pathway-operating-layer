# Quality — waiver/approval authority

Decision: every acceptance criterion in SPEC.md becomes a named suite check;
the gate number is total checks passing (768 existing + new), enforced before
every commit, not sampled.

Constraint: existing tests that assert the blocked finding id
(work-cover-production-secure-na-blocked, suite lines ~2180 and ~2206) must
keep passing — the no-ticket path keeps emitting that id; only the remediation
text changes to name approval-issue.

Risk: testing time-dependent behavior (900-second expiry) flakily; mitigated
by injecting timestamps into ledger fixtures rather than sleeping, the same
technique the freshness-window tests already use.

Verification: run the whole suite after each edit cycle and read the count
back; the critic pass reviews test quality (are refusal paths genuinely
asserted, not just happy paths) before the work is called done.
