# Security — waiver/approval authority

Decision: same trust model as approve-send.py, stated openly — a forcing
function and audit trail, not a cryptographic barrier. The agent that stages
work can technically run approval-issue; the protection is that issuance is a
separate, deliberate, logged act bound to reviewed content, plus the standing
rule that Alex issues.

Constraint: fail closed everywhere — consumed, expired, subject-mismatched,
or uncorroborated tickets must never credit; external `sent` receipts stay
locked (sends keep their own guard channel).

Risk: a forged proof row claiming approval fields without a ledger event;
mitigated by status-time corroboration re-joining digest, subject, and
consumed_by across ledgers. Second risk: digest collision via non-canonical
JSON; mitigated by sort_keys + compact separators, tested.

Verification: replay, expiry, tamper, and uncorroborated-claim tests all
assert refusal; the suite's source-integrity guard covers the new code.
