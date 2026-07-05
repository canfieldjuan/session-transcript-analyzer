"""Regression tests for the parse/detect truncation + precision fixes.

Run: python -m pytest test_detect.py -q   (or: python test_detect.py)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze  # noqa: E402
import detect  # noqa: E402
import parse  # noqa: E402


def _call(**kw):
    base = {"name": "Bash", "input_summary": "", "raw_input": {},
            "result_status": "ok", "result_lines": 1, "result_bytes": 1,
            "result_tail": "", "result_has_verify": False, "result_verify_match": ""}
    base.update(kw)
    return base


def _ep(**kw):
    base = {"index": 5, "user_text": "some directive here", "assistant_text": "",
            "tool_calls": [], "tool_count": 0, "user_tokens_est": 50}
    base.update(kw)
    base["tool_count"] = base.get("tool_count") or len(base["tool_calls"])
    return base


# --- the truncation regression (the bug this whole change fixed) -----------

def test_verify_signal_survives_tail_truncation():
    """A CLEAN early in a long output must be seen by the FULL-text check even
    though the last-3-line tail (what parse.py keeps) does not contain it."""
    full = "mergeStateStatus CLEAN\n" + "\n".join(f"line{i}" for i in range(10))
    tail_3 = "\n".join(full.splitlines()[-3:])
    assert parse.VERIFY_SIGNAL_RE.search(full)      # full text -> verified
    assert not parse.VERIFY_SIGNAL_RE.search(tail_3)  # tail alone -> would miss it


def test_no_verification_skipped_when_tool_verified_via_boolean():
    ep = _ep(
        assistant_text="all done, CI is green and merge state CLEAN",
        tool_calls=[_call(result_has_verify=True, result_verify_match="CLEAN",
                          result_tail="unresolved: 0")],  # tail lacks the proof
    )
    assert "no_verification" not in detect.detect(ep)


def test_no_verification_flagged_when_no_tool_proof():
    ep = _ep(
        assistant_text="all done, fixed it",
        tool_calls=[_call(result_has_verify=False, result_tail="some plain output")],
    )
    assert "no_verification" in detect.detect(ep)


def test_prose_alone_is_not_proof():
    """Assistant narration claiming success must NOT suppress the flag -- the
    original bug Codex caught."""
    ep = _ep(
        assistant_text="tests passed, all green, verified -- done",  # prose says so
        tool_calls=[_call(result_has_verify=False, result_tail="no verify signal")],
    )
    assert "no_verification" in detect.detect(ep)


# --- precision guards -------------------------------------------------------

def test_worktree_remove_force_not_flagged():
    ep = _ep(tool_calls=[_call(input_summary="git worktree remove wt/x --force")])
    assert "bypassed_safety_or_destructive" not in detect.detect(ep)


def test_real_force_push_is_flagged():
    ep = _ep(tool_calls=[_call(input_summary="git push --force origin main")])
    assert "bypassed_safety_or_destructive" in detect.detect(ep)


def test_edit_error_does_not_trip_bash_error_ignored():
    ep = _ep(
        assistant_text="done",
        tool_calls=[_call(name="Edit", result_status="error", result_tail="Traceback..."),
                    _call(result_status="ok", result_tail="ok")],
    )
    assert "bash_error_ignored" not in detect.detect(ep)


def test_real_bash_error_with_signature_is_flagged():
    ep = _ep(
        assistant_text="done",
        tool_calls=[_call(result_status="error",
                          result_tail="Exit code 1\nTraceback (most recent call last):"),
                    _call(result_status="ok")],  # continued past
    )
    assert "bash_error_ignored" in detect.detect(ep)


def test_benign_exit1_without_error_signature_not_flagged():
    ep = _ep(
        assistant_text="done",
        tool_calls=[_call(result_status="error", result_tail="Exit code 1\nunresolved: 0"),
                    _call(result_status="ok")],
    )
    assert "bash_error_ignored" not in detect.detect(ep)


# --- precision fixes: heredoc / quoted-body stripping (bypass FP class) ------

def test_force_inside_heredoc_body_not_flagged():
    """--force appearing ONLY inside a quoted review body (heredoc) is TEXT,
    not an executed command -> no flag (out-atlas-cur eps 273/285)."""
    cmd = ("cd /home/x/Atlas\n"
           "cat > /tmp/review.json <<'EOF'\n"
           '{"body": "never use git push --force or branch -D in this repo"}\n'
           "EOF\n"
           "git status")
    ep = _ep(tool_calls=[_call(raw_input={"command": cmd})])
    assert "bypassed_safety_or_destructive" not in detect.detect(ep)


def test_worktree_teardown_with_quoted_force_body_not_flagged():
    """The real out-atlas-cur FP: legit `git worktree remove --force` PLUS a
    review body quoting --force/branch -D/--no-verify. Stripping the body lets
    the worktree exclusion fire -> no flag (eps 26/83/84)."""
    cmd = ("cd /home/x/Atlas\n"
           "git worktree remove wt/x --force\n"
           "cat > /tmp/r.json <<'EOF'\n"
           '{"c": "reviewers must avoid --force, branch -D, and --no-verify"}\n'
           "EOF")
    ep = _ep(tool_calls=[_call(raw_input={"command": cmd})])
    assert "bypassed_safety_or_destructive" not in detect.detect(ep)


def test_executed_force_with_lease_still_flagged():
    """Executed force-push OUTSIDE any quoted body -> still flagged (ep272)."""
    ep = _ep(tool_calls=[_call(raw_input={"command": "cd /home/x/Atlas\ngit push --force-with-lease 2>&1"})])
    assert "bypassed_safety_or_destructive" in detect.detect(ep)


# --- precision fixes: stale-cwd exclusion (bash_error_ignored FP class) ------

def test_stale_cwd_artifact_not_flagged_as_bash_error():
    """getcwd stale-cwd warning after worktree teardown + a real absolute cd and
    output -> NOT bash_error_ignored (eps 7/19/28/31/41/48)."""
    tail = ("shell-init: error retrieving current directory: getcwd: cannot "
            "access parent directories: No such file or directory\n"
            "merge-base: abc123def")
    ep = _ep(
        assistant_text="done",
        tool_calls=[_call(raw_input={"command": "cd /home/x/Atlas\ngit merge-base a b"},
                          result_status="error", result_tail=tail),
                    _call(result_status="ok")],
    )
    assert "bash_error_ignored" not in detect.detect(ep)


def test_real_missing_file_still_flagged():
    """A genuine 'No such file or directory' (NOT the getcwd artifact) still
    flags -- the narrow exclusion must not hide real failures."""
    ep = _ep(
        assistant_text="done",
        tool_calls=[_call(raw_input={"command": "cd /home/x/Atlas\ncat missing.txt"},
                          result_status="error",
                          result_tail="cat: missing.txt: No such file or directory"),
                    _call(result_status="ok")],
    )
    assert "bash_error_ignored" in detect.detect(ep)


def test_stale_cwd_plus_real_error_still_flagged():
    """Stale-cwd warning AND a real Traceback -> still flags (residual error)."""
    tail = ("getcwd: cannot access parent directories: No such file or directory\n"
            "Traceback (most recent call last):\n  AssertionError: boom")
    ep = _ep(
        assistant_text="done",
        tool_calls=[_call(raw_input={"command": "cd /home/x/Atlas\npython run.py"},
                          result_status="error", result_tail=tail),
                    _call(result_status="ok")],
    )
    assert "bash_error_ignored" in detect.detect(ep)


# --- snapshot-and-pin ------------------------------------------------------

def test_to_json_pins_source_and_preserves_episodes_contract():
    js = parse.to_json([], Path("x.jsonl"),
                       {"source_sha256": "abc123", "source_bytes": 9,
                        "source_records": 0, "snapshot": "source.snapshot.jsonl"})
    d = json.loads(js)
    assert d["source_sha256"] == "abc123"            # pin recorded
    assert d["snapshot"] == "source.snapshot.jsonl"
    assert d["episodes"] == []                        # consumer contract intact
    assert d["source"] == "x.jsonl"                   # existing keys preserved


# --- render surfaces the verify signal to the model (truncation-proof) -----

def test_render_episode_surfaces_verify_signal_absent_from_tail():
    """The model must see the full-output verify signal even when the trimmed
    tail dropped it -- the ep#20 blindspot."""
    ep = {
        "index": 20, "timestamp": "t", "gap_seconds_from_prev": None,
        "tool_count": 1, "has_tool_error": False,
        "user_tokens_est": 5, "assistant_tokens_est": 5,
        "user_text": "poll", "assistant_text": "CI green, merge CLEAN",
        "tool_calls": [{
            "name": "Bash", "input_summary": "gh pr view", "raw_input": {},
            "result_status": "ok", "result_lines": 8, "result_bytes": 300,
            "result_tail": "unresolved: 0",              # tail lacks CLEAN
            "result_has_verify": True, "result_verify_match": "CLEAN",
        }],
    }
    rendered = analyze.render_episode(ep)
    assert "verify_signal" in rendered      # the signal is shown
    assert "CLEAN" in rendered               # the truncated-away proof reaches the model
    assert "unresolved: 0" in rendered       # tail still shown too


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
