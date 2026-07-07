#!/usr/bin/env python3
"""
forward_link_tier2.py -- Tier 2 session -> PR link for fix-forward records.

Tier 1 proves an earlier PR was later fixed forward. This slice links that
earlier PR back to transcript evidence only when the pinned raw session shows
this session actually created the PR. It deliberately does NOT infer authorship
from mentions, reviews, comments, or `gh pr view`.

Usage:
  python3 forward_link_tier2.py [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from parse import (
    extract_assistant_blocks,
    extract_tool_results,
    extract_user_text,
    is_pure_tool_result,
)

REPO_DEFAULT = "canfieldjuan/ATLAS"
TIER1_DEFAULT = Path("out-atlas-fwd/forward-links.jsonl")
EPISODES_DEFAULT = Path("out-atlas-cur/episodes.json")
SNAPSHOT_DEFAULT = Path("out-atlas-cur/source.snapshot.jsonl")
OUT_DIR_DEFAULT = Path("out-atlas-fwd")
DOC_DEFAULT = Path("docs/forward-link-tier2-session-links.md")

TERMINAL_SNAPSHOT_TYPES = {"pr-link"}
PULL_URL_RE = re.compile(r"github\.com/[\w.-]+/[\w.-]+/pull/(\d+)")
ECHOED_PR_RE = re.compile(r"\b[A-Z][A-Z0-9 _-]*PR\s*=\s*#?(\d+)\b")
REPO_ARG_RE = re.compile(r"--repo\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl_strict(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            try:
                records.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no} malformed JSON: {exc}") from exc
    return records


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} malformed JSON: {exc}") from exc


def validate_transcript_pin(episodes_path: Path, snapshot_path: Path) -> tuple[dict, list[dict], dict]:
    """Fail closed unless the parsed artifact is pinned to the raw snapshot."""
    payload = load_json(episodes_path)
    if payload.get("snapshot") != snapshot_path.name:
        raise SystemExit(
            f"{episodes_path}: snapshot field {payload.get('snapshot')!r} "
            f"does not match {snapshot_path.name!r}"
        )
    actual_sha = _sha256(snapshot_path)
    if payload.get("source_sha256") != actual_sha:
        raise SystemExit(
            f"{episodes_path}: source_sha256 mismatch "
            f"(expected {payload.get('source_sha256')}, got {actual_sha})"
        )
    records = read_jsonl_strict(snapshot_path)
    if payload.get("source_records") != len(records):
        raise SystemExit(
            f"{episodes_path}: source_records mismatch "
            f"(expected {payload.get('source_records')}, got {len(records)})"
        )
    if not records or records[-1].get("type") not in TERMINAL_SNAPSHOT_TYPES:
        raise SystemExit(
            f"{snapshot_path}: missing terminal snapshot marker "
            f"(last type={records[-1].get('type') if records else None!r})"
        )
    meta = {
        "episodes_path": str(episodes_path),
        "snapshot_path": str(snapshot_path),
        "source_sha256": actual_sha,
        "source_records": len(records),
        "episode_count": payload.get("episode_count"),
        "terminal_marker": records[-1].get("type"),
        "session_id": records[-1].get("sessionId"),
        "snapshot_timestamp": records[-1].get("timestamp"),
    }
    return payload, records, meta


def _repo_from_command(command: str) -> str | None:
    m = REPO_ARG_RE.search(command or "")
    return m.group(1) if m else None


def _created_pr_number(output: str) -> int | None:
    m = PULL_URL_RE.search(output or "")
    if m:
        return int(m.group(1))
    m = ECHOED_PR_RE.search(output or "")
    if m:
        return int(m.group(1))
    return None


def extract_pr_create_actions(raw_records: list[dict], repo: str,
                              snapshot_name: str = SNAPSHOT_DEFAULT.name) -> list[dict]:
    """Strong build evidence: `gh pr create` command plus PR number in tool output."""
    episode_index = -1
    tool_map: dict[str, dict] = {}
    actions = []

    for line_no, rec in enumerate(raw_records, 1):
        if rec.get("isSidechain"):
            continue
        msg = rec.get("message") or {}
        role = msg.get("role") or rec.get("type")
        content = msg.get("content")

        if role == "user":
            if is_pure_tool_result(content):
                tool_result = rec.get("toolUseResult") or {}
                for tr in extract_tool_results(content):
                    tool = tool_map.get(tr["tool_use_id"])
                    if tool is None:
                        continue
                    command = tool["input"].get("command", "")
                    if "gh pr create" not in command:
                        continue
                    command_repo = _repo_from_command(command)
                    if command_repo != repo:
                        continue
                    output = "\n".join(
                        s for s in [
                            tool_result.get("stdout") or tr.get("content") or "",
                            tool_result.get("stderr") or "",
                        ] if s
                    )
                    pr_number = _created_pr_number(output)
                    if pr_number is None:
                        continue
                    actions.append({
                        "repo": repo,
                        "pr": pr_number,
                        "episode_index": tool["episode_index"],
                        "episode_timestamp": tool["episode_timestamp"],
                        "tool_use_id": tr["tool_use_id"],
                        "tool_result_line": line_no,
                        "assistant_line": tool["assistant_line"],
                        "command": command,
                        "evidence": f"{snapshot_name}:line {line_no} gh pr create -> #{pr_number}",
                    })
                continue

            user_text = extract_user_text(content)
            if user_text:
                episode_index += 1
                tool_map = {}
            continue

        if role == "assistant" and episode_index >= 0:
            _, tool_uses = extract_assistant_blocks(content)
            for tu in tool_uses:
                if not tu.get("id"):
                    continue
                raw_input = tu.get("input") if isinstance(tu.get("input"), dict) else {}
                tool_map[tu["id"]] = {
                    "episode_index": episode_index,
                    "episode_timestamp": rec.get("timestamp"),
                    "assistant_line": line_no,
                    "input": raw_input,
                }

    return actions


def read_tier1_confirmed(path: Path) -> tuple[list[dict], dict]:
    records = read_jsonl_strict(path)
    confirmed = [r for r in records if r.get("classification") == "confirmed"]
    corpus = records[0].get("corpus", {}) if records else {}
    meta = {
        "tier1_path": str(path),
        "tier1_sha256": _sha256(path),
        "tier1_records": len(records),
        "tier1_confirmed": len(confirmed),
        "tier1_corpus": corpus,
    }
    return confirmed, meta


def build_session_links(tier1_records: list[dict], actions: list[dict],
                        tier1_meta: dict, transcript_meta: dict) -> list[dict]:
    by_pr: dict[int, dict] = {}
    for action in sorted(actions, key=lambda a: (a["episode_index"], a["tool_result_line"])):
        by_pr.setdefault(action["pr"], action)

    out = []
    for r in tier1_records:
        earlier = r["earlier_pr"]
        base = {
            "dataset": "out-atlas-fwd",
            "record": "session_pr_link",
            "forward_link_key": r.get("forward_link_key"),
            "earlier_pr": earlier,
            "fix_forward_pr": r["fix_forward_pr"],
            "tier1_corpus": tier1_meta["tier1_corpus"],
            "tier1_sha256": tier1_meta["tier1_sha256"],
            "transcript": {
                "episodes_path": transcript_meta["episodes_path"],
                "snapshot_path": transcript_meta["snapshot_path"],
                "source_sha256": transcript_meta["source_sha256"],
                "source_records": transcript_meta["source_records"],
                "episode_count": transcript_meta["episode_count"],
                "terminal_marker": transcript_meta["terminal_marker"],
                "session_id": transcript_meta["session_id"],
            },
        }
        action = by_pr.get(earlier)
        if action is None:
            base.update({
                "classification": "could_not_determine",
                "tags": [],
                "note": "No strong PR-create evidence for the earlier PR in this pinned transcript.",
            })
        else:
            base.update({
                "classification": "confirmed",
                "tags": ["TIER2_SESSION_PR_LINK"],
                "episode_index": action["episode_index"],
                "episode_timestamp": action["episode_timestamp"],
                "evidence": [{
                    "kind": "tool_result",
                    "location": action["evidence"],
                    "tool_use_id": action["tool_use_id"],
                    "assistant_line": action["assistant_line"],
                    "tool_result_line": action["tool_result_line"],
                    "quote_or_summary": f"gh pr create output created PR #{earlier}",
                }],
            })
        out.append(base)
    return out


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=True) + "\n")


def render_doc(tier1_meta: dict, transcript_meta: dict, records: list[dict],
               actions: list[dict]) -> str:
    confirmed = [r for r in records if r["classification"] == "confirmed"]
    cnd = [r for r in records if r["classification"] == "could_not_determine"]
    linked_prs = sorted({r["earlier_pr"] for r in confirmed})
    lines = [
        "# Forward-Link Findings -- Tier 2 (session -> PR)",
        "",
        "Status: partial session linkage for Tier-1 fix-forward records. This is",
        "building-biased evidence, not a promoted pattern or CI gate.",
        "",
        "Source artifacts, local only:",
        "- `out-atlas-fwd/session-pr-links.jsonl`",
        "- `out-atlas-cur/source.snapshot.jsonl`",
        "",
        "Input pins:",
        f"- Tier-1 jsonl sha256: `{tier1_meta['tier1_sha256']}`",
        f"- transcript sha256: `{transcript_meta['source_sha256']}`",
        f"- transcript records: `{transcript_meta['source_records']}`",
        f"- transcript episodes: `{transcript_meta['episode_count']}`",
        f"- terminal marker: `{transcript_meta['terminal_marker']}`",
        "",
        "## Method",
        "",
        "A Tier-1 earlier PR is linked only when the pinned raw snapshot contains",
        "strong build evidence: a `gh pr create` command for `canfieldjuan/ATLAS`",
        "and full tool output containing the created PR number. Plain mentions,",
        "`gh pr view`, review comments, merge commands, and `pr-link` metadata are",
        "ignored because they do not prove this session built the PR.",
        "",
        "The run fails closed if `episodes.json` no longer matches the raw snapshot",
        "by sha256, record count, snapshot filename, or terminal snapshot marker.",
        "",
        "## Result",
        "",
        f"- Tier-1 confirmed records considered: {len(records)}",
        f"- confirmed session links: {len(confirmed)}",
        f"- could_not_determine: {len(cnd)}",
        f"- unique PRs created in this transcript: {len({a['pr'] for a in actions})}",
        f"- linked earlier PRs: {', '.join(f'#{n}' for n in linked_prs) if linked_prs else 'none'}",
        "",
        "## Confirmed Links",
        "",
        "| earlier PR | fix-forward PR | episode | evidence |",
        "|---:|---:|---:|---|",
    ]
    if confirmed:
        for r in confirmed:
            ev = r["evidence"][0]
            lines.append(
                f"| #{r['earlier_pr']} | #{r['fix_forward_pr']} | "
                f"{r['episode_index']} | `{ev['location']}` |"
            )
    else:
        lines.append("| - | - | - | none |")
    lines += [
        "",
        "## Caveats",
        "",
        "- This is **building-biased** by construction. Review-only and planning-only",
        "  sessions usually do not create PRs, so they remain invisible here.",
        "- `could_not_determine` does not mean no session exists. It means this pinned",
        "  transcript lacks strong PR-create evidence for that earlier PR.",
        "- Do not promote prevention triples from this file alone. The linked episode",
        "  still needs Layer-2 reconstruction with cited transcript spans.",
        "",
        "## Deferred",
        "- Multi-session Atlas transcript index.",
        "- Weak/touched PR diagnostics.",
        "- Layer-2 adjudication of linked episodes.",
    ]
    return "\n".join(lines) + "\n"


def _dry_run(args) -> None:
    print("DRY RUN -- forward_link_tier2.py Tier 2 (no execution)")
    print(f"  repo: {args.repo}")
    print(f"  Tier-1 input: {args.tier1}")
    print(f"  episodes input: {args.episodes}")
    print(f"  snapshot input: {args.snapshot}")
    print("  checks:")
    print("    1. episodes snapshot filename, sha256, and source_records match raw snapshot")
    print("    2. raw snapshot ends with a terminal marker")
    print("    3. extract only gh-pr-create + full-output PR numbers")
    print("    4. link only Tier-1 confirmed earlier_pr records")
    print("    5. write out-atlas-fwd/session-pr-links.jsonl + docs/forward-link-tier2-session-links.md")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--tier1", type=Path, default=TIER1_DEFAULT)
    ap.add_argument("--episodes", type=Path, default=EPISODES_DEFAULT)
    ap.add_argument("--snapshot", type=Path, default=SNAPSHOT_DEFAULT)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR_DEFAULT)
    ap.add_argument("--doc", type=Path, default=DOC_DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        _dry_run(args)
        return

    _, raw_records, transcript_meta = validate_transcript_pin(args.episodes, args.snapshot)
    tier1_records, tier1_meta = read_tier1_confirmed(args.tier1)
    actions = extract_pr_create_actions(raw_records, args.repo, args.snapshot.name)
    records = build_session_links(tier1_records, actions, tier1_meta, transcript_meta)

    out_path = args.out_dir / "session-pr-links.jsonl"
    write_jsonl(out_path, records)
    args.doc.write_text(render_doc(tier1_meta, transcript_meta, records, actions),
                        encoding="utf-8")

    confirmed = sum(1 for r in records if r["classification"] == "confirmed")
    print(f"forward-link Tier 2: {confirmed}/{len(records)} Tier-1 records linked")
    print(f"  PR-create actions in transcript: {len(actions)}")
    print(f"  wrote {out_path} (gitignored) + {args.doc}")


if __name__ == "__main__":
    main()
