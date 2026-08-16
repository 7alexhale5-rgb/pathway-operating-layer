# Decision inputs — waiver/approval authority

timestamp: 2026-08-16

## Decisions the research feeds, with the input that decides each

1. Ledger events vs ticket files → **ndjson events** (`approvals.ndjson`).
   Input: the engine's entire trust model is append-only ndjson ledgers in the
   operator-intelligence store (Paths class, read_ndjson); a consumed event IS
   the durable consumption state the proof-integrity doc demands. Ticket files
   deleted on use (approve-send.py's model) would erase the audit trail the
   engine wants to re-join at status time.
2. Where the approval check lives → **work-log consumption + proof fields +
   status-time corroboration**, not inside pure validators. Input:
   `validate_release_receipt` is pure (no paths); `proof_is_verified` is pure;
   `work_status_summary` and work-log have `paths`. Purity is preserved by
   passing an approval context downward and re-joining at status time.
3. In-engine subcommand vs separate script → **subcommand (approval-issue)**.
   Input: one file, one existing symlink deploy path, stdlib only, and the
   suite's source-integrity guard covers it. A second script would need its
   own symlink and would duplicate ledger helpers.
4. External `sent` receipts → **stay fail-closed**. Input: task scope names
   (a) release production approval and (b) --na waiver only; sends already
   have approve-send.py + external-send-guard as their channel.
5. Observability route for transfern → **waiver, not Tier-B receipt**. Input:
   Tier-B contract (lines 1211-1342) is frozen tradebot-specific (metric
   names, drill questions) and cannot describe transfern; trusted-verifier set
   is deliberately empty and configuring it is a separate, bigger decision.
6. TTL → **900 seconds**, mirroring approve-send.py per the task directive,
   not the 24-hour evidence window (that window governs evidence freshness,
   not human-approval freshness).
