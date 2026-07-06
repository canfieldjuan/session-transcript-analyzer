#!/usr/bin/env python3
"""
forward_link_differentiate.py -- Layer 3: base-rate differentiation.

Tier 1 (forward_link.py) produced the POSITIVE class: earlier PRs that looked
done and were later fixed forward, with their merge-time-observable features.
Per SESSION_FORENSICS_SPEC.md bar 2, that is a FAILURE-ONLY sample -- a feature
that correlates with "got fixed forward" may be just as present in PRs never
fixed forward. This module builds a CONTROL (merged PRs NOT DETECTED as
fixed-forward by Tier 1 -- which is search-seeded, NOT exhaustive -- same
PR-range, same extractor) and contrasts per feature. A "no differentiating
feature" result is "not supported under this detected-positive sample", NOT a
clean refutation: undetected positives in the control bias the contrast toward
null and could mask a real effect.

Extraction reuses forward_link.merge_time_features + fetch_pr_view VERBATIM --
identical extraction for both classes is the validity of the contrast. Both
classes are re-extracted fresh at one corpus pin (no cross-pin confound when the
pin validation passes; a stale pin overridden by --allow-stale-pin carries it).

Stats are pure-python (no scipy): Cliff's delta via ranks (fast) + a seeded
permutation test on it.

Usage:
  python3 forward_link_differentiate.py [--repo owner/name] [--out-dir out-atlas-fwd]
      [--control-size N] [--seed S] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime
import json
import random
import statistics
from pathlib import Path

import forward_link as fl

# effect-size + significance thresholds (documented constants).
CLIFF_DELTA_MIN = 0.33   # medium-or-larger effect size
PERM_P_MAX = 0.005       # Bonferroni: 0.05 / 10 features
PERM_ITERS = 10000
DEFAULT_CONTROL_SIZE = 300
DEFAULT_SEED = 20260706
DEFAULT_MERGED_LIMIT = 5000  # headroom over the merged-PR count; fail loud if hit
MIN_SAMPLE = 30              # below this per class, a null is under-powered


# --- pure stats (unit-testable, no network) --------------------------------

def _avg_ranks(values: list[float]) -> list[float]:
    """1-based average ranks, ties share the mean of their positions."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1  # mean of ranks (i+1)..(j+1)
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _delta_from_ranksum(rank_sum_pos: float, n: int, m: int) -> float:
    u = rank_sum_pos - n * (n + 1) / 2      # Mann-Whitney U for the pos group
    return 2 * u / (n * m) - 1              # Cliff's delta in [-1, 1]


def cliffs_delta(pos: list[float], ctrl: list[float]) -> float:
    """Cliff's delta effect size in [-1, 1] via ranks: +1 iff every pos > every
    ctrl, 0 iff no stochastic dominance, -1 iff every pos < every ctrl."""
    n, m = len(pos), len(ctrl)
    if n == 0 or m == 0:
        return 0.0
    ranks = _avg_ranks(list(pos) + list(ctrl))
    return _delta_from_ranksum(sum(ranks[:n]), n, m)


def permutation_p(pos: list[float], ctrl: list[float], seed: int,
                  iters: int = PERM_ITERS) -> float:
    """Seeded two-sided permutation test on |Cliff's delta|. Shuffles the pooled
    ranks and recomputes; p = (#{|delta_perm| >= |delta_obs|} + 1) / (iters + 1).
    Add-one so p is never reported as 0. Reproducible for a fixed seed."""
    n, m = len(pos), len(ctrl)
    if n == 0 or m == 0:
        return 1.0
    ranks = _avg_ranks(list(pos) + list(ctrl))
    obs = abs(_delta_from_ranksum(sum(ranks[:n]), n, m))
    rng = random.Random(seed)
    hits = 0
    for _ in range(iters):
        rng.shuffle(ranks)
        if abs(_delta_from_ranksum(sum(ranks[:n]), n, m)) >= obs:
            hits += 1
    return (hits + 1) / (iters + 1)


def differentiates(delta: float, p: float) -> bool:
    return abs(delta) >= CLIFF_DELTA_MIN and p < PERM_P_MAX


# --- positive set + control (gh boundary is isolated in forward_link) -------

def read_positive_prs(jsonl_path: Path) -> tuple[list[int], dict]:
    """Distinct earlier_pr on `confirmed` records = the fixed-forward set, plus the
    Tier-1 corpus pin so the caller can reject a stale artifact."""
    if not jsonl_path.exists():
        raise SystemExit(
            f"{jsonl_path} not found -- run forward_link.py first (Tier 1).")
    pos: set[int] = set()
    pin: dict = {}
    for i, line in enumerate(jsonl_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError as e:
            # fail closed: a partially-readable evidence artifact must halt, not
            # silently shrink the positive set into a clean-looking null.
            raise SystemExit(f"{jsonl_path}:{i} malformed JSON in the Tier-1 artifact "
                             f"({e}); refusing to run on partial evidence.")
        if not pin and isinstance(r.get("corpus"), dict):
            pin = r["corpus"]
        if r.get("classification") == "confirmed" and r.get("earlier_pr") is not None:
            pos.add(r["earlier_pr"])
    if not pos:
        raise SystemExit("no confirmed forward-links in the Tier-1 artifact.")
    return sorted(pos), pin


def sample_control(repo: str, positive: list[int], seed: int,
                   control_size: int, merged_limit: int) -> tuple[list[int], int]:
    """Seeded sample of merged PRs in the positive PR-range, excluding positives.
    Returns (sampled_numbers, pool_size)."""
    lo, hi = min(positive), max(positive)
    merged = fl._gh_json(["gh", "pr", "list", "--repo", repo, "--state", "merged",
                          "--json", "number", "--limit", str(merged_limit)]) or []
    if len(merged) >= merged_limit:
        # gh returns the most-recent N; hitting the cap means older in-range PRs may be
        # silently dropped -> a recency-biased control. Fail loud (no silent truncation).
        raise SystemExit(
            f"merged-PR cap hit ({len(merged)} >= --merged-limit {merged_limit}); the control "
            "pool may be recency-truncated. Raise --merged-limit above the repo's total merged "
            "count.")
    posset = set(positive)
    pool = sorted(p["number"] for p in merged
                  if lo <= p["number"] <= hi and p["number"] not in posset)
    rng = random.Random(seed)
    k = min(control_size, len(pool))
    return sorted(rng.sample(pool, k)), len(pool)


def extract_features(repo: str, pr_numbers: list[int]) -> tuple[dict[int, dict], list[int]]:
    """Reuse forward_link's extractor VERBATIM (identical extraction is the contrast's
    validity). Inputs are KNOWN-merged PRs (Tier-1 confirmed positives / gh --state merged
    controls), so a None/unmerged view is an UNEXPECTED fetch failure, not a legitimate
    skip -- return it as attrition for the caller to fail loud on (no silent bias)."""
    out: dict[int, dict] = {}
    dropped: list[int] = []
    for n in pr_numbers:
        v = fl.fetch_pr_view(repo, n)
        if v is None or not v.get("mergedAt"):
            dropped.append(n)
            continue
        out[n] = fl.merge_time_features(v)
    return out, dropped


# --- contrast + triple draft ------------------------------------------------

def contrast(pos_feats: dict, ctrl_feats: dict, seed: int, adequate: bool) -> list[dict]:
    """Per-feature Cliff's delta + permutation p + differentiates verdict.

    `differentiates` is the SINGLE SOURCE of the differentiator claim: it requires ALL
    preconditions -- an adequate sample AND effect size AND significance. A feature cannot
    'differentiate' on an under-powered sample, so `adequate` gates it HERE, at the row.
    Everything downstream (the JSONL rows, the rendered table, meta['differentiators'], the
    triples, null_result) derives from this one gated field, so they can never disagree."""
    rows = []
    for key in fl.MERGE_TIME_FEATURE_KEYS:
        pos = [f[key] for f in pos_feats.values() if f.get(key) is not None]
        ctrl = [f[key] for f in ctrl_feats.values() if f.get(key) is not None]
        delta = cliffs_delta(pos, ctrl)
        # same seed per feature: each per-feature test is independently valid; the draws are
        # merely correlated across features, which is fine under the Bonferroni threshold.
        p = permutation_p(pos, ctrl, seed)
        rows.append({
            "feature": key,
            "n_pos": len(pos), "n_ctrl": len(ctrl),
            "pos_dropped_none": len(pos_feats) - len(pos),
            "ctrl_dropped_none": len(ctrl_feats) - len(ctrl),
            "median_pos": statistics.median(pos) if pos else None,
            "median_ctrl": statistics.median(ctrl) if ctrl else None,
            "cliffs_delta": round(delta, 4),
            "perm_p": round(p, 5),
            "significant": p < PERM_P_MAX,   # raw-p significance (near-miss uses this)
            "differentiates": adequate and differentiates(delta, p),
        })
    return rows


def draft_triple(row: dict) -> dict:
    """Draft a routed (condition -> behavior -> instrument) triple for a
    differentiating feature. Candidate only -- see the multiple-comparison caveat."""
    direction = "lower" if row["cliffs_delta"] < 0 else "higher"
    return {
        "feature": row["feature"],
        "condition": (f"earlier PR merges with {direction} {row['feature']} "
                      f"(median {row['median_pos']} vs control {row['median_ctrl']})"),
        "behavior": "was later fixed forward by another PR",
        "instrument": "CI gate -- merge-time mechanical signature (spec routing table)",
        "evidence": {"cliffs_delta": row["cliffs_delta"], "perm_p": row["perm_p"],
                     "n_pos": row["n_pos"], "n_ctrl": row["n_ctrl"]},
        "confidence": "candidate (exploratory; multiple-comparison caveat applies)",
    }


# --- writers ----------------------------------------------------------------

def write_jsonl(path: Path, rows: list[dict], meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write(json.dumps({"record": "meta", **meta}, ensure_ascii=True) + "\n")
        for r in rows:
            f.write(json.dumps({"record": "feature", **r}, ensure_ascii=True) + "\n")
        f.flush()


def render_doc(meta: dict, rows: list[dict], triples: list[dict]) -> str:
    pin = meta["corpus"]
    diff = [r for r in rows if r["differentiates"]]
    # the pin/confound claim is DERIVED from meta["stale_pin"] -- it must never assert
    # "validated / no confound" when the run overrode a stale pin.
    if meta.get("stale_pin"):
        pin_line = ("Corpus pin -- WARNING: STALE (`--allow-stale-pin`). The Tier-1 positive "
                    f"membership is pinned to `{str(meta.get('tier1_pin_head'))[:9]}` while the "
                    "control is from this run's head -- a CROSS-PIN CONFOUND IS PRESENT "
                    "(positives fixed-forward since Tier 1 may leak into the control):")
    else:
        pin_line = ("Corpus pin (both classes extracted at this pin; the Tier-1 positive "
                    "membership is validated to share it -- no cross-pin confound):")
    lines = [
        "# Forward-Link Differentiation -- Layer 3 (base-rate contrast)",
        "",
        "Status: differentiation of the Tier-1 positive class against a control base rate.",
        "",
        "Source artifact, local only:",
        f"- `{meta['dataset']}/forward-links-differentiation.jsonl`",
        f"- positive class from `{meta['dataset']}/forward-links.jsonl` (Tier 1)",
        "",
        pin_line,
        f"- repo: `{pin['repo']}`  query date: `{pin['query_date']}`",
        f"- Atlas `main` HEAD sha: `{pin['atlas_head_sha']}`",
        f"- seed: `{meta['seed']}`  control-size: `{meta['control_size']}`  "
        f"perm-iters: `{PERM_ITERS}`",
        f"- positive PRs (detected fixed-forward): {meta['n_positive']}  |  "
        f"control PRs (NOT detected fixed-forward): {meta['n_control']} "
        f"(pool {meta['control_pool']}, PR-range {pin['pr_range'][0]}-{pin['pr_range'][1]})",
        "",
        "## Method",
        "",
        "Both classes are merged PRs; the control (merged PRs NOT DETECTED fixed-forward by",
        "Tier 1) is sampled from the SAME PR-range and run through the IDENTICAL",
        "`merge_time_features` extractor. Per feature: Cliff's delta",
        f"(effect size) + a seeded permutation test. A feature `differentiates` iff",
        f"`|Cliff's delta| >= {CLIFF_DELTA_MIN}` AND `perm_p < {PERM_P_MAX}` "
        f"(Bonferroni 0.05 / {len(fl.MERGE_TIME_FEATURE_KEYS)} features).",
        "",
        "## Contrast",
        "",
        "| feature | median (pos) | median (ctrl) | Cliff's delta | perm p | differentiates |",
        "|---|---:|---:|---:|---:|:---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['feature']} | {r['median_pos']} | {r['median_ctrl']} | "
            f"{r['cliffs_delta']} | {r['perm_p']} | "
            f"{'YES' if r['differentiates'] else 'no'} |"
        )
    adequate = meta.get("adequate", True)
    lines += ["", "## Conclusion", ""]
    if not adequate:
        lines.append(f"**COULD NOT DETERMINE -- insufficient sample** "
                     f"(n_positive={meta['n_positive']}, n_control={meta['n_control']}; need "
                     f">= {MIN_SAMPLE} each). The contrast is under-powered; a null here is NOT "
                     "a refutation. Do not draw a go/no-go from this run.")
    elif diff:
        lines.append(f"{len(diff)} feature(s) differentiate the fixed-forward class from the "
                     "base rate. Drafted routed triples (candidates):")
        lines.append("")
        for t in triples:
            lines.append(f"- **{t['feature']}**: {t['condition']} -> {t['behavior']} "
                         f"-> {t['instrument']} "
                         f"(delta {t['evidence']['cliffs_delta']}, p {t['evidence']['perm_p']}).")
    else:
        lines.append("**NO DIFFERENTIATING FEATURE DETECTED.** No merge-time feature separates "
                     "the detected-fixed-forward class from the control at the stated thresholds. "
                     "This is **not supported under this detected-positive sample** -- NOT a clean "
                     "refutation: Tier 1 is search-seeded (not exhaustive), so the control "
                     "(\"not detected fixed-forward\") may contain undetected positives, which "
                     "bias the contrast toward null and could mask a real effect. Read this as "
                     "\"no gate-worthy signal found under this sampling\", not \"proven no signal "
                     "exists\". Do not build a CI gate on these features on this evidence.")
    near = [r for r in rows if r.get("significant") and abs(r["cliffs_delta"]) < CLIFF_DELTA_MIN]
    if adequate and near:
        lines += ["", "### Near-misses (significant but effect-size below the actionable bar)", ""]
        for r in near:
            lines.append(
                f"- `{r['feature']}`: Cliff's delta {r['cliffs_delta']} (< {CLIFF_DELTA_MIN}), "
                f"perm p {r['perm_p']}. A real but WEAK association -- large n makes a small "
                "effect significant, but it is not strong enough to gate on. Revisit with more data.")
    lines += [
        "",
        "## Caveats",
        "- **Control label is detection-limited.** The positive universe is what Tier 1 "
        "DETECTED as fixed-forward, and Tier 1 is search-seeded (not exhaustive). The control is "
        "therefore \"NOT DETECTED fixed-forward\", not \"never fixed forward\" -- it may contain "
        "undetected positives, which dilute the contrast toward null. Rebuild/validate the "
        "positive universe exhaustively to turn a null into a refutation.",
        f"- Multiple comparisons: {len(fl.MERGE_TIME_FEATURE_KEYS)} features tested; the "
        f"Bonferroni p-threshold ({PERM_P_MAX}) guards against ~1 chance hit. Differentiators "
        "are CANDIDATES, not proven patterns (the spec's \"proven\" bar needs cited instances).",
        "- Control is a seeded sample of the in-range pool, not the full pool; re-runs with the "
        "same seed are identical.",
        "- Features restricted to merge-time-observable (constraint 2, inherited from the reused "
        "extractor) -- nothing hindsight.",
        "",
        "## Deferred",
        "- LLM narrative synthesis of the contrast.",
        "- BUILDING any CI instrument for a differentiator (this slice only drafts the triple).",
        "- Tier 2 (session -> PR); same-file-hotfix / reopened-issue keys.",
    ]
    return "\n".join(lines) + "\n"


# --- fail-closed guards (factored out of main so the FIRE condition is testable) ------

def check_pin(tier1_pin: dict, repo: str, head: str, allow_stale: bool) -> bool:
    """Return whether the Tier-1 pin is stale vs (repo, head). Raise SystemExit if stale and
    not allowed -- the cross-pin-membership guard, factored out of main() so the FIRE
    condition is unit-testable (not merely that a helper returns a pin)."""
    stale = (tier1_pin.get("repo") != repo
             or tier1_pin.get("atlas_head_sha") != head)
    if stale and not allow_stale:
        raise SystemExit(
            f"Tier-1 artifact pinned to {tier1_pin.get('repo')}@"
            f"{str(tier1_pin.get('atlas_head_sha'))[:9]}, but this run is {repo}@{head[:9]}. "
            "Positive membership and control would be from different corpus states (stale "
            "positives leak into control). Re-run forward_link.py so both share one pin, or "
            "pass --allow-stale-pin to proceed with the confound recorded.")
    return stale


def require_complete(pos_dropped: list, ctrl_dropped: list) -> None:
    """Raise SystemExit if any KNOWN-merged PR failed to re-fetch (positives are Tier-1
    confirmed, controls are gh --state merged, so a drop is a gh error, not a skip).
    Factored out of main() so the FIRE condition is unit-testable."""
    if pos_dropped or ctrl_dropped:
        raise SystemExit(
            f"re-fetch failed for known-merged PRs (positives={pos_dropped}, "
            f"controls={ctrl_dropped}); a drop here is a gh error, not a skip. Retry.")


# --- main -------------------------------------------------------------------

def _dry_run(repo, out_dir, control_size, seed, merged_limit):
    print("DRY RUN -- forward_link_differentiate.py Layer 3 (no execution)")
    print(f"  repo (read-only): {repo} | out-dir: {out_dir} (gitignored jsonl)")
    print(f"  control-size: {control_size} | seed: {seed} | perm-iters: {PERM_ITERS} | "
          f"merged-limit: {merged_limit} | MIN_SAMPLE: {MIN_SAMPLE}")
    print("  steps:")
    print(f"    1. read confirmed earlier_pr + corpus pin from {out_dir}/forward-links.jsonl")
    print("    2. check_pin: Tier-1 pin == current head (SystemExit on stale unless --allow-stale-pin)")
    print(f"    3. gh pr list --repo {repo} --state merged --json number --limit {merged_limit} "
          "(SystemExit if the cap is hit)")
    print("       -> seeded control sample in the positive range, excluding positives")
    print("    4. gh pr view <n> for positive + control; require_complete -> SystemExit on any drop")
    print("    5. per feature: Cliff's delta + seeded permutation test -> differentiates?")
    print(f"    6. write {out_dir}/forward-links-differentiation.jsonl + "
          "docs/forward-link-differentiation.md")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=fl.REPO_DEFAULT)
    ap.add_argument("--out-dir", default="out-atlas-fwd")
    ap.add_argument("--control-size", type=int, default=DEFAULT_CONTROL_SIZE)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--merged-limit", type=int, default=DEFAULT_MERGED_LIMIT,
                    help="max merged PRs to fetch; fail loud if hit (recency-truncation guard)")
    ap.add_argument("--allow-stale-pin", action="store_true",
                    help="proceed even if the Tier-1 pin != current Atlas head (records the confound)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        _dry_run(args.repo, args.out_dir, args.control_size, args.seed, args.merged_limit)
        return

    out_dir = Path(args.out_dir)
    positive, tier1_pin = read_positive_prs(out_dir / "forward-links.jsonl")

    query_date = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    head_sha = fl.gh_head_sha(args.repo)
    stale = check_pin(tier1_pin, args.repo, head_sha, args.allow_stale_pin)

    control, pool = sample_control(args.repo, positive, args.seed, args.control_size,
                                   args.merged_limit)
    pos_feats, pos_dropped = extract_features(args.repo, positive)
    ctrl_feats, ctrl_dropped = extract_features(args.repo, control)
    require_complete(pos_dropped, ctrl_dropped)

    adequate = len(pos_feats) >= MIN_SAMPLE and len(ctrl_feats) >= MIN_SAMPLE
    rows = contrast(pos_feats, ctrl_feats, args.seed, adequate)
    triples = [draft_triple(r) for r in rows if r["differentiates"]]

    meta = {
        "dataset": args.out_dir,
        "corpus": {"repo": args.repo, "query_date": query_date,
                   "atlas_head_sha": head_sha,
                   "pr_range": [min(positive), max(positive)]},
        "seed": args.seed, "control_size": args.control_size, "min_sample": MIN_SAMPLE,
        "n_positive": len(pos_feats), "n_control": len(ctrl_feats),
        "control_pool": pool, "adequate": adequate,
        "tier1_pin_head": tier1_pin.get("atlas_head_sha"), "stale_pin": stale,
        "positive_universe": "tier1-detected (search-seeded, not exhaustive)",
        "control_label": "not detected fixed-forward (may contain undetected positives)",
        "differentiators": [r["feature"] for r in rows if r["differentiates"]],
        "null_result": adequate and not any(r["differentiates"] for r in rows),
    }

    write_jsonl(out_dir / "forward-links-differentiation.jsonl", rows, meta)
    Path("docs/forward-link-differentiation.md").write_text(
        render_doc(meta, rows, triples), encoding="utf-8")

    print(f"differentiation: {len(pos_feats)} positive vs {len(ctrl_feats)} control")
    if not adequate:
        print(f"  COULD NOT DETERMINE -- insufficient sample (need >= {MIN_SAMPLE} each)")
    elif meta["null_result"]:
        print("  NO DIFFERENTIATING FEATURE DETECTED -- not supported under this "
              "detected-positive sample (not a clean refutation; see caveats)")
    else:
        print(f"  differentiators: {meta['differentiators']}")
    print(f"  wrote {out_dir}/forward-links-differentiation.jsonl (gitignored) + "
          "docs/forward-link-differentiation.md")


if __name__ == "__main__":
    main()
