# Fast-follow research dossiers

Targeted research on the four open methodology questions surfaced by the world-class audit, each
briefed with what the build already measured so the findings map to a concrete decision. Produced
by independent research agents (web-sourced); citations inline.

---

## 1. Recommendation-quality measurement without a gold set

**Decision it unblocks:** how `pathway-evaluate` earns a defensible precision claim (today: n=3, one
judge, same model family — three stacked failure modes).

**Findings**
- **LLM jury, not one judge** — a panel of 3 *heterogeneous* families (e.g. Claude + GPT + Gemini),
  majority vote, beats a single large judge and cuts self-preference bias. **Correlated (same-family)
  judges collapse the effective vote count** — a jury of one vendor's models is still one judge.
  (Verga et al., *Replacing Judges with Juries / PoLL*, arXiv 2404.18796; *Nine Judges, Two Effective
  Votes*, arXiv 2605.29800.)
- **Validate the judge before trusting it** — hand-label ~20–30 picks; compute Cohen's κ (you vs each
  judge) and Fleiss' κ (across the jury). κ<0.4 = unreliable; κ>0.6 = trustworthy enough to scale.
  (Zheng et al. 2023, arXiv 2306.05685; *Judging the Judges*, arXiv 2604.23178.)
- **Bias controls** — position-swap each comparison and require both-orders agreement; rubric + CoT;
  pin model ID + rubric hash to detect drift. (~2× judge calls.)
- **Interleaving vs a dumb baseline** (random / most-recent) gives ~50× sample-size reduction vs A/B —
  with tiny n you can't claim absolute precision but you *can* claim "beats baseline." (Airbnb, arXiv 2508.00751.)
- Skip off-policy/counterfactual (IPS/DR) until logged action-reward data exists.

**Recommendation:** build a **3-family jury + a 20-pick κ check** before scaling n. "3/3 by one judge" is
a vibe; a κ-validated jury with intervals past n≈30 is a number.

---

## 2. Verifier trust / anti-gaming (`--verify-cmd true` still proves)

**Decision it unblocks:** the trivial-verifier flag — what a real receipt looks like.

**Findings (ranked by fit for a single-file local tool)**
- **in-toto `test-result` predicate** — a signed statement binding the command, stdout/stderr digest,
  pass/fail counts, and the artifact hash. Tiny schema, no infra. (in-toto attestation spec.)
- **Reproducible-builds-style hash binding** — record SHA-256 of the verifier *source*, the target
  artifact, and a normalized stdout transcript. `exit 0` has a recognizable source hash + empty
  transcript — detectable. (reproducible-builds.org; OWASP CICD-SEC-9.)
- **Canary mutant (mutation testing, distilled)** — flip a byte in a changed line and re-run the
  verifier; a real verifier must now fail, a no-op still passes and self-incriminates. The single
  highest-leverage check. (Stryker/PIT pattern; *Mind the Gap*, arXiv 2309.02395.)
- **Coverage-delta + assertion count** — verifier must execute lines inside the diff and emit >0
  assertions; `true` yields zero of both. (SonarQube new-code gate.)
- SLSA provenance: borrow the idea (record builder + invocation + materials), skip the PKI.

**Recommendation:** emit a per-proof **verifier receipt** (<50 LOC): `verifier_source_sha256`
(denylist `true`/`exit 0`/`echo`/empty), `stdout_sha256` + byte floor, `coverage_lines ∩ diff > 0`,
`assertion_count > 0`, and `canary_mutant_failed: bool`. The canary mutant is the keystone check.

---

## 3. Earning autonomy from a success rate at small n

**Decision it unblocks:** the autonomy gate (today a `0.5` point estimate — n=1 at 100% wrongly unlocks).

**Findings** — Wald point estimate is the bug. Clopper-Pearson over-covers (wastes proofs). SPRT needs
two hypotheses (overkill for a static gate). Canary tools (Flagger/Argo) and SRE burn-rate assume high
traffic; their small-n lesson is "**a hard minimum n is non-negotiable**" (rule of three: 0 failures in
9 trials still admits a 33% true failure rate). Wilson and Jeffreys both have good small-n coverage.
(Brown, Cai & DasGupta, PMC2706447.)

**Recommendation (exact, becomes code):** **Wilson score lower bound (z=1.96) ≥ 0.5, hard floor n ≥ 10.**
Unlock math: n=10→k≥9, n=20→k≥15, n=50→k≥32 — proves the rate, not a streak. Closed-form, deterministic,
auditable in one line; keep a Jeffreys cross-check in tests. (Corrected on implementation from an earlier
draft's k≥8/14/31, which were computed at z=1.645 — the one-sided 95% bound — and are off by one at the
z=1.96 specified here; a stdlib Jeffreys cross-check in the suite confirms the z=1.96 thresholds.) Failure modes: non-i.i.d. proofs (dedupe
per task-type), drift after unlock (pair with a sliding window), zero-failure illusion below n=10 (the
floor closes it).

---

## 4. Pathway selection as a bandit — verdict: NO

**Decision it unblocks:** whether to rebuild the scorer on bandit theory or keep tuning a heuristic.

**Findings** — A contextual bandit is **not justified at this data scale.** PAC bounds need ~O(K/ε²·log 1/δ)
≈ thousands of pulls for 11 arms; we have a few closed outcomes — 2–3 orders of magnitude short.
Bandits pay off with informative features + many decisions *per user*; a single operator doesn't
generate that signal. The existing "dampen what's been demonstrated" rule is already a crude
exploration prior. (Jeunen et al., *Practical Bandits*, WSDM 2024, arXiv 2302.01223; Eppo industry note.)

**Recommendation:** **instrument the heuristic, defer the bandit.** Log the score vector + chosen
pathway + outcome on every recommendation; surface a rolling per-pathway win-rate next to the score;
replace the hand-tuned dampening constant with an explicit ε-greedy knob (ε≈0.1–0.2) so exploration is
auditable. Re-evaluate with off-policy estimation after ~100 logged outcomes — only then is a bandit
migration even measurable.

---

## What this changes about the fast-follow

- **Autonomy gate** → implement Wilson LB ≥ 0.5, n ≥ 10 (now an exact spec).
- **Trivial verifier** → verifier receipt + canary mutant (now a concrete mechanism).
- **Evaluation** → 3-family jury + κ-validation before claiming precision (n=3/one-judge is not a claim).
- **Bandit** → **cut from the roadmap**; instrument the heuristic instead. (Research saved us from building the wrong thing.)
