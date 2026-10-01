# The CLI and its own tests

## Inputs

- Working: `operating-layer.py` (the CLI), `development_protocol.py`,
  `verify_obs_contracts_govern.py`, `proof-canary-observability.py`,
  `verify-approval-issue-guard.py`, `install-pathway-approval-authority.sh`,
  `scripts/tests/`.
- Stable reference: `references/pathway-operating-layer.md` (design),
  `references/system-design-proof-gates.md` (per-pathway proof gates).
- Related tool paths (not rooms, registration-named): `commands/pathway.md`,
  `hooks/approval-issue-guard.py`, `security/pathway-approval/`,
  `contracts/observability/`, `skills/karpathy/`.

## Process

1. Edit here, not through the `~/.claude` symlink — the symlink makes changes live
   immediately, but this repo is the canonical source. **Never `git init ~/.claude`.**
2. Stdlib only, in both the CLI and its tests. No third-party deps.
3. The CLI writes only to the central operator-intelligence store and, via
   `ingest-review`, a target project's `.planning/` — never a target repo's source.
4. After any edit: `python3 scripts/tests/operating_layer_test.py`. Preserve the
   `scripts/` ↔ `scripts/tests/` relative layout — the suite resolves the CLI through
   it. The source-integrity guard (no duplicate module-level constant/def names) must
   stay green; never silence it.

## Outputs

- `operating-layer.py --help` runs; `operating_layer_test.py` → `1181/1181 checks passed`
  (or current count) before commit.

## Human check

Alex runs the test suite and reads the diff. Pass: 100% green, no silenced guard. Fail:
fix before commit, never `--no-verify`.
