"""Regression tests for the parse/detect truncation + precision fixes.

Run: python -m pytest test_detect.py -q   (or: python test_detect.py)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
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
