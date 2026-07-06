# Forward-Link Differentiation -- Layer 3 (base-rate contrast)

Status: differentiation of the Tier-1 positive class against a control base rate.

Source artifact, local only:
- `out-atlas-fwd/forward-links-differentiation.jsonl`
- positive class from `out-atlas-fwd/forward-links.jsonl` (Tier 1)

Corpus pin (both classes extracted at this pin; the Tier-1 positive membership is validated to share it -- no cross-pin confound):
- repo: `canfieldjuan/ATLAS`  query date: `2026-07-06T12:41:20-05:00`
- Atlas `main` HEAD sha: `aad2297d5fa7845e0030949f55607c8f66815ed2`
- seed: `20260706`  control-size: `300`  perm-iters: `10000`
- positive PRs (detected fixed-forward): 127  |  control PRs (NOT detected fixed-forward): 300 (pool 1577, PR-range 118-2002)

## Method

Both classes are merged PRs; the control (merged PRs NOT DETECTED fixed-forward by
Tier 1) is sampled from the SAME PR-range and run through the IDENTICAL
`merge_time_features` extractor. Per feature: Cliff's delta
(effect size) + a seeded permutation test. A feature `differentiates` iff
`|Cliff's delta| >= 0.33` AND `perm_p < 0.005` (Bonferroni 0.05 / 10 features).

## Contrast

| feature | median (pos) | median (ctrl) | Cliff's delta | perm p | differentiates |
|---|---:|---:|---:|---:|:---:|
| additions | 435 | 232.0 | 0.2885 | 0.0001 | no |
| deletions | 3 | 4.0 | -0.0065 | 0.91571 | no |
| changed_files | 5 | 4.0 | 0.1259 | 0.0376 | no |
| test_files_changed | 1 | 1.0 | 0.1333 | 0.0192 | no |
| test_lines_changed | 141 | 74.0 | 0.2194 | 0.0005 | no |
| scope_files | 5 | 4.0 | 0.1259 | 0.0376 | no |
| scope_top_dirs | 3 | 3.0 | 0.0912 | 0.12509 | no |
| review_count | 2 | 1.0 | 0.2043 | 0.0012 | no |
| review_comment_count | 1 | 1.0 | 0.018 | 0.65553 | no |
| hours_to_merge | 0.5 | 0.2 | 0.2803 | 0.0001 | no |

## Conclusion

**NO DIFFERENTIATING FEATURE DETECTED.** No merge-time feature separates the detected-fixed-forward class from the control at the stated thresholds. This is **not supported under this detected-positive sample** -- NOT a clean refutation: Tier 1 is search-seeded (not exhaustive), so the control ("not detected fixed-forward") may contain undetected positives, which bias the contrast toward null and could mask a real effect. Read this as "no gate-worthy signal found under this sampling", not "proven no signal exists". Do not build a CI gate on these features on this evidence.

### Near-misses (significant but effect-size below the actionable bar)

- `additions`: Cliff's delta 0.2885 (< 0.33), perm p 0.0001. A real but WEAK association -- large n makes a small effect significant, but it is not strong enough to gate on. Revisit with more data.
- `test_lines_changed`: Cliff's delta 0.2194 (< 0.33), perm p 0.0005. A real but WEAK association -- large n makes a small effect significant, but it is not strong enough to gate on. Revisit with more data.
- `review_count`: Cliff's delta 0.2043 (< 0.33), perm p 0.0012. A real but WEAK association -- large n makes a small effect significant, but it is not strong enough to gate on. Revisit with more data.
- `hours_to_merge`: Cliff's delta 0.2803 (< 0.33), perm p 0.0001. A real but WEAK association -- large n makes a small effect significant, but it is not strong enough to gate on. Revisit with more data.

## Caveats
- **Control label is detection-limited.** The positive universe is what Tier 1 DETECTED as fixed-forward, and Tier 1 is search-seeded (not exhaustive). The control is therefore "NOT DETECTED fixed-forward", not "never fixed forward" -- it may contain undetected positives, which dilute the contrast toward null. Rebuild/validate the positive universe exhaustively to turn a null into a refutation.
- Multiple comparisons: 10 features tested; the Bonferroni p-threshold (0.005) guards against ~1 chance hit. Differentiators are CANDIDATES, not proven patterns (the spec's "proven" bar needs cited instances).
- Control is a seeded sample of the in-range pool, not the full pool; re-runs with the same seed are identical.
- Features restricted to merge-time-observable (constraint 2, inherited from the reused extractor) -- nothing hindsight.

## Deferred
- LLM narrative synthesis of the contrast.
- BUILDING any CI instrument for a differentiator (this slice only drafts the triple).
- Tier 2 (session -> PR); same-file-hotfix / reopened-issue keys.
