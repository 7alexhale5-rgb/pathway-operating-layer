# Data Boundary — proof sufficiency (Gap A)

Verified on real rows (temp store): a proof record (run.proof_id) is created **iff** a verifier
is named (--verified-by / --proof-type), and build_proof_record already requires the evidence file
to exist. Therefore the sufficiency gate is exact and uses existing machinery:

  proved  ⟺  run carries a proof record  AND  the evidence artifact exists on disk

A bare evidence log (no named verifier) records the run but does NOT prove the pathway. No new
table, no schema migration — the proof registry is the boundary.
