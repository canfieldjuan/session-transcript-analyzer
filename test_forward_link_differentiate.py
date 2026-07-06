"""Tests for forward_link_differentiate.py (Layer 3 base-rate contrast).

Dual-mode: `python -m pytest test_forward_link_differentiate.py -q` or
`python3 test_forward_link_differentiate.py`. The gh boundary is stubbed; the
stats are pure and tested directly.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forward_link as fl          # noqa: E402
import forward_link_differentiate as fd  # noqa: E402


def _feat(**kw):
    base = {k: 1 for k in fl.MERGE_TIME_FEATURE_KEYS}
    base.update(kw)
    return base


# --- Cliff's delta ----------------------------------------------------------

def test_cliffs_delta_all_greater_is_plus_one():
    assert fd.cliffs_delta([5, 6, 7], [1, 2, 3]) == 1.0


def test_cliffs_delta_all_less_is_minus_one():
    assert fd.cliffs_delta([1, 2, 3], [5, 6, 7]) == -1.0


def test_cliffs_delta_identical_is_zero():
    assert fd.cliffs_delta([1, 2, 3], [1, 2, 3]) == 0.0


def test_cliffs_delta_empty_is_zero():
    assert fd.cliffs_delta([], [1, 2]) == 0.0
    assert fd.cliffs_delta([1, 2], []) == 0.0


# --- permutation test -------------------------------------------------------

def test_permutation_determinism_same_seed():
    pos, ctrl = [3, 4, 5, 6], [1, 2, 3, 4]
    assert fd.permutation_p(pos, ctrl, seed=7) == fd.permutation_p(pos, ctrl, seed=7)


def test_permutation_low_p_for_separated_groups():
    pos = [100] * 12
    ctrl = [1] * 12
    assert fd.permutation_p(pos, ctrl, seed=1) < fd.PERM_P_MAX


def test_permutation_high_p_for_identical_groups():
    assert fd.permutation_p([1, 2, 3, 4], [1, 2, 3, 4], seed=1) > 0.5


# --- differentiates threshold ----------------------------------------------

def test_differentiates_requires_both_effect_and_significance():
    assert fd.differentiates(0.5, 0.001) is True
    assert fd.differentiates(0.5, 0.01) is False   # p above the Bonferroni bar
    assert fd.differentiates(0.2, 0.001) is False  # effect below CLIFF_DELTA_MIN


# --- contrast: null result + differentiator + None-drop ---------------------

def test_contrast_null_result_when_identical():
    pos = {i: _feat() for i in range(12)}
    ctrl = {i: _feat() for i in range(12, 24)}
    rows = fd.contrast(pos, ctrl, seed=1)
    assert not any(r["differentiates"] for r in rows)  # nothing manufactured


def test_contrast_flags_a_real_differentiator():
    pos = {i: _feat(additions=100) for i in range(12)}
    ctrl = {i: _feat(additions=1) for i in range(12, 24)}
    rows = fd.contrast(pos, ctrl, seed=1)
    add = next(r for r in rows if r["feature"] == "additions")
    assert add["differentiates"] is True
    assert add["cliffs_delta"] == 1.0
    # a feature that is identical in both classes must NOT differentiate
    other = next(r for r in rows if r["feature"] == "deletions")
    assert other["differentiates"] is False


def test_contrast_drops_none_and_counts_it():
    pos = {0: _feat(hours_to_merge=None), 1: _feat(hours_to_merge=2.0)}
    ctrl = {2: _feat(hours_to_merge=3.0)}
    row = next(r for r in fd.contrast(pos, ctrl, seed=1) if r["feature"] == "hours_to_merge")
    assert row["n_pos"] == 1 and row["pos_dropped_none"] == 1


# --- positive-set reader ----------------------------------------------------

def test_read_positive_prs_distinct_confirmed():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "forward-links.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in [
            {"earlier_pr": 100, "classification": "confirmed"},
            {"earlier_pr": 100, "classification": "confirmed"},  # dup -> distinct
            {"earlier_pr": 200, "classification": "confirmed"},
            {"earlier_pr": 300, "classification": "could_not_determine"},  # excluded
        ]) + "\n")
        assert fd.read_positive_prs(p) == [100, 200]


def test_read_positive_prs_missing_file_exits():
    try:
        fd.read_positive_prs(Path("/no/such/forward-links.jsonl"))
        raised = False
    except SystemExit:
        raised = True
    assert raised


# --- control sampler + extractor (stub the gh boundary only) ----------------

def test_sample_control_in_range_excludes_positives_seeded():
    def fake_gh_json(args, timeout=180):
        return [{"number": n} for n in range(100, 200)]
    orig = fl._gh_json
    fl._gh_json = fake_gh_json
    try:
        positive = [110, 120, 130]
        sample, pool = fd.sample_control("o/r", positive, seed=1, control_size=5, merged_limit=1000)
        assert len(sample) == 5
        assert all(110 <= n <= 130 for n in sample)     # in the positive range
        assert not (set(sample) & set(positive))         # excludes positives
        again, _ = fd.sample_control("o/r", positive, seed=1, control_size=5, merged_limit=1000)
        assert sample == again                            # seeded -> deterministic
    finally:
        fl._gh_json = orig


def test_extract_features_reuses_extractor_skips_unmerged():
    def fake_view(repo, n):
        if n % 2 == 0:
            return {"number": n, "additions": 5, "deletions": 1, "changedFiles": 1,
                    "files": [{"path": "a.py", "additions": 5, "deletions": 1}],
                    "reviews": [], "comments": [],
                    "createdAt": "2026-01-01T00:00:00Z",
                    "mergedAt": "2026-01-01T01:00:00Z", "state": "MERGED"}
        return {"number": n, "mergedAt": None, "state": "OPEN"}  # unmerged -> skip
    orig = fl.fetch_pr_view
    fl.fetch_pr_view = fake_view
    try:
        feats = fd.extract_features("o/r", [2, 3, 4])
        assert set(feats) == {2, 4}                       # odd (unmerged) skipped
        assert set(feats[2]) == set(fl.MERGE_TIME_FEATURE_KEYS)  # identical extractor
    finally:
        fl.fetch_pr_view = orig


# --- triple draft -----------------------------------------------------------

def test_draft_triple_shape():
    row = {"feature": "hours_to_merge", "cliffs_delta": -0.5, "perm_p": 0.001,
           "median_pos": 0.2, "median_ctrl": 12.0, "n_pos": 100, "n_ctrl": 200}
    t = fd.draft_triple(row)
    assert t["feature"] == "hours_to_merge"
    assert "lower" in t["condition"]           # negative delta -> "lower"
    assert t["behavior"] and t["instrument"]
    assert t["confidence"].startswith("candidate")


def test_sample_control_fails_loud_on_cap():
    # MAJOR-1: hitting the merged-limit means the pool may be recency-truncated -> fail loud
    def fake_gh_json(args, timeout=180):
        return [{"number": n} for n in range(1000, 1010)]  # exactly hits merged_limit=10
    orig = fl._gh_json
    fl._gh_json = fake_gh_json
    try:
        raised = False
        try:
            fd.sample_control("o/r", [1001, 1002], seed=1, control_size=3, merged_limit=10)
        except SystemExit:
            raised = True
        assert raised, "must fail loud when the merged-PR cap is hit"
    finally:
        fl._gh_json = orig


def test_read_positive_prs_no_confirmed_exits():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "forward-links.jsonl"
        p.write_text(json.dumps({"earlier_pr": 5, "classification": "could_not_determine"}) + "\n")
        try:
            fd.read_positive_prs(p)
            raised = False
        except SystemExit:
            raised = True
        assert raised


def test_read_positive_prs_fails_closed_on_malformed_json():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "forward-links.jsonl"
        p.write_text('{"earlier_pr": 100, "classification": "confirmed"}\n{ bad json\n')
        try:
            fd.read_positive_prs(p)
            raised = False
        except SystemExit:
            raised = True
        assert raised, "malformed evidence must fail closed, not silently shrink the set"


def test_render_doc_gates_null_on_adequacy():
    # MAJOR-2: an under-powered run must say "could not determine", not "refuted"
    rows = [{"feature": k, "n_pos": 3, "n_ctrl": 3, "median_pos": 1, "median_ctrl": 1,
             "cliffs_delta": 0.0, "perm_p": 1.0, "significant": False,
             "differentiates": False} for k in fl.MERGE_TIME_FEATURE_KEYS]
    base = {"dataset": "out-x", "corpus": {"repo": "o/r", "query_date": "d",
            "atlas_head_sha": "s", "pr_range": [1, 2]}, "seed": 1, "control_size": 3,
            "n_positive": 3, "n_control": 3, "control_pool": 3, "differentiators": []}
    assert "COULD NOT DETERMINE" in fd.render_doc({**base, "adequate": False}, rows, [])
    powered = fd.render_doc({**base, "adequate": True}, rows, [])
    assert "NO DIFFERENTIATING FEATURE DETECTED" in powered  # not a "refutation"
    assert "not supported under this detected-positive sample" in powered


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
