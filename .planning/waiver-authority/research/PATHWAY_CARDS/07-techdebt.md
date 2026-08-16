# Techdebt — waiver/approval authority

Decision: this build pays one debt and avoids creating another — the
2026-08-12/13 hardening wave was committed as its own boundary (73d5395)
before new work landed, resolving STATE.md follow-up 5 (the sitting dirty
worktree).

Constraint: surgical diff discipline — every changed line traces to the SPEC;
the external-send branch keeps its fail-closed behavior with only a message
cleanup so the flipped constant cannot mislead.

Risk: the two known open defects (work-close success omitting work_id;
attestation-migration backlog re-measurement) tempt scope creep; they stay in
the STATE.md follow-up queue untouched. Second risk: leaving misleading text
behind — any message quoting the old NOT_CONFIGURED states must be updated
with the code.

Verification: grep for both old state strings after the build; only historical
docs and the memory rewrite queue may reference them, never live engine text.
