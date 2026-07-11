# Security Redaction Boundary Receipt

Date: 2026-07-11
Project: `pathway-operating-layer`
Work item: `W-20260706-pathway-operating-layer-raise-pathway-command-to-3402fb`
Pathway: security
Status: pass

## Threat Surface

The local operating layer ingests logs, review findings, verifier output, and
carry-forward artifacts into operator-intelligence. Those values may contain API
keys or HTTP authorization headers. The relevant boundary is therefore every
`write_json`, `write_text`, and NDJSON ledger write, all of which pass through the
same redaction layer.

## Finding And Fix

The existing redactor handled `sk-*`, key-value names, and long entropy strings,
but it did not explicitly cover a shorter provider-prefixed credential or an HTTP
`Authorization: Bearer` header. Added provider prefixes including `xai-` and
`github_pat_`, plus bearer-header redaction before any output write.

## Verification

```bash
cd /Users/alexhale/Projects/pathway-operating-layer && python3 .planning/full-cycle-pathway-marketplace/security/verify-secret-redaction.py && python3 scripts/tests/operating_layer_test.py && git diff --check
```

The verifier uses synthetic credentials only. It confirms each is absent both
from in-memory output and from a JSON receipt written through the production
writer.

## What Changed

Provider-prefixed and bearer credentials are now redacted at the shared local
output boundary; no real credential was read, logged, or sent.

## More Relevant

Quality can rely on the added regression when exercising proof artifacts and
verifier output. The next security-sensitive additions must preserve this shared
writer boundary rather than implementing per-command masking.

## Less Relevant

There is no network, runtime-profile, deployment, or external-service change in
this slice.

## Next Pathway Must Use

Quality should keep this redaction fixture alongside hollow-proof checks and
assert that report artifacts never contain synthetic provider credentials.

## Do Not Do Yet

Do not print, rotate, or probe real credentials; do not make external calls or
change production authorization state.

## Open Decisions

Future provider-specific patterns can be added when a documented format appears,
but the generic secret and bearer boundaries remain the primary control.

## Active Risk Overlays

`rollback`, `human-gate`, `llm-agent-eval`.
