# Top-level integrity tests

## Inputs

- `test_measurement_staleness.py`.
- Stable reference: `references/pathway-operating-layer.md`.

## Process

1. Distinct from `scripts/tests/` (which tests the CLI itself): this suite checks
   cross-cutting integrity properties like measurement staleness.
2. Run directly: `python3 tests/test_measurement_staleness.py`, or via the project's
   test runner if one wraps it.

## Outputs

- A green run before any change to how the CLI measures or dates its output.

## Human check

Alex treats a red run here as a stop-ship signal for anything touching measurement
freshness. Pass: green. Fail: fix before commit.
