# Pathway Proof Integrity

`pathway-audit` is a local scorecard, not a deploy command or a release decision.
It reports a score even below `92` so later quality policy can make an explicit
pass/fail choice.

## What Counts As Proof

Every proved pathway needs an evidence file and an executed `--verify-cmd` that
exits zero. A reviewer name or `--verified-by` is retained as accountability
context, but it is not proof. The engine records artifact and verifier hashes,
rejects recognizable no-op verifiers, and may run a safe canary mutation when it
has a relevant changed file.

The audit reports:

- proof integrity from verified project proof records;
- current itinerary coverage;
- carry-forward continuity;
- authority-document alignment and explicit drift findings;
- whether required field and release proof exist.

## Credential Hygiene

All local JSON, Markdown, HTML, and NDJSON writes pass through the same redaction
boundary. It removes named secrets, common provider-prefixed keys such as `xai-`
and `github_pat_`, HTTP bearer credentials, and high-entropy token strings.

Use synthetic credential values in tests. Do not put a real credential into an
evidence artifact in order to test redaction.

## Release States

Release receipts keep readiness separate from mutation:

| State | Meaning |
|---|---|
| Preview `ready` | Local or preview verification is complete; production remains untouched. |
| Production `deployed` | Requires human approval, deploy/verification/rollback artifacts, and a rehearsed or executed rollback. |
| External `send-ready` | Prepared for a send but not sent. It cannot satisfy a sent claim. |
| External `sent` | Requires explicit human approval. |

A preview-ready receipt can prove release planning without authorizing a deploy,
canary, feature-flag change, rollback, or external send.

## Operator Checks

```bash
python3 scripts/operating-layer.py pathway-audit --project /path/to/project --json
python3 scripts/tests/operating_layer_test.py
```

The audit output names the report and HTML artifact paths. Treat the ledger,
proofs, controls, and carry-forward records as the status authority; vault notes
and old reports are context only.
