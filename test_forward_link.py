"""Tests for forward_link.py (Tier 1 PR->PR fix-forward join).

Dual-mode: `python -m pytest test_forward_link.py -q` or `python3 test_forward_link.py`.
Pure logic only -- the gh/git subprocess boundary is stubbed, never hit.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forward_link as fl  # noqa: E402


def _pr_view(**kw):
    base = {
        "number": 1000, "additions": 10, "deletions": 2, "changedFiles": 1,
        "files": [{"path": "a.py", "additions": 5, "deletions": 1}],
        "reviews": [], "comments": [],
        "createdAt": "2026-01-01T00:00:00Z", "mergedAt": "2026-01-01T02:00:00Z",
        "state": "MERGED",
    }
    base.update(kw)
    return base


def _ff_pr(**kw):
    base = {"number": 2004, "title": "fix regression", "body": "fixes #2002"}
    base.update(kw)
    return base


_CORPUS = {"dataset": "out-x", "pin": {"repo": "o/r", "query_date": "d",
                                       "atlas_head_sha": "s", "pr_range": [1, 2]}}


# --- parse_earlier_refs ----------------------------------------------------

def test_parse_earlier_refs_keeps_earlier_drops_self():
    assert fl.parse_earlier_refs(
        "fixes #1993 and #2002, supersedes (#2004)", 2004) == [1993, 2002]


def test_parse_earlier_refs_self_only_is_empty():
    # squash-merge body that only self-references -> no earlier work
    assert fl.parse_earlier_refs("Title (#2004)", 2004) == []


def test_parse_earlier_refs_ignores_later_refs():
    assert fl.parse_earlier_refs("see #3000", 2004) == []  # 3000 > 2004


# --- build_pairs -----------------------------------------------------------

def test_build_pairs_joins_earlier():
    pairs = fl.build_pairs([_ff_pr(number=2004, body="fixes #2002")])
    assert pairs == [{
        "earlier_pr": 2002, "fix_forward_pr": 2004,
        "fix_forward_title": "fix regression",
        "evidence_span": "#2002 referenced in PR #2004 body",
    }]


def test_build_pairs_no_earlier_ref_no_pair():
    # never fabricate a link
    assert fl.build_pairs([_ff_pr(number=2004, body="just a note (#2004)")]) == []


# --- merge_time_features (constraint 2) ------------------------------------

def test_features_are_exactly_the_allowlist():
    assert set(fl.merge_time_features(_pr_view())) == set(fl.MERGE_TIME_FEATURE_KEYS)


def test_features_exclude_post_merge_activity():
    # reviews/comments AFTER mergedAt are hindsight -> excluded
    view = _pr_view(
        mergedAt="2026-01-01T02:00:00Z",
        reviews=[{"submittedAt": "2026-01-01T01:00:00Z"},   # before -> counts
                 {"submittedAt": "2026-01-05T00:00:00Z"}],  # after  -> excluded
        comments=[{"createdAt": "2026-01-01T01:30:00Z"},    # before -> counts
                  {"createdAt": "2026-02-01T00:00:00Z"}],   # after  -> excluded
    )
    feats = fl.merge_time_features(view)
    assert feats["review_count"] == 1
    assert feats["review_comment_count"] == 1


def test_features_fail_closed_on_key_drift():
    # the guard is a real `raise ValueError` (survives python -O), not an assert
    orig = fl.MERGE_TIME_FEATURE_KEYS
    fl.MERGE_TIME_FEATURE_KEYS = orig + ("smuggled_hindsight_field",)
    try:
        raised = False
        try:
            fl.merge_time_features(_pr_view())
        except ValueError:
            raised = True
        assert raised, "guard must raise when allowlist and feats disagree"
    finally:
        fl.MERGE_TIME_FEATURE_KEYS = orig


def test_features_drop_unknown_timestamp_reviews():
    # M1: an unknown-timestamp review could be post-merge -> excluded (fail closed)
    view = _pr_view(reviews=[{"submittedAt": None},
                             {"submittedAt": "2026-01-01T01:00:00Z"}])
    assert fl.merge_time_features(view)["review_count"] == 1


def test_features_fail_closed_on_extra_key():
    # the `extra` branch: a key present in feats but absent from the allowlist
    orig = fl.MERGE_TIME_FEATURE_KEYS
    fl.MERGE_TIME_FEATURE_KEYS = tuple(k for k in orig if k != "hours_to_merge")
    try:
        raised = False
        try:
            fl.merge_time_features(_pr_view())
        except ValueError:
            raised = True
        assert raised, "guard must raise when feats carries an unlisted key"
    finally:
        fl.MERGE_TIME_FEATURE_KEYS = orig


def test_test_path_detection():
    assert fl._is_test_path("test_foo.py")
    assert fl._is_test_path("pkg/tests/bar.py")
    assert fl._is_test_path("web/foo.test.ts")
    assert not fl._is_test_path("pkg/foo.py")


def test_test_delta_counts_test_files_and_lines():
    view = _pr_view(files=[
        {"path": "pkg/foo.py", "additions": 40, "deletions": 4},
        {"path": "pkg/test_foo.py", "additions": 8, "deletions": 1},
    ])
    feats = fl.merge_time_features(view)
    assert feats["test_files_changed"] == 1
    assert feats["test_lines_changed"] == 9
    assert feats["scope_files"] == 2


def test_hours_to_merge():
    feats = fl.merge_time_features(
        _pr_view(createdAt="2026-01-01T00:00:00Z", mergedAt="2026-01-01T06:00:00Z"))
    assert feats["hours_to_merge"] == 6.0


# --- assemble_record -------------------------------------------------------

def test_assemble_confirmed_has_only_merge_time_features():
    rec = fl.assemble_record(
        {"earlier_pr": 2002, "fix_forward_pr": 2004,
         "evidence_span": "#2002 in #2004"}, _CORPUS, _pr_view())
    assert rec["classification"] == "confirmed"
    assert rec["tags"] == ["REPEATED_FIX_LOOP", "CONTRACT_DRIFT"]
    assert set(rec["earlier_pr_merge_time_features"]) == set(fl.MERGE_TIME_FEATURE_KEYS)
    # no hindsight: no feature value is derived from the fix-forward PR number
    assert "2004" not in str(rec["earlier_pr_merge_time_features"])


def test_assemble_cnd_when_not_merged():
    rec = fl.assemble_record(
        {"earlier_pr": 2002, "fix_forward_pr": 2004, "evidence_span": "x"},
        _CORPUS, _pr_view(mergedAt=None, state="OPEN"))
    assert rec["classification"] == "could_not_determine"
    assert "earlier_pr_merge_time_features" not in rec


def test_assemble_cnd_when_ref_not_a_pr():
    rec = fl.assemble_record(
        {"earlier_pr": 50, "fix_forward_pr": 2004, "evidence_span": "x"},
        _CORPUS, None)
    assert rec["classification"] == "could_not_determine"


def test_record_carries_evidence_span():
    rec = fl.assemble_record(
        {"earlier_pr": 2002, "fix_forward_pr": 2004,
         "evidence_span": "#2002 referenced in PR #2004 body"}, _CORPUS, _pr_view())
    assert rec["evidence"][0]["quote_or_summary"] == "#2002 referenced in PR #2004 body"
    assert rec["evidence"][0]["location"] == "PR #2004 body"


# --- gh wrapper parsing (stub the subprocess boundary only) ----------------

def test_key_discovery_parses_stubbed_gh():
    def fake_run(args, timeout=180):
        if "pr" in args and "list" in args:
            # 5 fix-forward PRs -- realistically > the calibration reopened count (3)
            return '[{"number":1},{"number":2},{"number":3},{"number":4},{"number":5}]'
        if "search" in args:
            return "[]"
        return "null"
    orig = fl._run
    fl._run = fake_run
    try:
        keys = fl.key_discovery("o/r")
        assert keys["fix_forward_prs"] == 5
        assert keys["git_reverts"] == 0
        # dominant is measured (max by count): 5 fix-forward > 3 reopened > 0 revert
        assert keys["dominant_key"] == "fix_forward"
    finally:
        fl._run = orig


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
