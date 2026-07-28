# Data Boundary - Proof Canary Target Selection

Date: 2026-07-11
Pathway work: W-20260711-pathway-operating-layer-harden-proof-canary-muta-c7a065
Pathway: data

## Record Contract

Future executed proof records add these fields without changing existing proof IDs or evidence hashes:

| Field | Type | Meaning |
| --- | --- | --- |
| `canary_target` | string or `null` | Repository-relative selected file, never an absolute path. |
| `canary_target_source` | `explicit`, `verifier_reference`, or `unavailable` | How the target was selected. |
| `canary_target_reason` | stable enum string | Why selection succeeded or why no safe target applied. |
| `canary_mutant_failed` | `true`, `false`, or `null` | Verifier failed on a relevant mutation, ignored one, or no mutation applied. |

The example JSON beside this record is a valid strict-proof receipt: an explicit, changed, regular in-repository file was mutated and the verifier failed.

## Selection Boundary

`--canary-target` accepts a relative or absolute user input, but persistence normalizes it to a repository-relative path. The resolver rejects paths outside the verification checkout, symlinks, directories, unreadable/binary files, and files without a mutable changed line.

Automatic selection records `verifier_reference` only for a changed file directly named by the verifier command. It never selects the first dirty file merely because it appears in the checkout. When no relevant target is available, the receipt is:

```json
{
  "canary_target": null,
  "canary_target_source": "unavailable",
  "canary_target_reason": "no_relevant_changed_file",
  "canary_mutant_failed": null
}
```

The raw user input, shell token stream, absolute target path, and unrelated changed-file list are not persisted in proof records.

## Compatibility

Existing proof records have no target-provenance fields. Readers must treat their absence as the legacy format, not as `false` or as evidence of a failed mutation. New records always carry all four fields when an executed verifier is considered for a canary.

## Verifier

```text
/bin/bash /Users/alexhale/Projects/pathway-operating-layer/.planning/2026-07-11-proof-canary-target-selection/verify-data.sh
```

## Summary

Proof receipts will persist only a safe, repository-relative canary target plus deterministic selection provenance, allowing `None` to mean no relevant mutation was available.

## What Changed

- Defined the four-field canary receipt contract and a strict-probe example record.
- Separated selected-target provenance from the tri-state mutation result.
- Prohibited persistence of absolute paths, shell-token input, and unrelated dirty-file lists.

## More Relevant

- Implementation must normalize explicit paths before persistence and preserve legacy records without inventing provenance.
- Quality must assert both strict-target and unavailable-target receipt shapes.

## Less Relevant

- A first-dirty-file heuristic has no place in the new receipt model.
- Database migrations and external data stores are not part of this local JSONL contract.

## Next Pathway Must Use

- Read this data contract before adding CLI parsing or proof-record fields; preserve the nullable target/result pair and repository-relative persistence rule.

## Do Not Do Yet

- Do not persist raw command tokens, absolute paths, arbitrary dirty-file inventories, or a target outside the verification checkout.

## Open Decisions

- Whether the receipt should use `canary_target_reason` exactly as named here or a shorter `canary_reason` alias; the implementation must choose one stable public field.

## Active Risk Overlays

- rollback
