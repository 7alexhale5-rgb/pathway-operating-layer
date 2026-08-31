---
captured_at: 2026-08-31
base_commit: 9ecedb620169fdcd5919e5cd7f3fd26d9ac67387
status: preserved-before-surgical-removal
---

# Approval chat-override forensic record

This record preserves identifiers and cryptographic digests only. It does not
copy approval reasons, credentials, transcript bodies, or the removed bypass
source. No approval, invalidation, proof, or work-item ledger was mutated while
capturing it.

## Pre-repair source snapshot

| Evidence | Value |
| --- | --- |
| Base hook SHA-256 | `98bf9036cf838a2aac4f7a0d77b98d0810fe6f2bad23f795aa5a6486ff8efb12` |
| Pre-repair worktree hook SHA-256 | `a6b68b1aec67b375aa09e55d6e3660daac8dec16f48aa1c2f040edf052c09a7a` |
| Exact pre-repair hook diff SHA-256 | `09b814a3bd6ece42928f0146c41351c9454b43b953aee3b8dbc55753067cd05e` |
| Exact pre-repair hook diff size | 2,113 bytes, 43 lines |
| Override log SHA-256 | `9603da93a208419e034422add63937300589d60626d6fa110befe0fe15ce21e8` |
| Override log snapshot | 864 bytes, 9 lines, mtime_ns `1788124240203207306` |

The first eight override-log rows correlate with six issued tickets below. The
ninth row is the disclosed direct-hook audit probe and issued no ticket.

## Central ledger snapshot

| Ledger | SHA-256 | Lines | Bytes |
| --- | --- | ---: | ---: |
| `operator-intelligence/approvals.ndjson` | `37b067ab41a9775769fce89ba1371171642a274c6cb6614a0f369a7636ba2a99` | 41 | 28,535 |
| `operator-intelligence/work-items.ndjson` | `f1748e31ef54cb67e2d9e162d12514f925532019396e2209c2151094f6a686fd` | 325 | 995,704 |
| `operator-intelligence/proofs.ndjson` | `99640819eda3cce42841dbdd42e03fce11390b5cf8fe083ed2001512f21770c8` | 3,042 | 6,468,331 |
| `operator-intelligence/pathway-runs.ndjson` | `f1270a29a3407864ddf6b395f100c6c07f10d449c9f64c369676ce6efd115d02` | 3,286 | 1,534,860 |
| `operator-intelligence/pathway-carry-forward.ndjson` | `96192c0efb8021f45cf3c333fec434e50bb74a4457c9c123d4f2836e475434a2` | 1,894 | 3,983,424 |

## Exact affected tickets

| Approval row(s) | Ticket | Kind | Work item | Consumption |
| --- | --- | --- | --- | --- |
| 33 | `AT-0fd7f99873b5` | release | `W-20260829-agents-voice-first-agent-org-co-429400` | unconsumed |
| 34 | `AT-fc16cd121a6e` | release | `W-20260829-agents-voice-first-agent-org-co-429400` | unconsumed |
| 35 | `AT-19b0e3d47549` | release | `W-20260829-agents-voice-first-agent-org-co-429400` | unconsumed |
| 36-37 | `AT-03107fa17570` | release | `W-20260829-agents-voice-first-agent-org-co-429400` | `AC-87d7f967cb95`, proof `P-66a142f71ca3` |
| 38-39 | `AT-28d236bf4ff1` | waiver | `W-20260830-agents-subagent-hiring-machine--a4b36d` | `AC-79dc449b72a2` |
| 40-41 | `AT-7e231a6289f9` | release | `W-20260830-agents-subagent-hiring-machine--a4b36d` | `AC-d3f1a0a47c71`, proof `P-0557a94227ea` |

## Human-only corrective ceremony

The former six repository-CLI invalidation commands are superseded. The live
CLI is user-writable and now returns a nonzero helper-required refusal; running
those old commands would not correct authority.

Run this reviewed ceremony from Alex's normal Terminal, outside any agent
session. Do not execute the mutable repository installer directly with `sudo`.
These fixed Apple tools stage the exact reviewed bytes as root-owned files,
verify both hashes, then run only the verified staged copy. The staged installer
imports the exact 41-row legacy ledger above, preserves all historical rows,
appends invalidations for every one of its 29 issued tickets, verifies the
protected ledger, and only then installs the password-required sudoers rule.
The six exact tickets above remain the proven chat-override subset; the other
23 are also denied live authority because independent human authentication was
not established for the mutable-era ledger.

```bash
/usr/bin/sudo -k
/usr/bin/sudo /usr/bin/install -d -o root -g wheel -m 0700 /private/var/root/pathway-approval-bootstrap
/usr/bin/sudo /usr/bin/install -o root -g wheel -m 0500 /Users/alexhale/Projects/pathway-operating-layer/scripts/install-pathway-approval-authority.sh /private/var/root/pathway-approval-bootstrap/install.sh
/usr/bin/sudo /usr/bin/install -o root -g wheel -m 0500 /Users/alexhale/Projects/pathway-operating-layer/security/pathway-approval /private/var/root/pathway-approval-bootstrap/pathway-approval
/usr/bin/printf '%s  %s\n' 'f22b618ba40f105411f5c22a819babd49f52597bbe8ef82ef629f135f45e1a6f' '/private/var/root/pathway-approval-bootstrap/install.sh' | /usr/bin/sudo /usr/bin/shasum -a 256 -c -
/usr/bin/printf '%s  %s\n' '34df494a986a2b56e056190b507e6117fae70a979135418517b311f116e3e323' '/private/var/root/pathway-approval-bootstrap/pathway-approval' | /usr/bin/sudo /usr/bin/shasum -a 256 -c -
/usr/bin/sudo /private/var/root/pathway-approval-bootstrap/install.sh --expected-installer-sha256 'f22b618ba40f105411f5c22a819babd49f52597bbe8ef82ef629f135f45e1a6f' --expected-helper-sha256 '34df494a986a2b56e056190b507e6117fae70a979135418517b311f116e3e323'
```

The installer embeds this exact bootstrap request:

```bash
/usr/local/libexec/pathway-approval bootstrap --source-ledger /Users/alexhale/Projects/memory-vault/operator-intelligence/approvals.ndjson --expected-sha256 37b067ab41a9775769fce89ba1371171642a274c6cb6614a0f369a7636ba2a99 --invalidate-all-issued --reason "Legacy user-owned approval history is audit evidence only; independent human authorization was not established."
```

Neither command has been run as part of this repair. The repository hook is
defense in depth; the root-owned installed helper and ledger are the authority
boundary. See `2026-08-31-os-owned-approval-authority.md` for the decision.
