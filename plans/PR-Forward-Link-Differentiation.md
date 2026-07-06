# PR: Forward-Link Differentiation (Layer 3 base-rate contrast)

## Why this slice exists
Tier 1 (`forward_link.py`, on `main`) produced 143 confirmed forward-links -- earlier PRs
that looked done and were later fixed forward, with their merge-time-observable features. Per
`docs/SESSION_FORENSICS_SPEC.md` bar 2, that is a FAILURE-ONLY sample: no feature can be
claimed to predict fix-forward without a base rate. This slice builds the control and runs the
contrast, so a feature is surfaced only if it is *differentially* present -- not just common
everywhere.

## What it does
`forward_link_differentiate.py` reads the positive set (distinct confirmed `earlier_pr` from
the Tier-1 jsonl), samples a control of merged PRs in the same PR-range that were NOT DETECTED
fixed-forward by Tier 1 (seeded), re-extracts BOTH classes fresh at one corpus pin through the IDENTICAL
`forward_link.merge_time_features` (reused verbatim -- the symmetry is the contrast's
validity), and per feature computes Cliff's delta (effect size) + a seeded permutation test.
A feature `differentiates` iff `|delta| >= 0.33` AND `perm_p < 0.005` (Bonferroni 0.05/10).
Pure-python stats, no new deps.

## Result
**NO DIFFERENTIATING FEATURE DETECTED** -- no merge-time feature separates the classes at the
stated thresholds. This is "not supported under this **detected**-positive sample", NOT a clean
refutation: the control is "not detected fixed-forward" by Tier 1 (search-seeded, not
exhaustive), so undetected positives may leak in and bias toward null. Some features are
statistically significant but below the actionable effect-size bar (near-misses) -- weak, not
gate-worthy. **No CI gate is warranted on this evidence.**

Exact counts, per-feature Cliff's delta / p, the near-miss list, and the corpus pin live in the
generated report `docs/forward-link-differentiation.md` -- the single source of truth. This plan
deliberately does not restate them, so it cannot drift from the run.

## Intentional
- Effect size (Cliff's delta) is the primary gate, not just significance -- large n makes tiny
  effects "significant", so a p-only rule would over-claim. The dual threshold prevents that.
- The control is sampled (seeded) from the in-range pool, not the full pool -- deterministic,
  fast, statistically adequate for a base-rate estimate.

## What must NOT change (and did not)
`forward_link.py` (reused, not modified), the four in-session layers, `test_detect.py`,
`test_forward_link.py`, the Tier-1 jsonl (read-only input), the spec, `requirements.txt`
(no new deps). Atlas is read-only (gh queries).

## Verification
- `python3 forward_link_differentiate.py --dry-run` prints the plan, no execution.
- `pytest test_forward_link_differentiate.py` + the `__main__` runner both pass (count tracks
  the test file -- no hard-coded number to drift); covers the null-result path, adequacy gate,
  fail-loud cap, fail-closed malformed-JSON parse, Cliff's-delta known values, permutation
  determinism, and None-drop.
- Live run reproducible for a fixed `--seed` (seeded control + seeded permutation).
- Raw pairs in gitignored `out-atlas-fwd/forward-links-differentiation.jsonl`; findings in
  `docs/forward-link-differentiation.md`.

## Deferred
LLM narrative synthesis; BUILDING a CI instrument (this slice only draws the conclusion / would
draft a triple if one differentiated); Tier 2 (session -> PR); the same-file-hotfix and
reopened-issue keys.
