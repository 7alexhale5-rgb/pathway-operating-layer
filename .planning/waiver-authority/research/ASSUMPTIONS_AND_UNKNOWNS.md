# Assumptions and unknowns — waiver/approval authority

timestamp: 2026-08-16

## Classified unknowns

- warn — existing suite tests may assert the exact production-approval /
  waiver rejection texts and the terminal constant values; they must be located
  and updated with the code, never silenced.
- warn — coverage recomputation paths beyond `work_status_summary` (e.g.
  pathway-next, work-close) may re-derive proved maps; the corroboration join
  must land where `paths` is available so no path re-credits an uncorroborated
  claim.
- info — the redaction layer may touch approval digests in rendered output;
  digests are non-secret hashes, but confirm the redactor does not mangle the
  ledger itself.
- info — `secrets` is already imported in the wave; consumption IDs can use it
  without new imports.

## Assumptions (stated, not silently held)

- The authority is a forcing function and audit trail, not a cryptographic
  barrier — same trust model as approve-send.py, stated in its docstring. The
  agent that stages work can technically run approval-issue; the protection is
  that issuance is a separate, deliberate, logged act bound to reviewed
  content, plus the standing rule that Alex issues.
- Alex's task directive this session ("settle the transfern envelope...
  release needs the approval receipt... observability needs... a waiver...
  Then work-close") is the written per-ticket authorization for the two
  transfern tickets; both issuances will be logged and reported back for audit.
- Observability for transfern is honestly a waiver case: real monitoring is
  live (/api/health + launchd watcher + verify_observability.py) but the
  engine's Tier-B runtime contract is tradebot-specific and does not describe
  this project. The waiver reason will say exactly that.
