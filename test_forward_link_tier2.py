"""Tests for forward_link_tier2.py (Tier 2 session -> PR link).

Dual-mode: `python -m pytest test_forward_link_tier2.py -q` or
`python3 test_forward_link_tier2.py`.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forward_link_tier2 as t2  # noqa: E402


def _user(text: str) -> dict:
    return {
        "type": "user",
        "timestamp": "2026-01-01T00:00:00Z",
        "isSidechain": False,
        "message": {"role": "user", "content": text},
    }


def _assistant(tool_id: str, command: str) -> dict:
    return {
        "type": "assistant",
        "timestamp": "2026-01-01T00:00:01Z",
        "isSidechain": False,
        "message": {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": tool_id,
                "name": "Bash",
                "input": {"command": command},
            }],
        },
    }


def _tool_result(tool_id: str, stdout: str) -> dict:
    return {
        "type": "user",
        "timestamp": "2026-01-01T00:00:02Z",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": stdout,
            }],
        },
        "toolUseResult": {"stdout": stdout, "stderr": ""},
    }


def _terminal() -> dict:
    return {
        "type": "pr-link",
        "sessionId": "session-1",
        "timestamp": "2026-01-01T00:00:03Z",
        "prNumber": 2002,
        "prRepository": "canfieldjuan/ATLAS",
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def _write_pinned_pair(tmp_path: Path, records: list[dict]):
    snapshot = tmp_path / "source.snapshot.jsonl"
    _write_jsonl(snapshot, records)
    raw = snapshot.read_bytes()
    episodes = tmp_path / "episodes.json"
    episodes.write_text(json.dumps({
        "snapshot": snapshot.name,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_records": len(records),
        "episode_count": 1,
        "episodes": [],
    }), encoding="utf-8")
    return episodes, snapshot


def _create_records() -> list[dict]:
    return [
        _user("build it"),
        _assistant(
            "tool-1",
            "gh pr create --repo canfieldjuan/ATLAS --base main --head branch",
        ),
        _tool_result(
            "tool-1",
            "SELF-CORRECTION PR = #2002\n"
            "https://github.com/canfieldjuan/ATLAS/issues/2000#issuecomment-1",
        ),
        _terminal(),
    ]


def test_validate_transcript_pin_accepts_pinned_terminal_snapshot(tmp_path):
    episodes, snapshot = _write_pinned_pair(tmp_path, _create_records())
    payload, records, meta = t2.validate_transcript_pin(episodes, snapshot)
    assert payload["source_records"] == 4
    assert len(records) == 4
    assert meta["terminal_marker"] == "pr-link"
    assert meta["session_id"] == "session-1"


def test_validate_transcript_pin_fails_on_sha_mismatch(tmp_path):
    episodes, snapshot = _write_pinned_pair(tmp_path, _create_records())
    data = json.loads(episodes.read_text())
    data["source_sha256"] = "bad"
    episodes.write_text(json.dumps(data), encoding="utf-8")
    raised = False
    try:
        t2.validate_transcript_pin(episodes, snapshot)
    except SystemExit as exc:
        raised = True
        assert "source_sha256 mismatch" in str(exc)
    assert raised


def test_validate_transcript_pin_fails_without_terminal_marker(tmp_path):
    records = _create_records()[:-1]
    episodes, snapshot = _write_pinned_pair(tmp_path, records)
    raised = False
    try:
        t2.validate_transcript_pin(episodes, snapshot)
    except SystemExit as exc:
        raised = True
        assert "missing terminal snapshot marker" in str(exc)
    assert raised


def test_extract_pr_create_actions_reads_full_tool_output():
    actions = t2.extract_pr_create_actions(_create_records(), "canfieldjuan/ATLAS")
    assert len(actions) == 1
    assert actions[0]["pr"] == 2002
    assert actions[0]["episode_index"] == 0
    assert actions[0]["tool_result_line"] == 3


def test_extract_pr_create_actions_ignores_non_create_and_wrong_repo():
    records = [
        _user("review it"),
        _assistant("tool-view", "gh pr view 2002 --repo canfieldjuan/ATLAS"),
        _tool_result("tool-view", "https://github.com/canfieldjuan/ATLAS/pull/2002"),
        _assistant("tool-other", "gh pr create --repo other/repo"),
        _tool_result("tool-other", "https://github.com/other/repo/pull/99"),
        _terminal(),
    ]
    assert t2.extract_pr_create_actions(records, "canfieldjuan/ATLAS") == []


def test_build_session_links_only_links_created_earlier_pr():
    tier1 = [
        {"earlier_pr": 2002, "fix_forward_pr": 2004, "forward_link_key": "fix_forward"},
        {"earlier_pr": 1994, "fix_forward_pr": 2004, "forward_link_key": "fix_forward"},
    ]
    actions = t2.extract_pr_create_actions(_create_records(), "canfieldjuan/ATLAS")
    tier1_meta = {
        "tier1_corpus": {"repo": "canfieldjuan/ATLAS"},
        "tier1_sha256": "tier1-sha",
    }
    transcript_meta = {
        "episodes_path": "episodes.json",
        "snapshot_path": "source.snapshot.jsonl",
        "source_sha256": "source-sha",
        "source_records": 4,
        "episode_count": 1,
        "terminal_marker": "pr-link",
        "session_id": "session-1",
    }
    links = t2.build_session_links(tier1, actions, tier1_meta, transcript_meta)
    assert links[0]["classification"] == "confirmed"
    assert links[0]["episode_index"] == 0
    assert links[1]["classification"] == "could_not_determine"
    assert "No strong PR-create evidence" in links[1]["note"]


def test_render_doc_names_building_bias_and_counts():
    tier1_meta = {"tier1_sha256": "tier1-sha"}
    transcript_meta = {
        "source_sha256": "source-sha",
        "source_records": 4,
        "episode_count": 1,
        "terminal_marker": "pr-link",
    }
    records = [
        {
            "classification": "confirmed",
            "earlier_pr": 2002,
            "fix_forward_pr": 2004,
            "episode_index": 0,
            "evidence": [{"location": "source.snapshot.jsonl:line 3"}],
        },
        {"classification": "could_not_determine", "earlier_pr": 1994, "fix_forward_pr": 2004},
    ]
    doc = t2.render_doc(tier1_meta, transcript_meta, records, [{"pr": 2002}])
    assert "building-biased" in doc
    assert "confirmed session links: 1" in doc
    assert "| #2002 | #2004 | 0 |" in doc


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            if "tmp_path" in fn.__code__.co_varnames:
                import tempfile
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
