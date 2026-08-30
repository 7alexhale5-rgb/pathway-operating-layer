---
timestamp: 2026-08-30
work_id: W-20260830-pathway-operating-layer-per-project-observabilit-e65d28
---

# Verification report — research dossier claims

Method: every claim in `2026-08-30-dossier.md` was produced by reading
`scripts/operating-layer.py` (HEAD `e9e0518`) in the authoring session on
2026-08-30 — grep for constant/def locations, then full reads of
`:1486-1685`, `:2010-2299`, `:3224-3333`, `:4480-4520`, `:5140-5165`.
No claim is carried forward from the spec, memory, or any dated document;
where the spec's numbers were repeated (1486-1663, 1872, 2049, 2194) they
were independently re-measured first.

| Claim                                             | How verified                                                                                                                             | Status   |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| 1 spec line refs                                  | grep + read of each cited line                                                                                                           | VERIFIED |
| 2 tradebot-only enums                             | read `:1486-1534`, all members inspected                                                                                                 | VERIFIED |
| 3 fail-closed default                             | read `:1616-1617`, `:3279-3280`, `:5152`                                                                                                 | VERIFIED |
| 4 invariants live in `proof_is_verified`          | read `:3282-3306`                                                                                                                        | VERIFIED |
| 5 extraction surface = 36 constants               | AST parse of the engine, module-level `OBSERVABILITY_*` assignments counted                                                              | VERIFIED |
| 6 inline literals                                 | read `:2088-2089`, `:2122-2128`                                                                                                          | VERIFIED |
| 7 correlation-field pin                           | read `:2068-2069`, `:2200-2202`                                                                                                          | VERIFIED |
| 8 caller binding refuses receipt-supplied context | read `:2231-2237`, `:4505`, `:4877`                                                                                                      | VERIFIED |
| 9 unbound call site                               | read `:2270-2272`                                                                                                                        | VERIFIED |
| 10 suite already has validator fixture            | counted 24 direct calls; read fixture `:4197` + clean-receipt assertion `:4558-4560` (corrected — a truncated first grep wrongly said 0) | VERIFIED |

Executable re-check: `verify_research.py` in this directory re-measures the
load-bearing subset (claims 2, 3, 5, 10) against the engine source via AST
parse and asserts the dossier and receipt agree with the measurement.

Unknowns: 2 warn, 2 info — none blocker. Phase 0 may start.
