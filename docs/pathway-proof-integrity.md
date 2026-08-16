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

Generic proof receipts record `verify_command_sha256` separately from verifier
source identity. New generic proofs accept only the current trusted Python
interpreter, an optional `-B`, and one directly executed `.py` source. Pathway
normalizes execution to a shell-free argument vector and binds the regular
interpreter target plus the verifier's lexical path, resolved regular target, and
SHA-256 digest. It reads the resolved verifier once, then executes that exact byte
snapshot through the trusted interpreter with `-I -B -S`. The isolated loader
preserves the resolved `__file__`, requested arguments and working directory, and
imports from the verifier's source directory. It removes inherited `PYTHON*`
startup settings and the macOS `__PYVENV_LAUNCHER__` override, so `PYTHONPATH`,
`sitecustomize`, user site packages, and similar ambient Python startup hooks
cannot preempt the captured verifier. A mutation canary rerun receives the same
immutable verifier snapshot.

Pathway hashes the interpreter and live target before execution and after the
verifier and mutation canary complete. Every later proof decision reparses the
command, requires the lexical path to resolve to the same recorded target, and
rechecks both files. A fake interpreter, `env` wrapper, unsupported interpreter
option, shell composition, missing file, unreadable file, changed bytes, symlink
replacement, or mid-run mutation fails closed and reopens any itinerary coverage
earned by that proof. A stable symlinked ancestor is accepted only through this
lexical-to-resolved target binding; retargeting any ancestor invalidates the proof
even when the new verifier has byte-identical source. This boundary does not claim
to isolate a hostile host and intentionally does not snapshot a verifier's broad
import dependency graph. Generic proof scripts therefore use the standard library
plus explicitly local source-directory modules.

Historical receipts without `verifier_source_kind` remain readable. Release and
observability retain their stricter, receipt-specific verifier binding and
mutation checks.

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
| Production `deployed` | Requires an externally verifiable single-use approval receipt, deploy/verification/rollback artifacts, and a rehearsed or executed rollback. |
| External `send-ready` | Prepared for a send but not sent. It cannot satisfy a sent claim. |
| External `sent` | Requires the same externally verifiable single-use approval boundary, even without a deployment. |

A preview-ready receipt can prove release planning without authorizing a deploy,
canary, feature-flag change, rollback, or external send. It does not credit the
release pathway or satisfy production readiness.

Release pathway credit requires a Markdown evidence artifact plus a same-stem
structured JSON receipt. Production credit is currently disabled until Pathway
has an externally verifiable, fresh, single-use human approval receipt bound to
the work, project, stage, release digest, and durable consumption state. Free
text such as `human_approval` is only an attestation and cannot authorize a
release or external send. A future production receipt must also bind an active
or passed canary, production verification, and rehearsed or executed rollback
artifacts. Production evidence binds the exact work ID, recommendation ID,
resolved target project, and a fresh issued/expiry window of no more than 24
hours. Release artifacts must be regular companion-directory filenames;
absolute paths, traversal, and symlinks fail closed. The executed verifier must
also trip Pathway's anti-gaming canary. A
`NO_RELEASE`, `BLOCKED`, all-not-run, preview-only, invalid-template, or missing-
canary record remains evidence of a hold and cannot be relabeled by passing
`--result pass`.

Production-secure itinerary obligations are non-waivable while no verified
waiver authority exists. `work-cover --na` rejects free-text reasons for these
outcomes, and status/closeout reopens any historical N/A row as required. It also
reopens a persisted `proved` label whenever the current proof ledger lacks a
non-stale proof that still passes the current verifier. A production-secure
outcome closes only from current verified pathway proof, not from an assertion
or cached status label.

Pathway hashes the Markdown evidence, structured receipt, and every referenced
release artifact before running the verifier. It re-reads and hashes the same
bundle after the verifier and anti-gaming canary finish. Any pre/post mismatch
fails closed as a verifier-side evidence mutation and cannot receive release
credit or become a carry-forward record.

A constraint-only `blocked_no_deploy` carry-forward can defer release without
crediting it. If another required pathway is open, the router selects the best
non-release prerequisite. If release is the only open pathway, Pathway returns
an explicit prerequisite hold, logs no new recommendation, and points to the
first recorded open decision instead of looping back to release.

## Observability States

Observability has two evidence tiers. Tier A is an honest pre-runtime hold. Its
same-stem JSON companion must carry the exact root state
`PRE_RUNTIME_OBSERVABILITY_CONTRACT`, `SPEC_ONLY_NO_TELEMETRY`,
`pathway_result=BLOCKED`, `credits_pathway=false`, absent runtime and telemetry,
unwired alerts, no drills, `authorized_stage=NONE`, and
`current_verdict=NO_PROMOTE`. The root must also bind exact `work_id`,
`recommendation_id`, and resolved `target_project` values from the current proof
request. The verifier must emit the nine corresponding
`NO_CREDIT`, `BLOCKED_NO_RUNTIME`, absent-telemetry, unwired-alert, undrilled-
runbook, no-promotion, no-tree-mutation, and zero-side-effect markers. Verifier
exit zero means those negative claims are consistent; caller `--result pass`
still cannot credit observability.

```text
OBSERVABILITY_DECISION=NO_CREDIT
OBSERVABILITY_GATE=BLOCKED_NO_RUNTIME
TELEMETRY_STATUS=ABSENT
ALERT_STATUS=NOT_WIRED
RUNBOOK_STATUS=SPECIFIED_NOT_DRILLED
AUTHORIZED_STAGE=NONE
CURRENT_VERDICT=NO_PROMOTE
PROJECT_TREE_MUTATION=NONE
EXTERNAL_SIDE_EFFECTS=0
WORK_ID=<exact work_id>
RECOMMENDATION_ID=<exact recommendation_id>
TARGET_PROJECT=<exact resolved target_project>
OBSERVABILITY_RECEIPT_SHA256=<exact companion digest>
```

A valid Tier-A result creates a constraint-only `blocked_no_runtime` carry-
forward with `credits_pathway=false`. Observability stays open. While another
required prerequisite is available, the router excludes observability and picks
the best non-deferred pathway. If observability becomes the sole open deferred
item, Pathway emits a prerequisite hold and writes no recommendation row, so the
same blocked receipt cannot create a recommendation loop.

Tier B is the only structurally eligible observability state. Final pathway
credit remains disabled until an external trusted-verifier digest is configured
and independently verified. A receipt cannot trust the verifier digest that it
declares about itself. Its typed
`observability_receipt` binds the current work ID, recommendation ID, project,
exact resolved target project, runtime digest, environment identity/class,
stage, verdict, canonical metric
names, log-correlation fields, and executed runtime/telemetry/alert/drill/
recovery/canary booleans. It also binds distinct existing artifacts for metric,
log, trace, alert, runbook drill, failed canary, and the verifier source. The
six evidence artifacts must be strict, nontrivial JSON with matching runtime,
environment, and observation timestamps. Numeric overflow and every non-finite
metric sample fail closed. Metric values must satisfy per-metric domains,
including nonnegative ages, latency, counters, heartbeat ages, and drawdown in
the inclusive range zero to one. Every metric also carries exactly the frozen,
bounded label keys and values; identifier or high-cardinality labels fail closed.
Metric evidence carries every canonical metric and a typed sample; logs carry the
complete frozen event envelope, typed hashes and sequences, canonical timestamps,
bounded asset/mode/decision values, and coherent market/occurrence/observation order; traces carry validated
identifiers; alerts carry fired fail-closed actions; the drill answers the
frozen Tradebot ten-question 3am set with question-specific typed fact objects and
evidence mappings, canonical answer codes, bounded safety-state enums, identifiers
and hashes matched to one structured incident record, digest-bound multi-artifact
recovery evidence, and an enumerated safe disposition, without a prohibited action;
identical narratives, one-character placeholders, and uncorrelated facts fail
closed. The unresolved scenario specifically requires the halt event, denied stale-data
decision, correlated halt trace, fired stale-feed alert, retained halt, and reconciliation
next action, so nominal-health evidence or a recovered disposition cannot be relabeled as
the incident. The canary proves
both missing-signal and disabled-alert failures. The seventh artifact is
nontrivial Python verifier source.

Every artifact is a single regular filename located directly beside the JSON
companion. Absolute paths, traversal, symlinks, duplicate files, and paths
outside that resolved directory fail closed. The receipt's exact lowercase
`artifact_sha256` map must contain all seven fields and match current bytes. Its
`verifier_source_sha256` must match the verifier artifact. The command may only
place that source immediately after the operating layer's exact
`sys.executable`; Pathway normalizes both interpreter and verifier paths before
execution. Direct/shebang execution, interpreter options before the script,
fake Python executables or symlinks, shell composition, and later decoy tokens
are rejected. Production scope requires a production environment.

Runtime receipts cannot promote authority: the only accepted stage is `NONE`
until a separately verified stage-grant boundary exists, and the verdict remains
`NO_PROMOTE`. Receipts require
canonical `issued_at` and `expires_at` timestamps. Receipts and
artifacts may be at most 24 hours old with at most five minutes of future skew.
Every artifact must also be observed no more than five minutes before the
receipt is issued, and none may postdate issuance, so one receipt cannot combine
unrelated evidence windows. The receipt must remain unexpired and its validity
window cannot exceed 24 hours. Stale, future-dated, temporally incoherent, or
overlong evidence is not creditable.

The positive verifier must emit one unambiguous marker for each runtime gate,
the exact work/recommendation/environment bindings, and the exact
`OBSERVABILITY_RECEIPT_SHA256`. Duplicate, contradictory, missing, or replayed
bindings fail closed. Pathway hashes the evidence, receipt, and every bound
artifact before execution and again after the verifier and mutation canary are
finished. Pathway independently mutates each of the seven bound artifacts twice
in randomized orders, reruns the exact verifier without a shell, restores the
artifact, and persists both the seven-result map and restoration hashes. Every
mutation must make the verifier fail reproducibly and every restoration hash
must equal the pre-run digest. Randomized replay is defense in depth against a
stateful verifier; it is not a verifier identity trust root. Even a structurally
complete receipt stays uncredited while the trusted-verifier set is empty. Any
receipt or artifact change, missing file, unavailable/ignored canary, invalid
evidence template, or digest mismatch denies credit and leaves observability
required. The post-verifier read also reruns all receipt validation at a fresh
clock instant: any new error, expired freshness window, or changed outcome or
credit scope fails the snapshot even when every byte is unchanged. These extra
gates apply only to observability; generic pathway verification retains its
existing behavior.

## Operator Checks

```bash
python3 scripts/operating-layer.py pathway-audit --project /path/to/project --json
python3 scripts/tests/operating_layer_test.py
```

The audit output names the report and HTML artifact paths. Treat the ledger,
proofs, controls, and carry-forward records as the status authority; vault notes
and old reports are context only.
