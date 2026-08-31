# Decision: OS-owned approval authority

Date: 2026-08-31

Status: implemented locally; installation and bootstrap require Alex in a normal
Terminal

## Context

The prior agent-shell guard contained a chat-override path. The same user account
could also edit the repository CLI, its hook, and the user-owned approval ledger.
That made the guard useful friction but not an independent approval authority.

The forensic record identifies six exact tickets created through that removed
path. Their historical records must remain visible, but they cannot retain live
waiver or release credit.

## Decision

- The live authority ledger is fixed at
  `/Library/Application Support/Pathway/approval-authority.ndjson` on macOS.
- The only live writer is fixed at `/usr/local/libexec/pathway-approval`.
- The helper, directory, ledger, and sudoers rule are root-owned and reject
  symlinks, hard links, group/other writes, alternate paths, malformed records,
  partial records, unsafe ownership, and oversized ledgers.
- Every mutation requires a real non-root `SUDO_USER`/`SUDO_UID` and a fresh
  password-required `sudo` invocation.
- Issue commands bind the canonical subject to its final consumer and append the
  issue plus consumption in one locked, fsynced transaction.
- Invalidation is append-only. Historical issue and consumption rows remain so
  the engine can establish that removed credit was causally load-bearing.
- The repository CLI validates requests and renders exact helper commands. It
  does not mutate live authority.
- The PreToolUse hook remains defense in depth only.

## One-time trust ceremony

The installer and helper originate in a mutable checkout, so installation is a
one-time trust ceremony. The repository installer must never be executed
directly with `sudo`. Alex reviews both exact digests, stages both files with
fixed Apple tools into `/private/var/root/pathway-approval-bootstrap`, verifies the
root-owned staged bytes, and executes only the verified staged installer.
Steady-state separation begins only after the installed copy verifies its own
full path chain and ledger.

Bootstrap imports the exact digest-pinned legacy ledger as audit history and
appends an invalidation for every legacy issuance. The six tickets traced to the
removed chat override remain specifically identified in the forensic record,
but no other user-ledger ticket is promoted into root authority without fresh
human approval. The agent does not run either ceremony.

## Compatibility

The user-owned `operator-intelligence/approvals.ndjson` remains an append-only
historical record. It does not grant live credit. Current work status, routing,
carry-forward, calibration, dashboard, and closeout all re-evaluate the fixed
OS authority and fail closed when it is missing or invalid.

## Recovery

Do not delete or rewrite either ledger. If the installed helper or authority is
damaged, stop approval-dependent work, retain the bytes for forensics, repair the
root-owned installation through a newly reviewed ceremony, and verify the exact
ticket and consumer before restoring credit.
