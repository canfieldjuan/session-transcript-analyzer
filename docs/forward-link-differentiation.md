# Forward-Link Differentiation -- Layer 3 (base-rate contrast)

Status: differentiation of the Tier-1 positive class against a control base rate.

Source artifact, local only:
- `out-atlas-fwd/forward-links-differentiation.jsonl`
- positive class from `out-atlas-fwd/forward-links.jsonl` (Tier 1)

Corpus pin (both classes re-extracted fresh at this pin -- no cross-pin confound):
- repo: `canfieldjuan/ATLAS`  query date: `2026-07-06T11:45:37-05:00`
- Atlas `main` HEAD sha: `aad2297d5fa7845e0030949f55607c8f66815ed2`
- seed: `20260706`  control-size: `300`  perm-iters: `10000`
- positive PRs (fixed-forward): 128  |  control PRs (not fixed-forward): 300 (pool 1576, PR-range 118-2002)

## Method

Both classes are merged PRs; the control (merged PRs NOT DETECTED fixed-forward by
Tier 1) is sampled from the SAME PR-range and run through the IDENTICAL
`merge_time_features` extractor. Per feature: Cliff's delta
(effect size) + a seeded permutation test. A feature `differentiates` iff
`|Cliff's delta| >= 0.33` AND `perm_p < 0.005` (Bonferroni 0.05 / 10 features).

## Contrast

| feature | median (pos) | median (ctrl) | Cliff's delta | perm p | differentiates |
|---|---:|---:|---:|---:|:---:|
| additions | 427.5 | 256.0 | 0.2428 | 0.0002 | no |
| deletions | 3.0 | 3.0 | 0.0146 | 0.80792 | no |
| changed_files | 5.0 | 4.0 | 0.1226 | 0.0436 | no |
| test_files_changed | 1.0 | 1.0 | 0.1281 | 0.0241 | no |
| test_lines_changed | 142.0 | 78.0 | 0.1772 | 0.0031 | no |
| scope_files | 5.0 | 4.0 | 0.1226 | 0.0436 | no |
| scope_top_dirs | 3.0 | 3.0 | 0.0271 | 0.65283 | no |
| review_count | 2.0 | 1.0 | 0.1672 | 0.0051 | no |
| review_comment_count | 1.0 | 1.0 | 0.0222 | 0.58134 | no |
| hours_to_merge | 0.5 | 0.3 | 0.2352 | 0.0001 | no |

## Conclusion

**NO DIFFERENTIATING FEATURE DETECTED.** No merge-time feature separates the detected-fixed-forward class from the control at the stated thresholds. This is **not supported under this detected-positive sample** -- NOT a clean refutation: Tier 1 is search-seeded (not exhaustive), so the control ("not detected fixed-forward") may contain undetected positives, which bias the contrast toward null and could mask a real effect. Read this as "no gate-worthy signal found under this sampling", not "proven no signal exists". Do not build a CI gate on these features on this evidence.

### Near-misses (significant but effect-size below the actionable bar)

- `additions`: Cliff's delta 0.2428 (< 0.33), perm p 0.0002. A real but WEAK association -- large n makes a small effect significant, but it is not strong enough to gate on. Revisit with more data.
- `test_lines_changed`: Cliff's delta 0.1772 (< 0.33), perm p 0.0031. A real but WEAK association -- large n makes a small effect significant, but it is not strong enough to gate on. Revisit with more data.
- `hours_to_merge`: Cliff's delta 0.2352 (< 0.33), perm p 0.0001. A real but WEAK association -- large n makes a small effect significant, but it is not strong enough to gate on. Revisit with more data.

## Caveats
- **Control label is detection-limited.** The positive universe is what Tier 1 DETECTED as fixed-forward, and Tier 1 is search-seeded (not exhaustive). The control is therefore "NOT DETECTED fixed-forward", not "never fixed forward" -- it may contain undetected positives, which dilute the contrast toward null. Rebuild/validate the positive universe exhaustively to turn a null into a refutation.
- Multiple comparisons: 10 features tested; the Bonferroni p-threshold (0.005) guards against ~1 chance hit. Differentiators are CANDIDATES, not proven patterns (the spec's "proven" bar needs cited instances).
- Control is a seeded sample of the in-range pool, not the full pool; re-runs with the same seed are identical.
- Features restricted to merge-time-observable (constraint 2, inherited from the reused extractor) -- nothing hindsight.

## Deferred
- LLM narrative synthesis of the contrast.
- BUILDING any CI instrument for a differentiator (this slice only drafts the triple).
- Tier 2 (session -> PR); same-file-hotfix / reopened-issue keys.
