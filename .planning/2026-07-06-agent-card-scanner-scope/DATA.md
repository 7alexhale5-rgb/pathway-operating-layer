# Agent-Card Scanner Data Contract

Status: pass
Work item: W-20260706-pathway-operating-layer-fix-agent-card-scanner-s-c64f27
Pathway: data

## Record Model

The scanner must classify a local directory before creating a capability card.
The contract fixture uses these fields:

| Field | Meaning |
| --- | --- |
| `source_path` | Repository-relative input directory; never a resolved external path. |
| `inclusion_signal` | The regular local file that qualifies the record. |
| `kind` | `hermes-profile`, `helper-folder`, `legacy-automation`, or `symlinked-candidate`. |
| `expected_selected` | Whether the record becomes an agent capability card. |
| `expected_incomplete` | Whether a selected record must remain in the readiness finding. |

The fixture records one real Hermes profile by its `manifest.json`, two real
helper folders that happen to have generic `README.md` files, a legacy Codex
automation, and the security regression case for a symlinked candidate.

## Boundary And Lineage

The primary input is the active Hermes profile manifest at
`hermes/profiles/atlas-ceo/manifest.json`. It provides a real profile name and
rung. Generic helper documentation is not agent identity. A legacy automation
also does not enter the Hermes readiness population without a future,
deliberate autonomous-agent signal. Symlinked candidates remain excluded under
the preceding security proof.

## Metric

`agent_cards_scope_false_blockers` is the count of unselected records that are
incorrectly expected to be incomplete. The fixture target is `0`, while the
real Hermes profile remains selected and incomplete so the readiness warning is
not weakened.

## Proof

`verify-data.py` parses the structured fixture, confirms its exact record
contract, reads the real Atlas manifest, confirms both real helper directories,
and writes a receipt with the selected record and zero false blockers.

Verification command:

```bash
cd /Users/alexhale/Projects/pathway-operating-layer && python3 .planning/2026-07-06-agent-card-scanner-scope/verify-data.py && python3 -m py_compile scripts/operating-layer.py && git diff --check
```

## Summary

Status pass: the scanner-scope data model now separates manifest-backed Hermes
profile records from generic helper folders, legacy automations, and symlinks.

## What Changed

Added a versioned fixture and verifier that preserve one incomplete real Hermes
profile while defining zero false blockers for helper, legacy, and symlinked
records.

## More Relevant

Implementation must consume `manifest.json` as the explicit Hermes profile
signal and preserve the exact fixture selection set.

## Less Relevant

No database migration, remote data store, runtime profile mutation, or external
API call is needed; this is a local filesystem record contract.

## Next Pathway Must Use

Use `agent-card-scope-fixture.json` as the expected selection data and keep the
security symlink case in the scanner regression test.

## Do Not Do Yet

Do not add metadata to every legacy Codex automation, alter Hermes runtime
profiles, mutate central ledgers by hand, push, deploy, or close the work item.

## Open Decisions

Whether a later automation-specific scanner should define a separate explicit
autonomous-automation marker and readiness population.

## Active Risk Overlays

`llm-agent-eval`.
